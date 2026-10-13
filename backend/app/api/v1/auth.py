"""
Authentication API endpoints.

API endpoints:
- POST /api/v1/auth/register
- POST /api/v1/auth/login
- POST /api/v1/auth/refresh
- POST /api/v1/auth/logout
- GET  /api/v1/auth/me
- POST /api/v1/auth/forgot-password
- POST /api/v1/auth/reset-password
"""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Body
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import Auth, CurrentUser
from app.models.user import UserCreate, UserResponse
from app.services.auth_service import (
    UserAlreadyExistsError,
    InvalidCredentialsError,
    InvalidTokenError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Request/Response models
class LoginRequest(BaseModel):
    """Login request model."""

    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., min_length=1, description="User password")


class TokenResponse(BaseModel):
    """Token response model."""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")


class AuthResponse(BaseModel):
    """Authentication response with user and tokens."""

    user: UserResponse = Field(..., description="User details")
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")


class RefreshRequest(BaseModel):
    """Token refresh request model."""

    refresh_token: str = Field(..., description="Refresh token")


class LogoutRequest(BaseModel):
    """Logout request model."""

    refresh_token: str = Field(..., description="Refresh token to invalidate")


class ForgotPasswordRequest(BaseModel):
    """Forgot password request model."""

    email: EmailStr = Field(..., description="User email")


class ResetPasswordRequest(BaseModel):
    """Reset password request model."""

    token: str = Field(..., description="Reset token")
    password: str = Field(..., min_length=8, max_length=128, description="New password")


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str = Field(..., description="Response message")


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account and return authentication tokens.",
)
async def register(
    user_data: UserCreate,
    auth_service: Auth,
) -> AuthResponse:
    """
    Register a new user account.

    - Validates user data
    - Creates user with free tier subscription
    - Returns user info and JWT tokens
    """
    try:
        user, access_token, refresh_token = await auth_service.register(user_data)
        logger.info(f"New user registered: {user.email}")

        return AuthResponse(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except UserAlreadyExistsError as e:
        logger.warning(f"Registration failed - user exists: {user_data.email}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": e.message, "code": e.code},
        )


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="User login",
    description="Authenticate user and return JWT tokens.",
)
async def login(
    credentials: LoginRequest,
    auth_service: Auth,
) -> AuthResponse:
    """
    Authenticate user with email and password.

    - Validates credentials
    - Updates last login timestamp
    - Returns user info and JWT tokens
    """
    try:
        user, access_token, refresh_token = await auth_service.login(
            credentials.email, credentials.password
        )

        return AuthResponse(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except InvalidCredentialsError as e:
        logger.warning(f"Login failed for email: {credentials.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": e.message, "code": e.code},
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh tokens",
    description="Get new access and refresh tokens using a valid refresh token.",
)
async def refresh_tokens(
    request: RefreshRequest,
    auth_service: Auth,
) -> TokenResponse:
    """
    Refresh authentication tokens.

    - Validates refresh token
    - Invalidates old refresh token
    - Returns new token pair
    """
    try:
        access_token, refresh_token = await auth_service.refresh_tokens(
            request.refresh_token
        )
        logger.debug("Tokens refreshed successfully")

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": e.message, "code": e.code},
        )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="User logout",
    description="Invalidate refresh token and end session.",
)
async def logout(
    request: LogoutRequest,
    auth_service: Auth,
) -> MessageResponse:
    """
    Logout user by invalidating refresh token.

    - Deletes refresh token session
    - Access token remains valid until expiration
    """
    deleted = await auth_service.logout(request.refresh_token)

    if deleted:
        logger.debug("User logged out successfully")
        return MessageResponse(message="Logged out successfully")

    return MessageResponse(message="Session not found or already expired")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Get the currently authenticated user's information.",
)
async def get_current_user_info(
    current_user: CurrentUser,
) -> UserResponse:
    """
    Get current user information.

    Requires valid access token in Authorization header.
    """
    return current_user


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request password reset",
    description="Send password reset email to user.",
)
async def forgot_password(
    request: ForgotPasswordRequest,
    auth_service: Auth,
) -> MessageResponse:
    """
    Request password reset.

    - Always returns success to prevent email enumeration
    - Sends reset email if user exists

    Note: Email sending not implemented in MVP - returns placeholder response.
    """
    # TODO: Implement password reset email sending
    logger.info(f"Password reset requested for: {request.email}")

    # Always return success to prevent email enumeration
    return MessageResponse(
        message="If an account with that email exists, a password reset link has been sent."
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password",
    description="Reset password using token from reset email.",
)
async def reset_password(
    request: ResetPasswordRequest,
    auth_service: Auth,
) -> MessageResponse:
    """
    Reset password with token.

    - Validates reset token
    - Updates user password
    - Invalidates all existing sessions

    Note: Not fully implemented in MVP.
    """
    # TODO: Implement password reset with token validation
    logger.info("Password reset attempted")

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "detail": "Password reset not yet implemented",
            "code": "NOT_IMPLEMENTED",
        },
    )
