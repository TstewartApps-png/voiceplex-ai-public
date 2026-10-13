"""
Integration API endpoints for OAuth connections.

OAuth integrations for Google and Microsoft services.
Handles OAuth flows, token management, and calendar operations.
"""

import logging
from datetime import datetime
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Database, verify_company_access
from app.config import get_settings
from app.services.integrations.google_calendar import (
    GoogleCalendarError,
    GoogleCalendarService,
    GOOGLE_CALENDAR_SCOPES,
)
from app.services.integrations.google_gmail import (
    GmailError,
    GoogleGmailService,
    GOOGLE_COMBINED_SCOPES,
    check_gmail_connected,
)
from app.services.integrations.microsoft_graph import (
    MicrosoftGraphError,
    MicrosoftGraphService,
    check_microsoft_connected,
)
from app.services.integrations.oauth_manager import (
    InvalidStateError,
    IntegrationNotConnectedError,
    OAuthError,
    TokenExpiredError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


# =============================================================================
# Response Models
# =============================================================================


class IntegrationStatusResponse(BaseModel):
    """Integration connection status."""

    provider: str
    connected: bool
    email: str | None = None
    scopes: list[str] = Field(default_factory=list)
    calendar_id: str | None = None
    expires_at: datetime | None = None


class IntegrationsListResponse(BaseModel):
    """List of all integration statuses."""

    google: IntegrationStatusResponse
    microsoft: IntegrationStatusResponse


class AuthUrlResponse(BaseModel):
    """OAuth authorization URL response."""

    auth_url: str
    provider: str


class CalendarResponse(BaseModel):
    """Calendar information."""

    id: str
    name: str
    description: str | None = None
    timezone: str | None = None
    primary: bool = False
    can_edit: bool = True


class CalendarListResponse(BaseModel):
    """List of calendars."""

    calendars: list[CalendarResponse]


class SetCalendarRequest(BaseModel):
    """Request to set default calendar."""

    calendar_id: str = Field(..., description="Calendar ID to set as default")


class DisconnectResponse(BaseModel):
    """Disconnect response."""

    success: bool
    message: str


class OAuthCallbackResponse(BaseModel):
    """OAuth callback success response."""

    success: bool
    provider: str
    email: str


# =============================================================================
# Status Endpoint
# =============================================================================


@router.get(
    "",
    response_model=IntegrationsListResponse,
    summary="Get integration status",
    description="Get connection status for all integrations for a company",
)
async def get_integration_status(
    company_id: str = Query(..., description="Company ID"),
    current_user: CurrentUser = None,
    db: Database = None,
):
    """Get status of all integrations for a company."""
    # Verify access
    company = await verify_company_access(company_id, current_user, db)
    integrations = company.get("integrations", {})

    google_data = integrations.get("google", {})
    microsoft_data = integrations.get("microsoft", {})

    return IntegrationsListResponse(
        google=IntegrationStatusResponse(
            provider="google",
            connected=google_data.get("connected", False),
            email=google_data.get("email"),
            scopes=google_data.get("scopes", []),
            calendar_id=google_data.get("calendar_id"),
            expires_at=google_data.get("token_expires_at"),
        ),
        microsoft=IntegrationStatusResponse(
            provider="microsoft",
            connected=microsoft_data.get("connected", False),
            email=microsoft_data.get("email"),
            scopes=[],  # Microsoft doesn't store scopes in same way
            calendar_id=microsoft_data.get("calendar_id"),
            expires_at=microsoft_data.get("token_expires_at"),
        ),
    )


# =============================================================================
# Google OAuth Endpoints
# =============================================================================


@router.get(
    "/google/auth-url",
    response_model=AuthUrlResponse,
    summary="Get Google OAuth URL",
    description="Generate OAuth authorization URL for Google Calendar/Gmail",
)
async def get_google_auth_url(
    company_id: str = Query(..., description="Company ID"),
    redirect_after: str | None = Query(None, description="URL to redirect after OAuth"),
    include_gmail: bool = Query(True, description="Include Gmail send permissions"),
    current_user: CurrentUser = None,
    db: Database = None,
):
    """Generate Google OAuth authorization URL."""
    # Verify access
    await verify_company_access(company_id, current_user, db)

    settings = get_settings()

    # Check if Google OAuth is configured
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "detail": "Google OAuth not configured",
                "code": "GOOGLE_NOT_CONFIGURED",
            },
        )

    # Generate OAuth URL
    auth_url = GoogleCalendarService.get_oauth_url(
        company_id=company_id,
        redirect_after=redirect_after,
    )

    return AuthUrlResponse(auth_url=auth_url, provider="google")


