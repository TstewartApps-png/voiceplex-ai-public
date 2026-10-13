"""
Microsoft Graph API integration service.

Microsoft OAuth for Outlook calendar and email.
Uses MSAL for authentication and Microsoft Graph SDK.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import msal

from app.config import get_settings
from app.database import get_database
from app.services.integrations.oauth_manager import (
    IntegrationNotConnectedError,
    OAuthError,
    TokenExpiredError,
    get_oauth_manager,
)

logger = logging.getLogger(__name__)

# Microsoft Graph OAuth scopes
MICROSOFT_SCOPES = [
    "User.Read",
    "Calendars.ReadWrite",
    "Mail.Send",
    "offline_access",
]

# Microsoft Graph API base URL
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class MicrosoftGraphError(OAuthError):
    """Microsoft Graph API error."""

    pass


@dataclass
class MicrosoftCalendarInfo:
    """Outlook calendar information."""

    id: str
    name: str
    color: str | None
    can_edit: bool
    is_default: bool
    owner_email: str


@dataclass
class MicrosoftTimeSlot:
    """Available time slot."""

    start: datetime
    end: datetime
    duration_minutes: int


@dataclass
class MicrosoftCalendarEvent:
    """Outlook calendar event details."""

    id: str
    title: str
    description: str | None
    start: datetime
    end: datetime
    timezone: str
    attendees: list[dict[str, str]]
    location: str | None
    status: str
    web_link: str


class MicrosoftGraphService:
    """
    Microsoft Graph API service.

    Handles OAuth flow and calendar/email operations for a company.
    """

    def __init__(self, company_id: str):
        """
        Initialize service for a company.

        Args:
            company_id: Company ID for multi-tenant isolation
        """
        self.company_id = company_id
        self._oauth_manager = get_oauth_manager()
        self._access_token: str | None = None
        self._http_client: httpx.AsyncClient | None = None

    @staticmethod
    def _get_msal_app() -> msal.ConfidentialClientApplication:
        """Create MSAL confidential client application."""
        settings = get_settings()
        authority = f"https://login.microsoftonline.com/{settings.microsoft_tenant_id}"

        return msal.ConfidentialClientApplication(
            client_id=settings.microsoft_client_id,
            client_credential=settings.microsoft_client_secret,
            authority=authority,
        )

    @staticmethod
    def get_oauth_url(company_id: str, redirect_after: str | None = None) -> str:
        """
        Generate Microsoft OAuth authorization URL.

        Args:
            company_id: Company initiating OAuth
            redirect_after: URL to redirect after OAuth completes

        Returns:
            Authorization URL to redirect user to
        """
        settings = get_settings()
        oauth_manager = get_oauth_manager()

        # Generate state for CSRF protection
        state = oauth_manager.generate_state(
            company_id=company_id,
            provider="microsoft",
            redirect_after=redirect_after,
        )

        app = MicrosoftGraphService._get_msal_app()
        auth_url = app.get_authorization_request_url(
            scopes=MICROSOFT_SCOPES,
            state=state,
            redirect_uri=settings.microsoft_redirect_uri,
        )

        logger.info(f"Generated Microsoft OAuth URL for company {company_id}")
        return auth_url

    @staticmethod
    async def handle_oauth_callback(
        code: str,
        state: str,
    ) -> dict[str, Any]:
        """
        Handle OAuth callback and store tokens.

        Args:
            code: Authorization code from Microsoft
            state: State parameter for CSRF validation

        Returns:
            Dictionary with success status and user info
        """
        settings = get_settings()
        oauth_manager = get_oauth_manager()

        # Validate state
        oauth_state = oauth_manager.validate_state(state)
        company_id = oauth_state.company_id

        # Exchange code for tokens
        app = MicrosoftGraphService._get_msal_app()

        try:
            result = app.acquire_token_by_authorization_code(
                code=code,
                scopes=MICROSOFT_SCOPES,
                redirect_uri=settings.microsoft_redirect_uri,
            )
        except Exception as e:
            logger.error(f"Failed to exchange Microsoft auth code: {e}")
            raise MicrosoftGraphError(f"Failed to complete Microsoft OAuth: {e}")

        if "error" in result:
            error_desc = result.get("error_description", result.get("error"))
            logger.error(f"Microsoft OAuth error: {error_desc}")
            raise MicrosoftGraphError(f"Microsoft OAuth failed: {error_desc}")

        access_token = result.get("access_token")
        refresh_token = result.get("refresh_token")
        expires_in = result.get("expires_in", 3600)

        if not access_token:
            raise MicrosoftGraphError("No access token received from Microsoft")

        # Calculate expiry
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        # Get user profile
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GRAPH_API_BASE}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code != 200:
                logger.error(f"Failed to get Microsoft user info: {response.text}")
                email = ""
            else:
                user_info = response.json()
                email = user_info.get("mail") or user_info.get("userPrincipalName", "")

        # Prepare tokens for storage
        token_data = oauth_manager.prepare_tokens_for_storage(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scopes=MICROSOFT_SCOPES,
        )
        token_data["email"] = email

        # Store in MongoDB
        db = get_database()
        from bson import ObjectId

        await db.companies.update_one(
            {"_id": ObjectId(company_id)},
            {
                "$set": {
                    "integrations.microsoft": token_data,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(f"Stored Microsoft OAuth tokens for company {company_id}, email {email}")

        return {
            "success": True,
            "email": email,
            "redirect_after": oauth_state.redirect_after,
        }

    async def _ensure_access_token(self) -> str:
        """
        Ensure valid Microsoft access token is available.

        Returns:
            Valid access token string

        Raises:
            IntegrationNotConnectedError: If Microsoft not connected
            TokenExpiredError: If refresh fails
        """
        if self._access_token:
            return self._access_token

        # Load tokens from database
        db = get_database()
        from bson import ObjectId

        company = await db.companies.find_one(
            {"_id": ObjectId(self.company_id)},
            {"integrations.microsoft": 1},
        )

        if not company:
            raise IntegrationNotConnectedError("Company not found")

        microsoft_data = company.get("integrations", {}).get("microsoft", {})
        tokens = self._oauth_manager.extract_tokens_from_storage(microsoft_data)

        if not tokens:
            raise IntegrationNotConnectedError("Microsoft integration not connected")

        # Check if token needs refresh
        if self._oauth_manager.is_token_expired(tokens.expires_at):
            if not tokens.refresh_token:
                raise TokenExpiredError("Token expired and no refresh token available")

            # Refresh using MSAL
            try:
                app = self._get_msal_app()
                result = app.acquire_token_by_refresh_token(
                    refresh_token=tokens.refresh_token,
                    scopes=MICROSOFT_SCOPES,
                )

                if "error" in result:
                    raise TokenExpiredError(f"Token refresh failed: {result.get('error_description')}")

                new_access_token = result.get("access_token")
                new_refresh_token = result.get("refresh_token", tokens.refresh_token)
                expires_in = result.get("expires_in", 3600)
                expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

                # Store refreshed tokens
                new_token_data = self._oauth_manager.prepare_tokens_for_storage(
                    access_token=new_access_token,
                    refresh_token=new_refresh_token,
                    expires_at=expires_at,
                    scopes=MICROSOFT_SCOPES,
                )

                await db.companies.update_one(
                    {"_id": ObjectId(self.company_id)},
                    {
                        "$set": {
                            "integrations.microsoft.access_token_encrypted": new_token_data["access_token_encrypted"],
                            "integrations.microsoft.refresh_token_encrypted": new_token_data["refresh_token_encrypted"],
                            "integrations.microsoft.token_expires_at": new_token_data["token_expires_at"],
                            "updated_at": datetime.utcnow(),
                        }
                    },
                )

                self._access_token = new_access_token
                logger.info(f"Refreshed Microsoft token for company {self.company_id}")

            except Exception as e:
                logger.error(f"Failed to refresh Microsoft token: {e}")
                raise TokenExpiredError(f"Failed to refresh token: {e}")
        else:
            self._access_token = tokens.access_token

        return self._access_token

    async def _get_client(self) -> httpx.AsyncClient:
        """Get HTTP client with authorization header."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=GRAPH_API_BASE,
                timeout=30.0,
            )
        return self._http_client

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """
        Make authenticated request to Microsoft Graph.

        Args:
            method: HTTP method
            endpoint: API endpoint (relative to base URL)
            json: Request body
            params: Query parameters

        Returns:
            Response JSON
        """
        token = await self._ensure_access_token()
        client = await self._get_client()

        headers = {"Authorization": f"Bearer {token}"}

        response = await client.request(
            method=method,
            url=endpoint,
            headers=headers,
            json=json,
            params=params,
        )

        if response.status_code >= 400:
            logger.error(f"Microsoft Graph API error: {response.status_code} - {response.text}")
            raise MicrosoftGraphError(f"API request failed: {response.status_code}")

        if response.status_code == 204:  # No content
            return {}

        return response.json()

    async def get_calendars(self) -> list[MicrosoftCalendarInfo]:
        """
        List user's Outlook calendars.

        Returns:
            List of calendar information
        """
        result = await self._make_request("GET", "/me/calendars")
        calendars = []

        for item in result.get("value", []):
            calendars.append(
                MicrosoftCalendarInfo(
                    id=item["id"],
                    name=item.get("name", ""),
                    color=item.get("color"),
                    can_edit=item.get("canEdit", False),
                    is_default=item.get("isDefaultCalendar", False),
                    owner_email=item.get("owner", {}).get("address", ""),
                )
            )

        return calendars

    async def check_availability(
        self,
        start_date: datetime,
        end_date: datetime,
        duration_minutes: int = 30,
        calendar_id: str | None = None,
    ) -> list[MicrosoftTimeSlot]:
        """
        Find available time slots in a date range.

        Args:
            start_date: Start of range
            end_date: End of range
            duration_minutes: Required slot duration
            calendar_id: Calendar to check (default: primary)

        Returns:
            List of available time slots
        """
        # Use schedules API for availability
        body = {
            "schedules": ["me"],
            "startTime": {
                "dateTime": start_date.isoformat(),
                "timeZone": "UTC",
            },
            "endTime": {
                "dateTime": end_date.isoformat(),
                "timeZone": "UTC",
            },
            "availabilityViewInterval": duration_minutes,
        }

        result = await self._make_request(
            "POST",
            "/me/calendar/getSchedule",
            json=body,
        )

        available_slots = []
        schedules = result.get("value", [])

        if not schedules:
            return available_slots

        schedule_info = schedules[0].get("scheduleItems", [])
        availability_view = schedules[0].get("availabilityView", "")

        # Parse availability view (0 = free, 1 = tentative, 2 = busy, 3 = oof, 4 = working elsewhere)
        current = start_date
        slot_duration = timedelta(minutes=duration_minutes)

        for char in availability_view:
            if char == "0":  # Free
                available_slots.append(
                    MicrosoftTimeSlot(
                        start=current,
                        end=current + slot_duration,
                        duration_minutes=duration_minutes,
                    )
                )
            current += slot_duration

            if len(available_slots) >= 20:
                break

        return available_slots

    async def create_event(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendee_email: str,
        attendee_name: str = "",
        description: str = "",
        location: str = "",
        calendar_id: str | None = None,
        send_notifications: bool = True,
    ) -> MicrosoftCalendarEvent:
        """
        Create an Outlook calendar event.

        Args:
            title: Event title
            start_time: Event start time
            end_time: Event end time
            attendee_email: Attendee email address
            attendee_name: Attendee display name
            description: Event description
            location: Event location
            calendar_id: Target calendar ID (None = default)
            send_notifications: Send email invites

        Returns:
            Created event details
        """
        event_body = {
            "subject": title,
            "body": {
                "contentType": "text",
                "content": description,
            },
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "UTC",
            },
            "attendees": [
                {
                    "emailAddress": {
                        "address": attendee_email,
                        "name": attendee_name,
                    },
                    "type": "required",
                }
            ],
            "isOnlineMeeting": False,
        }

        if location:
            event_body["location"] = {"displayName": location}

        endpoint = "/me/events"
        if calendar_id:
            endpoint = f"/me/calendars/{calendar_id}/events"

        # Add preference header for notifications
        result = await self._make_request("POST", endpoint, json=event_body)

        logger.info(f"Created Outlook event {result['id']} for company {self.company_id}")

        return MicrosoftCalendarEvent(
            id=result["id"],
            title=result.get("subject", ""),
            description=result.get("body", {}).get("content"),
            start=datetime.fromisoformat(result["start"]["dateTime"]),
            end=datetime.fromisoformat(result["end"]["dateTime"]),
            timezone=result["start"].get("timeZone", "UTC"),
            attendees=[
                {
                    "email": a.get("emailAddress", {}).get("address", ""),
                    "name": a.get("emailAddress", {}).get("name", ""),
                }
                for a in result.get("attendees", [])
            ],
            location=result.get("location", {}).get("displayName"),
            status=result.get("showAs", "busy"),
            web_link=result.get("webLink", ""),
        )

    async def get_event(
        self,
        event_id: str,
        calendar_id: str | None = None,
    ) -> MicrosoftCalendarEvent:
        """
        Get event details.

        Args:
            event_id: Event ID
            calendar_id: Calendar ID (None = default)

        Returns:
            Event details
        """
        endpoint = f"/me/events/{event_id}"
        if calendar_id:
            endpoint = f"/me/calendars/{calendar_id}/events/{event_id}"

        result = await self._make_request("GET", endpoint)

        return MicrosoftCalendarEvent(
            id=result["id"],
            title=result.get("subject", ""),
            description=result.get("body", {}).get("content"),
            start=datetime.fromisoformat(result["start"]["dateTime"]),
            end=datetime.fromisoformat(result["end"]["dateTime"]),
            timezone=result["start"].get("timeZone", "UTC"),
            attendees=[
                {
                    "email": a.get("emailAddress", {}).get("address", ""),
                    "name": a.get("emailAddress", {}).get("name", ""),
                }
                for a in result.get("attendees", [])
            ],
            location=result.get("location", {}).get("displayName"),
            status=result.get("showAs", "busy"),
            web_link=result.get("webLink", ""),
        )

    async def update_event(
        self,
        event_id: str,
        title: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        calendar_id: str | None = None,
        send_notifications: bool = True,
    ) -> MicrosoftCalendarEvent:
        """
        Update an existing event.

        Args:
            event_id: Event ID to update
            title: New title (optional)
            start_time: New start time (optional)
            end_time: New end time (optional)
            description: New description (optional)
            location: New location (optional)
            calendar_id: Calendar ID
            send_notifications: Notify attendees of changes

        Returns:
            Updated event details
        """
        update_body = {}

        if title is not None:
            update_body["subject"] = title
        if description is not None:
            update_body["body"] = {"contentType": "text", "content": description}
        if location is not None:
            update_body["location"] = {"displayName": location}
        if start_time is not None:
            update_body["start"] = {"dateTime": start_time.isoformat(), "timeZone": "UTC"}
        if end_time is not None:
            update_body["end"] = {"dateTime": end_time.isoformat(), "timeZone": "UTC"}

        endpoint = f"/me/events/{event_id}"
        if calendar_id:
            endpoint = f"/me/calendars/{calendar_id}/events/{event_id}"

        result = await self._make_request("PATCH", endpoint, json=update_body)

        logger.info(f"Updated Outlook event {event_id}")

        return MicrosoftCalendarEvent(
            id=result["id"],
            title=result.get("subject", ""),
            description=result.get("body", {}).get("content"),
            start=datetime.fromisoformat(result["start"]["dateTime"]),
            end=datetime.fromisoformat(result["end"]["dateTime"]),
            timezone=result["start"].get("timeZone", "UTC"),
            attendees=[
                {
                    "email": a.get("emailAddress", {}).get("address", ""),
                    "name": a.get("emailAddress", {}).get("name", ""),
                }
                for a in result.get("attendees", [])
            ],
            location=result.get("location", {}).get("displayName"),
            status=result.get("showAs", "busy"),
            web_link=result.get("webLink", ""),
        )

    async def delete_event(
        self,
        event_id: str,
        calendar_id: str | None = None,
        send_notifications: bool = True,
    ) -> bool:
        """
        Delete (cancel) an Outlook event.

        Args:
            event_id: Event ID to delete
            calendar_id: Calendar ID
            send_notifications: Notify attendees of cancellation

        Returns:
            True if deleted successfully
        """
        endpoint = f"/me/events/{event_id}"
        if calendar_id:
            endpoint = f"/me/calendars/{calendar_id}/events/{event_id}"

        await self._make_request("DELETE", endpoint)

        logger.info(f"Deleted Outlook event {event_id}")
        return True

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        is_html: bool = False,
    ) -> dict[str, Any]:
        """
        Send an email via Outlook.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body
            is_html: Whether body is HTML

        Returns:
            Success status
        """
        message_body = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML" if is_html else "Text",
                    "content": body,
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to,
                        }
                    }
                ],
            },
            "saveToSentItems": True,
        }

        await self._make_request("POST", "/me/sendMail", json=message_body)

        logger.info(f"Sent email to {to} via Outlook, company {self.company_id}")

        return {"success": True}

    @staticmethod
    async def disconnect(company_id: str) -> bool:
        """
        Disconnect Microsoft integration for a company.

        Args:
            company_id: Company ID

        Returns:
            True if disconnected successfully
        """
        db = get_database()
        from bson import ObjectId

        result = await db.companies.update_one(
            {"_id": ObjectId(company_id)},
            {
                "$set": {
                    "integrations.microsoft": {
                        "connected": False,
                        "email": None,
                        "access_token_encrypted": None,
                        "refresh_token_encrypted": None,
                        "token_expires_at": None,
                        "calendar_id": None,
                    },
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(f"Disconnected Microsoft integration for company {company_id}")
        return result.modified_count > 0

    @staticmethod
    async def set_default_calendar(company_id: str, calendar_id: str) -> bool:
        """
        Set the default calendar for a company.

        Args:
            company_id: Company ID
            calendar_id: Calendar ID to set as default

        Returns:
            True if updated successfully
        """
        db = get_database()
        from bson import ObjectId

        result = await db.companies.update_one(
            {"_id": ObjectId(company_id)},
            {
                "$set": {
                    "integrations.microsoft.calendar_id": calendar_id,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(f"Set default Microsoft calendar {calendar_id} for company {company_id}")
        return result.modified_count > 0

    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


async def check_microsoft_connected(company_id: str) -> bool:
    """
    Check if Microsoft integration is connected.

    Args:
        company_id: Company ID to check

    Returns:
        True if Microsoft is connected
    """
    db = get_database()
    from bson import ObjectId

    company = await db.companies.find_one(
        {"_id": ObjectId(company_id)},
        {"integrations.microsoft": 1},
    )

    if not company:
        return False

    microsoft_data = company.get("integrations", {}).get("microsoft", {})
    return microsoft_data.get("connected", False)
