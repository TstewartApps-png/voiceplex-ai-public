"""
API dependencies for authentication, database access, and authorization.

- Clean dependency injection via FastAPI's Depends
- Tenant isolation: every query scoped by company_id/user_id
- Access control checks on every API endpoint
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

from app.database import get_database
from app.models.user import UserResponse, SubscriptionPlan
from app.models.subscription import get_plan_limits, PlanLimits
from app.services.auth_service import (
    AuthService,
    InvalidTokenError,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)

# HTTP Bearer token security scheme
bearer_scheme = HTTPBearer(auto_error=True)


async def get_db() -> AsyncIOMotorDatabase:
    """
    Dependency for database access.

    Returns:
        MongoDB database instance
    """
    return get_database()


async def get_auth_service(
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)]
) -> AuthService:
    """
    Dependency for auth service.

    Args:
        db: Database instance

    Returns:
        AuthService instance
    """
    return AuthService(db)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """
    Dependency for getting the current authenticated user.

    Args:
        credentials: Bearer token credentials
        auth_service: Auth service instance

    Returns:
        Current user

    Raises:
        HTTPException: If authentication fails
    """
    try:
        user_id = await auth_service.validate_access_token(credentials.credentials)
        user = await auth_service.get_user_by_id(user_id)
        return user
    except InvalidTokenError as e:
        logger.warning(f"Authentication failed: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": e.message, "code": e.code},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except UserNotFoundError as e:
        logger.warning(f"User not found during auth: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "User not found", "code": "USER_NOT_FOUND"},
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_optional(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse | None:
    """
    Dependency for optionally getting the current user.

    Returns None if not authenticated instead of raising an exception.

    Args:
        credentials: Optional bearer token credentials
        auth_service: Auth service instance

    Returns:
        Current user or None
    """
    if credentials is None:
        return None

    try:
        user_id = await auth_service.validate_access_token(credentials.credentials)
        user = await auth_service.get_user_by_id(user_id)
        return user
    except (InvalidTokenError, UserNotFoundError):
        return None


def get_plan_limits_for_user(user: UserResponse) -> PlanLimits:
    """
    Get plan limits for a user.

    Args:
        user: User response

    Returns:
        Plan limits for the user's subscription
    """
    return get_plan_limits(user.subscription.plan.value)


async def verify_company_access(
    company_id: str,
    user: UserResponse,
    db: AsyncIOMotorDatabase,
) -> dict:
    """
    Verify user has access to a company.

    Tenant isolation - every query scoped by user_id

    Args:
        company_id: Company ID to verify
        user: Current user
        db: Database instance

    Returns:
        Company document

    Raises:
        HTTPException: If company not found or access denied
    """
    if not ObjectId.is_valid(company_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Company not found", "code": "COMPANY_NOT_FOUND"},
        )

    company = await db["companies"].find_one({
        "_id": ObjectId(company_id),
        "user_id": user.id,
    })

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Company not found", "code": "COMPANY_NOT_FOUND"},
        )

    return company


async def verify_agent_access(
    agent_id: str,
    user: UserResponse,
    db: AsyncIOMotorDatabase,
) -> dict:
    """
    Verify user has access to an agent.

    Args:
        agent_id: Agent ID to verify
        user: Current user
        db: Database instance

    Returns:
        Agent document

    Raises:
        HTTPException: If agent not found or access denied
    """
    if not ObjectId.is_valid(agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Agent not found", "code": "AGENT_NOT_FOUND"},
        )

    agent = await db["agents"].find_one({
        "_id": ObjectId(agent_id),
        "user_id": user.id,
    })

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Agent not found", "code": "AGENT_NOT_FOUND"},
        )

    return agent


async def verify_call_access(
    call_id: str,
    user: UserResponse,
    db: AsyncIOMotorDatabase,
) -> dict:
    """
    Verify user has access to a call.

    Args:
        call_id: Call ID to verify
        user: Current user
        db: Database instance

    Returns:
        Call document

    Raises:
        HTTPException: If call not found or access denied
    """
    if not ObjectId.is_valid(call_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Call not found", "code": "CALL_NOT_FOUND"},
        )

    call = await db["calls"].find_one({
        "_id": ObjectId(call_id),
        "user_id": user.id,
    })

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Call not found", "code": "CALL_NOT_FOUND"},
        )

    return call


def check_subscription_limit(
    user: UserResponse,
    resource: str,
    current_count: int,
) -> None:
    """
    Check if user has reached subscription limit for a resource.

    Args:
        user: Current user
        resource: Resource type (agents, companies, etc.)
        current_count: Current count of the resource

    Raises:
        HTTPException: If limit reached
    """
    # DEV_MODE bypass - skip all limit checks for development
    from app.config import get_settings
    settings = get_settings()
    if settings.dev_mode:
        logger.debug(f"DEV_MODE: Bypassing subscription limit check for {resource}")
        return

    limits = get_plan_limits_for_user(user)

    limit_map = {
        "agents": limits.agents,
        "companies": limits.companies,
        "knowledge_items": limits.knowledge_items,
        "team_members": limits.team_members,
    }

    if resource not in limit_map:
        return

    limit = limit_map[resource]
    if current_count >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "detail": f"You have reached the {resource} limit for your plan. Please upgrade to add more.",
                "code": "SUBSCRIPTION_LIMIT_REACHED",
                "limit": limit,
                "current": current_count,
            },
        )


def check_minutes_available(user: UserResponse, minutes_needed: float = 0) -> None:
    """
    Check if user has minutes available.

    Args:
        user: Current user
        minutes_needed: Minutes needed for operation

    Raises:
        HTTPException: If insufficient minutes
    """
    available = user.subscription.minutes_included - user.subscription.minutes_used

    if available < minutes_needed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "detail": "Insufficient minutes available. Please upgrade your plan.",
                "code": "INSUFFICIENT_MINUTES",
                "available": available,
                "needed": minutes_needed,
            },
        )


# Type aliases for cleaner dependency injection
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
OptionalUser = Annotated[UserResponse | None, Depends(get_current_user_optional)]
Database = Annotated[AsyncIOMotorDatabase, Depends(get_db)]
Auth = Annotated[AuthService, Depends(get_auth_service)]