@router.get(
    "/google/callback",
    summary="Google OAuth callback",
    description="Handle OAuth callback from Google",
)
async def google_oauth_callback(
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="State parameter"),
    error: str | None = Query(None, description="Error from Google"),
):
    """Handle Google OAuth callback."""
    settings = get_settings()

    if error:
        logger.warning(f"Google OAuth error: {error}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard/integrations?error={error}"
        )

    try:
        result = await GoogleCalendarService.handle_oauth_callback(code, state)

        redirect_url = result.get("redirect_after") or f"{settings.frontend_url}/dashboard/integrations"
        return RedirectResponse(
            url=f"{redirect_url}?google_connected=true&email={result['email']}"
        )

    except InvalidStateError as e:
        logger.warning(f"Invalid Google OAuth state: {e}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard/integrations?error=invalid_state"
        )
    except GoogleCalendarError as e:
        logger.error(f"Google OAuth error: {e}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard/integrations?error=oauth_failed"
        )


@router.post(
    "/google/disconnect",
    response_model=DisconnectResponse,
    summary="Disconnect Google",
    description="Disconnect Google integration and revoke tokens",
)
async def disconnect_google(
    company_id: str = Query(..., description="Company ID"),
    current_user: CurrentUser = None,
    db: Database = None,
):
    """Disconnect Google integration."""
    await verify_company_access(company_id, current_user, db)

    success = await GoogleCalendarService.disconnect(company_id)

    return DisconnectResponse(
        success=success,
        message="Google integration disconnected" if success else "Failed to disconnect",
    )


@router.get(
    "/google/calendars",
    response_model=CalendarListResponse,
    summary="List Google calendars",
    description="List available Google Calendar calendars",
)
async def list_google_calendars(
    company_id: str = Query(..., description="Company ID"),
    current_user: CurrentUser = None,
    db: Database = None,
):
    """List Google calendars for a company."""
    await verify_company_access(company_id, current_user, db)

    try:
        service = GoogleCalendarService(company_id)
        calendars = await service.get_calendars()

        return CalendarListResponse(
            calendars=[
                CalendarResponse(
                    id=cal.id,
                    name=cal.name,
                    description=cal.description,
                    timezone=cal.timezone,
                    primary=cal.primary,
                    can_edit=cal.access_role in ("owner", "writer"),
                )
                for cal in calendars
            ]
        )

    except IntegrationNotConnectedError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "Google Calendar not connected",
                "code": "GOOGLE_NOT_CONNECTED",
            },
        )
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "detail": "Google token expired. Please reconnect.",
                "code": "TOKEN_EXPIRED",
            },
        )
    except GoogleCalendarError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "detail": f"Google API error: {e}",
                "code": "GOOGLE_API_ERROR",
            },
        )


@router.put(
    "/google/calendar",
    response_model=DisconnectResponse,
    summary="Set default Google calendar",
    description="Set the default calendar for the agent to use",
)
async def set_google_calendar(
    company_id: str = Query(..., description="Company ID"),
    request: SetCalendarRequest = None,
    current_user: CurrentUser = None,
    db: Database = None,
):
    """Set default Google calendar."""
    await verify_company_access(company_id, current_user, db)

    success = await GoogleCalendarService.set_default_calendar(
        company_id, request.calendar_id
    )

    return DisconnectResponse(
        success=success,
        message="Default calendar updated" if success else "Failed to update calendar",
    )


# =============================================================================
# Microsoft OAuth Endpoints
# =============================================================================


@router.get(
    "/microsoft/auth-url",
    response_model=AuthUrlResponse,
    summary="Get Microsoft OAuth URL",
    description="Generate OAuth authorization URL for Microsoft/Outlook",
)
async def get_microsoft_auth_url(
    company_id: str = Query(..., description="Company ID"),
    redirect_after: str | None = Query(None, description="URL to redirect after OAuth"),
    current_user: CurrentUser = None,
    db: Database = None,
):
    """Generate Microsoft OAuth authorization URL."""
    await verify_company_access(company_id, current_user, db)

    settings = get_settings()

    # Check if Microsoft OAuth is configured
    if not settings.microsoft_client_id or not settings.microsoft_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "detail": "Microsoft OAuth not configured",
                "code": "MICROSOFT_NOT_CONFIGURED",
            },
        )

    auth_url = MicrosoftGraphService.get_oauth_url(
        company_id=company_id,
        redirect_after=redirect_after,
    )

    return AuthUrlResponse(auth_url=auth_url, provider="microsoft")


@router.get(
    "/microsoft/callback",
    summary="Microsoft OAuth callback",
    description="Handle OAuth callback from Microsoft",
)
async def microsoft_oauth_callback(
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="State parameter"),
    error: str | None = Query(None, description="Error from Microsoft"),
    error_description: str | None = Query(None, description="Error description"),
):
    """Handle Microsoft OAuth callback."""
    settings = get_settings()

    if error:
        logger.warning(f"Microsoft OAuth error: {error} - {error_description}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard/integrations?error={error}"
        )

    try:
        result = await MicrosoftGraphService.handle_oauth_callback(code, state)

        redirect_url = result.get("redirect_after") or f"{settings.frontend_url}/dashboard/integrations"
        return RedirectResponse(
            url=f"{redirect_url}?microsoft_connected=true&email={result['email']}"
        )

    except InvalidStateError as e:
        logger.warning(f"Invalid Microsoft OAuth state: {e}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard/integrations?error=invalid_state"
        )
    except MicrosoftGraphError as e:
        logger.error(f"Microsoft OAuth error: {e}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard/integrations?error=oauth_failed"
        )


