"""
Google Calendar integration service.

Google Calendar OAuth with calendar.events scope.
Provides calendar availability checking and event management.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings
from app.database import get_database
from app.services.integrations.oauth_manager import (
    IntegrationNotConnectedError,
    OAuthError,
    OAuthManager,
    OAuthTokens,
    TokenExpiredError,
    get_oauth_manager,
)

logger = logging.getLogger(__name__)

# Google Calendar OAuth scopes
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


class GoogleCalendarError(OAuthError):
    """Google Calendar API error."""

    pass


@dataclass
class CalendarInfo:
    """Calendar information."""

    id: str
    name: str
    description: str | None
    timezone: str
    primary: bool
    access_role: str


@dataclass
class TimeSlot:
    """Available time slot."""

    start: datetime
    end: datetime
    duration_minutes: int


@dataclass
class CalendarEvent:
    """Calendar event details."""

    id: str
    title: str
    description: str | None
    start: datetime
    end: datetime
    timezone: str
    attendees: list[dict[str, str]]
    location: str | None
    status: str
    html_link: str


class GoogleCalendarService:
    """
    Google Calendar API service.

    Handles OAuth flow and calendar operations for a specific company.
    """

    def __init__(self, company_id: str):
        """
        Initialize service for a company.

        Args:
            company_id: Company ID for multi-tenant isolation
        """
        self.company_id = company_id
        self._oauth_manager = get_oauth_manager()
        self._credentials: Credentials | None = None
        self._service = None

    @staticmethod
    def get_oauth_url(company_id: str, redirect_after: str | None = None) -> str:
        """
        Generate Google OAuth authorization URL.

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
            provider="google",
            redirect_after=redirect_after,
        )

        # Build OAuth URL
        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.google_redirect_uri],
                }
            },
            scopes=GOOGLE_CALENDAR_SCOPES,
        )
        flow.redirect_uri = settings.google_redirect_uri

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )

        logger.info(f"Generated Google OAuth URL for company {company_id}")
        return auth_url

    @staticmethod
    async def handle_oauth_callback(
        code: str,
        state: str,
    ) -> dict[str, Any]:
        """
        Handle OAuth callback and store tokens.

        Args:
            code: Authorization code from Google
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
        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.google_redirect_uri],
                }
            },
            scopes=GOOGLE_CALENDAR_SCOPES,
        )
        flow.redirect_uri = settings.google_redirect_uri

        try:
            flow.fetch_token(code=code)
        except Exception as e:
            logger.error(f"Failed to exchange Google auth code: {e}")
            raise GoogleCalendarError(f"Failed to complete Google OAuth: {e}")

        credentials = flow.credentials

        # Calculate token expiry
        expires_at = None
        if credentials.expiry:
            expires_at = credentials.expiry

        # Get user email
        user_info_service = build("oauth2", "v2", credentials=credentials)
        user_info = user_info_service.userinfo().get().execute()
        email = user_info.get("email", "")

        # Prepare tokens for storage
        token_data = oauth_manager.prepare_tokens_for_storage(
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            expires_at=expires_at,
            scopes=list(credentials.scopes) if credentials.scopes else GOOGLE_CALENDAR_SCOPES,
        )
        token_data["email"] = email

        # Store in MongoDB
        db = get_database()
        from bson import ObjectId

        await db.companies.update_one(
            {"_id": ObjectId(company_id)},
            {
                "$set": {
                    "integrations.google": token_data,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(f"Stored Google OAuth tokens for company {company_id}, email {email}")

        return {
            "success": True,
            "email": email,
            "redirect_after": oauth_state.redirect_after,
        }

    async def _ensure_credentials(self) -> Credentials:
        """
        Ensure valid Google credentials are available.

        Returns:
            Valid Google Credentials object

        Raises:
            IntegrationNotConnectedError: If Google not connected
            TokenExpiredError: If refresh fails
        """
        if self._credentials and self._credentials.valid:
            return self._credentials

        # Load tokens from database
        db = get_database()
        from bson import ObjectId

        company = await db.companies.find_one(
            {"_id": ObjectId(self.company_id)},
            {"integrations.google": 1},
        )

        if not company:
            raise IntegrationNotConnectedError("Company not found")

        google_data = company.get("integrations", {}).get("google", {})
        tokens = self._oauth_manager.extract_tokens_from_storage(google_data)

        if not tokens:
            raise IntegrationNotConnectedError("Google Calendar not connected")

        # Check if token needs refresh
        settings = get_settings()
        if self._oauth_manager.is_token_expired(tokens.expires_at):
            if not tokens.refresh_token:
                raise TokenExpiredError("Token expired and no refresh token available")

            # Refresh the token
            try:
                self._credentials = Credentials(
                    token=tokens.access_token,
                    refresh_token=tokens.refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    scopes=tokens.scopes,
                )
                self._credentials.refresh(None)

                # Store refreshed tokens
                new_token_data = self._oauth_manager.prepare_tokens_for_storage(
                    access_token=self._credentials.token,
                    refresh_token=self._credentials.refresh_token or tokens.refresh_token,
                    expires_at=self._credentials.expiry,
                    scopes=list(self._credentials.scopes) if self._credentials.scopes else tokens.scopes,
                )

                await db.companies.update_one(
                    {"_id": ObjectId(self.company_id)},
                    {
                        "$set": {
                            "integrations.google.access_token_encrypted": new_token_data["access_token_encrypted"],
                            "integrations.google.token_expires_at": new_token_data["token_expires_at"],
                            "updated_at": datetime.utcnow(),
                        }
                    },
                )

                logger.info(f"Refreshed Google token for company {self.company_id}")
            except Exception as e:
                logger.error(f"Failed to refresh Google token: {e}")
                raise TokenExpiredError(f"Failed to refresh token: {e}")
        else:
            self._credentials = Credentials(
                token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                scopes=tokens.scopes,
            )

        return self._credentials

    def _get_service(self):
        """Get or create Google Calendar API service."""
        if self._service is None:
            self._service = build("calendar", "v3", credentials=self._credentials)
        return self._service

    async def get_calendars(self) -> list[CalendarInfo]:
        """
        List user's calendars.

        Returns:
            List of calendar information
        """
        await self._ensure_credentials()
        service = self._get_service()

        try:
            calendar_list = service.calendarList().list().execute()
            calendars = []

            for item in calendar_list.get("items", []):
                calendars.append(
                    CalendarInfo(
                        id=item["id"],
                        name=item.get("summary", ""),
                        description=item.get("description"),
                        timezone=item.get("timeZone", "UTC"),
                        primary=item.get("primary", False),
                        access_role=item.get("accessRole", "reader"),
                    )
                )

            return calendars

        except HttpError as e:
            logger.error(f"Failed to list calendars: {e}")
            raise GoogleCalendarError(f"Failed to list calendars: {e}")

    async def check_availability(
        self,
        start_date: datetime,
        end_date: datetime,
        duration_minutes: int = 30,
        calendar_id: str = "primary",
    ) -> list[TimeSlot]:
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
        await self._ensure_credentials()
        service = self._get_service()

        try:
            # Get busy times
            body = {
                "timeMin": start_date.isoformat() + "Z",
                "timeMax": end_date.isoformat() + "Z",
                "items": [{"id": calendar_id}],
            }
            freebusy = service.freebusy().query(body=body).execute()
            busy_times = freebusy.get("calendars", {}).get(calendar_id, {}).get("busy", [])

            # Convert busy times to datetime objects
            busy_slots = []
            for busy in busy_times:
                busy_start = datetime.fromisoformat(busy["start"].replace("Z", "+00:00"))
                busy_end = datetime.fromisoformat(busy["end"].replace("Z", "+00:00"))
                busy_slots.append((busy_start, busy_end))

            # Sort busy slots
            busy_slots.sort(key=lambda x: x[0])

            # Find free slots (simplified - assumes business hours 9 AM - 5 PM)
            available_slots = []
            current = start_date

            while current + timedelta(minutes=duration_minutes) <= end_date:
                # Check if current slot overlaps with any busy time
                slot_end = current + timedelta(minutes=duration_minutes)
                is_free = True

                for busy_start, busy_end in busy_slots:
                    if current < busy_end and slot_end > busy_start:
                        is_free = False
                        # Jump to end of this busy period
                        current = busy_end
                        break

                if is_free:
                    available_slots.append(
                        TimeSlot(
                            start=current,
                            end=slot_end,
                            duration_minutes=duration_minutes,
                        )
                    )
                    current = slot_end

                    # Limit results
                    if len(available_slots) >= 20:
                        break

            return available_slots

        except HttpError as e:
            logger.error(f"Failed to check availability: {e}")
            raise GoogleCalendarError(f"Failed to check availability: {e}")

    async def create_event(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendee_email: str,
        attendee_name: str = "",
        description: str = "",
        location: str = "",
        calendar_id: str = "primary",
        send_notifications: bool = True,
    ) -> CalendarEvent:
        """
        Create a calendar event.

        Args:
            title: Event title
            start_time: Event start time
            end_time: Event end time
            attendee_email: Attendee email address
            attendee_name: Attendee display name
            description: Event description
            location: Event location
            calendar_id: Target calendar ID
            send_notifications: Send email invites

        Returns:
            Created event details
        """
        await self._ensure_credentials()
        service = self._get_service()

        event_body = {
            "summary": title,
            "description": description,
            "location": location,
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
                    "email": attendee_email,
                    "displayName": attendee_name,
                }
            ],
            "reminders": {
                "useDefault": True,
            },
        }

        try:
            event = (
                service.events()
                .insert(
                    calendarId=calendar_id,
                    body=event_body,
                    sendUpdates="all" if send_notifications else "none",
                )
                .execute()
            )

            logger.info(f"Created calendar event {event['id']} for company {self.company_id}")

            return CalendarEvent(
                id=event["id"],
                title=event.get("summary", ""),
                description=event.get("description"),
                start=datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00")),
                end=datetime.fromisoformat(event["end"]["dateTime"].replace("Z", "+00:00")),
                timezone=event["start"].get("timeZone", "UTC"),
                attendees=[
                    {"email": a.get("email", ""), "name": a.get("displayName", "")}
                    for a in event.get("attendees", [])
                ],
                location=event.get("location"),
                status=event.get("status", "confirmed"),
                html_link=event.get("htmlLink", ""),
            )

        except HttpError as e:
            logger.error(f"Failed to create event: {e}")
            raise GoogleCalendarError(f"Failed to create event: {e}")

    async def get_event(self, event_id: str, calendar_id: str = "primary") -> CalendarEvent:
        """
        Get event details.

        Args:
            event_id: Event ID
            calendar_id: Calendar ID

        Returns:
            Event details
        """
        await self._ensure_credentials()
        service = self._get_service()

        try:
            event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

            return CalendarEvent(
                id=event["id"],
                title=event.get("summary", ""),
                description=event.get("description"),
                start=datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00")),
                end=datetime.fromisoformat(event["end"]["dateTime"].replace("Z", "+00:00")),
                timezone=event["start"].get("timeZone", "UTC"),
                attendees=[
                    {"email": a.get("email", ""), "name": a.get("displayName", "")}
                    for a in event.get("attendees", [])
                ],
                location=event.get("location"),
                status=event.get("status", "confirmed"),
                html_link=event.get("htmlLink", ""),
            )

        except HttpError as e:
            logger.error(f"Failed to get event {event_id}: {e}")
            raise GoogleCalendarError(f"Failed to get event: {e}")

    async def update_event(
        self,
        event_id: str,
        title: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        calendar_id: str = "primary",
        send_notifications: bool = True,
    ) -> CalendarEvent:
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
        await self._ensure_credentials()
        service = self._get_service()

        try:
            # Get existing event
            event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

            # Update fields
            if title is not None:
                event["summary"] = title
            if description is not None:
                event["description"] = description
            if location is not None:
                event["location"] = location
            if start_time is not None:
                event["start"]["dateTime"] = start_time.isoformat()
            if end_time is not None:
                event["end"]["dateTime"] = end_time.isoformat()

            updated = (
                service.events()
                .update(
                    calendarId=calendar_id,
                    eventId=event_id,
                    body=event,
                    sendUpdates="all" if send_notifications else "none",
                )
                .execute()
            )

            logger.info(f"Updated calendar event {event_id}")

            return CalendarEvent(
                id=updated["id"],
                title=updated.get("summary", ""),
                description=updated.get("description"),
                start=datetime.fromisoformat(updated["start"]["dateTime"].replace("Z", "+00:00")),
                end=datetime.fromisoformat(updated["end"]["dateTime"].replace("Z", "+00:00")),
                timezone=updated["start"].get("timeZone", "UTC"),
                attendees=[
                    {"email": a.get("email", ""), "name": a.get("displayName", "")}
                    for a in updated.get("attendees", [])
                ],
                location=updated.get("location"),
                status=updated.get("status", "confirmed"),
                html_link=updated.get("htmlLink", ""),
            )

        except HttpError as e:
            logger.error(f"Failed to update event {event_id}: {e}")
            raise GoogleCalendarError(f"Failed to update event: {e}")

    async def delete_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        send_notifications: bool = True,
    ) -> bool:
        """
        Delete (cancel) a calendar event.

        Args:
            event_id: Event ID to delete
            calendar_id: Calendar ID
            send_notifications: Notify attendees of cancellation

        Returns:
            True if deleted successfully
        """
        await self._ensure_credentials()
        service = self._get_service()

        try:
            service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
                sendUpdates="all" if send_notifications else "none",
            ).execute()

            logger.info(f"Deleted calendar event {event_id}")
            return True

        except HttpError as e:
            logger.error(f"Failed to delete event {event_id}: {e}")
            raise GoogleCalendarError(f"Failed to delete event: {e}")

    @staticmethod
    async def disconnect(company_id: str) -> bool:
        """
        Disconnect Google integration for a company.

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
                    "integrations.google": {
                        "connected": False,
                        "email": None,
                        "access_token_encrypted": None,
                        "refresh_token_encrypted": None,
                        "token_expires_at": None,
                        "calendar_id": None,
                        "scopes": [],
                    },
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(f"Disconnected Google integration for company {company_id}")
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
                    "integrations.google.calendar_id": calendar_id,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(f"Set default Google calendar {calendar_id} for company {company_id}")
        return result.modified_count > 0
