"""
Authentication service handling user registration, login, and token management.

JWT + OAuth 2.0 for authentication.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.user import (
    User,
    UserCreate,
    UserInDB,
    UserResponse,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    UserSettings,
)
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_REFRESH,
)
from jose import JWTError

logger = logging.getLogger(__name__)


class AuthServiceError(Exception):
    """Base exception for auth service errors."""

    def __init__(self, message: str, code: str):
        self.message = message
        self.code = code
        super().__init__(message)


class UserAlreadyExistsError(AuthServiceError):
    """Raised when attempting to register with existing email."""

    def __init__(self, email: str):
        super().__init__(
            message=f"User with email {email} already exists",
            code="USER_ALREADY_EXISTS",
        )


class InvalidCredentialsError(AuthServiceError):
    """Raised when login credentials are invalid."""

    def __init__(self):
        super().__init__(
            message="Invalid email or password",
            code="INVALID_CREDENTIALS",
        )


class InvalidTokenError(AuthServiceError):
    """Raised when token is invalid or expired."""

    def __init__(self, reason: str = "Invalid or expired token"):
        super().__init__(
            message=reason,
            code="INVALID_TOKEN",
        )


class UserNotFoundError(AuthServiceError):
    """Raised when user is not found."""

    def __init__(self, identifier: str):
        super().__init__(
            message=f"User not found: {identifier}",
            code="USER_NOT_FOUND",
        )


class AuthService:
    """Service for authentication operations."""

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize auth service.

        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.users_collection = db["users"]
        self.sessions_collection = db["sessions"]

    async def register(self, user_data: UserCreate) -> Tuple[UserResponse, str, str]:
        """
        Register a new user.

        Args:
            user_data: User registration data

        Returns:
            Tuple of (user response, access token, refresh token)

        Raises:
            UserAlreadyExistsError: If email is already registered
        """
        # Check if user exists
        existing = await self.users_collection.find_one(
            {"email": user_data.email.lower()}
        )
        if existing:
            logger.warning(f"Registration attempt with existing email: {user_data.email}")
            raise UserAlreadyExistsError(user_data.email)

        # Create user document
        now = datetime.utcnow()
        user_doc = {
            "email": user_data.email.lower(),
            "password_hash": hash_password(user_data.password),
            "name": user_data.name,
            "avatar_url": None,
            "subscription": Subscription(
                plan=SubscriptionPlan.FREE,
                status=SubscriptionStatus.ACTIVE,
                minutes_included=50,  # Free tier minutes
                minutes_used=0,
            ).model_dump(),
            "settings": UserSettings().model_dump(),
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        }

        # Insert user
        result = await self.users_collection.insert_one(user_doc)
        user_id = str(result.inserted_id)

        logger.info(f"User registered successfully: {user_id}")

        # Generate tokens
        access_token = create_access_token(subject=user_id)
        refresh_token = create_refresh_token(subject=user_id)

        # Store refresh token session
        await self._create_session(user_id, refresh_token)

        # Build response
        user_doc["_id"] = result.inserted_id
        user_response = UserResponse.model_validate(user_doc)

        return user_response, access_token, refresh_token

    async def login(
        self, email: str, password: str
    ) -> Tuple[UserResponse, str, str]:
        """
        Authenticate user and return tokens.

        Args:
            email: User email
            password: User password

        Returns:
            Tuple of (user response, access token, refresh token)

        Raises:
            InvalidCredentialsError: If credentials are invalid
        """
        # Find user
        user_doc = await self.users_collection.find_one({"email": email.lower()})
        if not user_doc:
            logger.warning(f"Login attempt for non-existent user: {email}")
            raise InvalidCredentialsError()

        # Verify password
        if not verify_password(password, user_doc["password_hash"]):
            logger.warning(f"Failed login attempt for user: {email}")
            raise InvalidCredentialsError()

        user_id = str(user_doc["_id"])

        # Update last login
        await self.users_collection.update_one(
            {"_id": user_doc["_id"]},
            {"$set": {"last_login_at": datetime.utcnow()}},
        )

        # Generate tokens
        access_token = create_access_token(subject=user_id)
        refresh_token = create_refresh_token(subject=user_id)

        # Store refresh token session
        await self._create_session(user_id, refresh_token)

        logger.info(f"User logged in successfully: {user_id}")

        # Build response
        user_response = UserResponse.model_validate(user_doc)

        return user_response, access_token, refresh_token

    async def refresh_tokens(self, refresh_token: str) -> Tuple[str, str]:
        """
        Refresh access token using refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            Tuple of (new access token, new refresh token)

        Raises:
            InvalidTokenError: If refresh token is invalid
        """
        try:
            payload = decode_token(refresh_token)
        except JWTError as e:
            logger.warning(f"Invalid refresh token: {e}")
            raise InvalidTokenError("Invalid or expired refresh token")

        # Verify token type
        if payload.get("type") != TOKEN_TYPE_REFRESH:
            raise InvalidTokenError("Invalid token type")

        user_id = payload.get("sub")
        if not user_id:
            raise InvalidTokenError("Invalid token payload")

        # Verify session exists
        session = await self.sessions_collection.find_one(
            {"user_id": user_id, "refresh_token": refresh_token}
        )
        if not session:
            logger.warning(f"Refresh token session not found for user: {user_id}")
            raise InvalidTokenError("Session not found or expired")

        # Delete old session
        await self.sessions_collection.delete_one({"_id": session["_id"]})

        # Generate new tokens
        new_access_token = create_access_token(subject=user_id)
        new_refresh_token = create_refresh_token(subject=user_id)

        # Store new session
        await self._create_session(user_id, new_refresh_token)

        logger.info(f"Tokens refreshed for user: {user_id}")

        return new_access_token, new_refresh_token

    async def logout(self, refresh_token: str) -> bool:
        """
        Logout user by invalidating refresh token.

        Args:
            refresh_token: Refresh token to invalidate

        Returns:
            True if session was found and deleted
        """
        result = await self.sessions_collection.delete_one(
            {"refresh_token": refresh_token}
        )

        if result.deleted_count > 0:
            logger.info("User logged out successfully")
            return True

        return False

    async def logout_all(self, user_id: str) -> int:
        """
        Logout user from all sessions.

        Args:
            user_id: User ID

        Returns:
            Number of sessions invalidated
        """
        result = await self.sessions_collection.delete_many({"user_id": user_id})
        logger.info(f"Logged out {result.deleted_count} sessions for user: {user_id}")
        return result.deleted_count

    async def get_user_by_id(self, user_id: str) -> UserResponse:
        """
        Get user by ID.

        Args:
            user_id: User ID

        Returns:
            User response

        Raises:
            UserNotFoundError: If user not found
        """
        if not ObjectId.is_valid(user_id):
            raise UserNotFoundError(user_id)

        user_doc = await self.users_collection.find_one({"_id": ObjectId(user_id)})
        if not user_doc:
            raise UserNotFoundError(user_id)

        return UserResponse.model_validate(user_doc)

    async def validate_access_token(self, token: str) -> str:
        """
        Validate access token and return user ID.

        Args:
            token: JWT access token

        Returns:
            User ID from token

        Raises:
            InvalidTokenError: If token is invalid
        """
        try:
            payload = decode_token(token)
        except JWTError as e:
            logger.warning(f"Invalid access token: {e}")
            raise InvalidTokenError("Invalid or expired access token")

        # Verify token type
        if payload.get("type") != TOKEN_TYPE_ACCESS:
            raise InvalidTokenError("Invalid token type")

        user_id = payload.get("sub")
        if not user_id:
            raise InvalidTokenError("Invalid token payload")

        # Verify user exists
        exists = await self.users_collection.find_one(
            {"_id": ObjectId(user_id)},
            {"_id": 1},
        )
        if not exists:
            raise InvalidTokenError("User not found")

        return user_id

    async def _create_session(
        self, user_id: str, refresh_token: str
    ) -> None:
        """
        Create a session for refresh token.

        Args:
            user_id: User ID
            refresh_token: Refresh token
        """
        from app.config import get_settings

        settings = get_settings()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.jwt_refresh_token_expire_days
        )

        await self.sessions_collection.insert_one({
            "user_id": user_id,
            "refresh_token": refresh_token,
            "created_at": datetime.utcnow(),
            "expires_at": expires_at,
        })