@router.post(
    "/microsoft/disconnect",
    response_model=DisconnectResponse,
    summary="Disconnect Microsoft",
    description="Disconnect Microsoft integration and revoke tokens",
)
async def disconnect_microsoft(
    company_id: str = Query(..., description="Company ID"),
    current_user: CurrentUser = None,
    db: Database = None,
):
    """Disconnect Microsoft integration."""
    await verify_company_access(company_id, current_user, db)

    success = await MicrosoftGraphService.disconnect(company_id)

    return DisconnectResponse(
        success=success,
        message="Microsoft integration disconnected" if success else "Failed to disconnect",
    )


@router.get(
    "/microsoft/calendars",
    response_model=CalendarListResponse,
    summary="List Microsoft calendars",
    description="List available Outlook calendars",
)
async def list_microsoft_calendars(
    company_id: str = Query(..., description="Company ID"),
    current_user: CurrentUser = None,
    db: Database = None,
):
    """List Outlook calendars for a company."""
    await verify_company_access(company_id, current_user, db)

    service = None
    try:
        service = MicrosoftGraphService(company_id)
        calendars = await service.get_calendars()

        return CalendarListResponse(
            calendars=[
                CalendarResponse(
                    id=cal.id,
                    name=cal.name,
                    description=None,
                    timezone=None,
                    primary=cal.is_default,
                    can_edit=cal.can_edit,
                )
                for cal in calendars
            ]
        )

    except IntegrationNotConnectedError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "Microsoft/Outlook not connected",
                "code": "MICROSOFT_NOT_CONNECTED",
            },
        )
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "detail": "Microsoft token expired. Please reconnect.",
                "code": "TOKEN_EXPIRED",
            },
        )
    except MicrosoftGraphError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "detail": f"Microsoft API error: {e}",
                "code": "MICROSOFT_API_ERROR",
            },
        )
    finally:
        if service:
            await service.close()


@router.put(
    "/microsoft/calendar",
    response_model=DisconnectResponse,
    summary="Set default Microsoft calendar",
    description="Set the default Outlook calendar for the agent to use",
)
async def set_microsoft_calendar(
    company_id: str = Query(..., description="Company ID"),
    request: SetCalendarRequest = None,
    current_user: CurrentUser = None,
    db: Database = None,
):
    """Set default Microsoft calendar."""
    await verify_company_access(company_id, current_user, db)

    success = await MicrosoftGraphService.set_default_calendar(
        company_id, request.calendar_id
    )

    return DisconnectResponse(
        success=success,
        message="Default calendar updated" if success else "Failed to update calendar",
    )


# =============================================================================
# Helper Functions for Tools
# =============================================================================


async def get_calendar_service(company_id: str):
    """
    Get the appropriate calendar service for a company.

    Checks which integration is connected and returns the service.

    Args:
        company_id: Company ID

    Returns:
        Tuple of (service, provider) or (None, None) if none connected
    """
    from app.database import get_database

    db = get_database()

    company = await db.companies.find_one(
        {"_id": ObjectId(company_id)},
        {"integrations": 1},
    )

    if not company:
        return None, None

    integrations = company.get("integrations", {})

    # Prefer Google if connected
    if integrations.get("google", {}).get("connected"):
        return GoogleCalendarService(company_id), "google"

    # Fall back to Microsoft
    if integrations.get("microsoft", {}).get("connected"):
        return MicrosoftGraphService(company_id), "microsoft"

    return None, None


async def get_email_service(company_id: str):
    """
    Get the appropriate email service for a company.

    Args:
        company_id: Company ID

    Returns:
        Tuple of (service, provider) or (None, None) if none connected
    """
    from app.database import get_database

    db = get_database()

    company = await db.companies.find_one(
        {"_id": ObjectId(company_id)},
        {"integrations": 1},
    )

    if not company:
        return None, None

    integrations = company.get("integrations", {})

    # Check Google Gmail (requires gmail scope)
    google_data = integrations.get("google", {})
    if google_data.get("connected"):
        scopes = google_data.get("scopes", [])
        if any("gmail" in s.lower() for s in scopes):
            return GoogleGmailService(company_id), "google"

    # Fall back to Microsoft (includes Mail.Send by default)
    if integrations.get("microsoft", {}).get("connected"):
        return MicrosoftGraphService(company_id), "microsoft"

    return None, None
