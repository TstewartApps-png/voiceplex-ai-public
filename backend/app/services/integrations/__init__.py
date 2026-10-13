"""
OAuth integrations for Google and Microsoft.

OAuth integrations for calendar and email access.
"""

from app.services.integrations.oauth_manager import (
    OAuthManager,
    OAuthError,
    TokenEncryptionError,
    TokenExpiredError,
    InvalidStateError,
    IntegrationNotConnectedError,
    OAuthTokens,
    OAuthState,
    get_oauth_manager,
)
from app.services.integrations.google_calendar import (
    GoogleCalendarService,
    GoogleCalendarError,
    CalendarInfo,
    TimeSlot,
    CalendarEvent,
    GOOGLE_CALENDAR_SCOPES,
)
from app.services.integrations.google_gmail import (
    GoogleGmailService,
    GmailError,
    EmailResult,
    check_gmail_connected,
    GOOGLE_GMAIL_SCOPES,
    GOOGLE_COMBINED_SCOPES,
)
from app.services.integrations.microsoft_graph import (
    MicrosoftGraphService,
    MicrosoftGraphError,
    MicrosoftCalendarInfo,
    MicrosoftTimeSlot,
    MicrosoftCalendarEvent,
    check_microsoft_connected,
    MICROSOFT_SCOPES,
)

__all__ = [
    # OAuth Manager
    "OAuthManager",
    "OAuthError",
    "TokenEncryptionError",
    "TokenExpiredError",
    "InvalidStateError",
    "IntegrationNotConnectedError",
    "OAuthTokens",
    "OAuthState",
    "get_oauth_manager",
    # Google Calendar
    "GoogleCalendarService",
    "GoogleCalendarError",
    "CalendarInfo",
    "TimeSlot",
    "CalendarEvent",
    "GOOGLE_CALENDAR_SCOPES",
    # Google Gmail
    "GoogleGmailService",
    "GmailError",
    "EmailResult",
    "check_gmail_connected",
    "GOOGLE_GMAIL_SCOPES",
    "GOOGLE_COMBINED_SCOPES",
    # Microsoft Graph
    "MicrosoftGraphService",
    "MicrosoftGraphError",
    "MicrosoftCalendarInfo",
    "MicrosoftTimeSlot",
    "MicrosoftCalendarEvent",
    "check_microsoft_connected",
    "MICROSOFT_SCOPES",
]
