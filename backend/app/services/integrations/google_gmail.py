"""
Google Gmail integration service.

Gmail integration for sending emails via OAuth.
Uses gmail.send and gmail.compose scopes.
"""

import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings
from app.database import get_database
from app.services.integrations.oauth_manager import (
    IntegrationNotConnectedError,
    OAuthError,
    TokenExpiredError,
    get_oauth_manager,
)

logger = logging.getLogger(__name__)

# Gmail OAuth scopes
GOOGLE_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

# Combined scopes for calendar + gmail
GOOGLE_COMBINED_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


class GmailError(OAuthError):
    """Gmail API error."""

    pass


@dataclass
class EmailResult:
    """Result of sending an email."""

    success: bool
    message_id: str | None
    thread_id: str | None
    error: str | None = None


# Email templates
APPOINTMENT_CONFIRMATION_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #3B82F6; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background-color: #f9f9f9; }}
        .details {{ background-color: white; padding: 15px; border-radius: 5px; margin: 15px 0; }}
        .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Appointment Confirmed</h1>
        </div>
        <div class="content">
            <p>Hello {attendee_name},</p>
            <p>Your appointment has been scheduled. Here are the details:</p>
            <div class="details">
                <p><strong>Service:</strong> {service_name}</p>
                <p><strong>Date:</strong> {date}</p>
                <p><strong>Time:</strong> {time}</p>
                <p><strong>Duration:</strong> {duration}</p>
                {location_line}
            </div>
            <p>If you need to reschedule or cancel, please contact us.</p>
            <p>Thank you for choosing {company_name}!</p>
        </div>
        <div class="footer">
            <p>{company_name}</p>
        </div>
    </div>
</body>
</html>
"""

MESSAGE_RECEIVED_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #3B82F6; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background-color: #f9f9f9; }}
        .message-box {{ background-color: white; padding: 15px; border-left: 4px solid #3B82F6; margin: 15px 0; }}
        .urgency-{urgency} {{ border-left-color: {urgency_color}; }}
        .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>New Message Received</h1>
        </div>
        <div class="content">
            <p>A new message was received via your AI receptionist:</p>
            <div class="message-box urgency-{urgency}">
                <p><strong>From:</strong> {caller_name}</p>
                <p><strong>Phone:</strong> {caller_phone}</p>
                <p><strong>Time:</strong> {timestamp}</p>
                <p><strong>Urgency:</strong> {urgency}</p>
                <hr>
                <p><strong>Message:</strong></p>
                <p>{message}</p>
            </div>
            <p>Please follow up as needed.</p>
        </div>
        <div class="footer">
            <p>Sent by VoicePlex AI</p>
        </div>
    </div>
</body>
</html>
"""


class GoogleGmailService:
    """
    Google Gmail API service.

    Handles email sending for a specific company.
    Shares OAuth tokens with Google Calendar integration.
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

    async def _ensure_credentials(self) -> Credentials:
        """
        Ensure valid Gmail credentials are available.

        Uses same tokens as Google Calendar (shared OAuth).

        Returns:
            Valid Google Credentials object

        Raises:
            IntegrationNotConnectedError: If Google not connected
            TokenExpiredError: If refresh fails
        """
        if self._credentials and self._credentials.valid:
            return self._credentials

        # Load tokens from database (shared with calendar)
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
            raise IntegrationNotConnectedError("Google integration not connected")

        # Check if Gmail scope is granted
        has_gmail_scope = any(
            "gmail" in scope.lower() for scope in tokens.scopes
        )
        if not has_gmail_scope:
            raise IntegrationNotConnectedError(
                "Gmail permission not granted. Please reconnect with Gmail access."
            )

        settings = get_settings()

        # Check if token needs refresh
        if self._oauth_manager.is_token_expired(tokens.expires_at):
            if not tokens.refresh_token:
                raise TokenExpiredError("Token expired and no refresh token available")

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

                logger.info(f"Refreshed Google token for Gmail, company {self.company_id}")
            except Exception as e:
                logger.error(f"Failed to refresh token for Gmail: {e}")
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
        """Get or create Gmail API service."""
        if self._service is None:
            self._service = build("gmail", "v1", credentials=self._credentials)
        return self._service

    def _create_message(
        self,
        to: str,
        subject: str,
        body: str,
        is_html: bool = False,
        from_name: str | None = None,
    ) -> dict[str, str]:
        """
        Create an email message.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body content
            is_html: Whether body is HTML
            from_name: Sender display name (optional)

        Returns:
            Message dict for Gmail API
        """
        message = MIMEMultipart("alternative")
        message["to"] = to
        message["subject"] = subject

        if is_html:
            # Create both plain text and HTML versions
            text_part = MIMEText(
                body.replace("<br>", "\n").replace("</p>", "\n\n"),
                "plain",
            )
            html_part = MIMEText(body, "html")
            message.attach(text_part)
            message.attach(html_part)
        else:
            text_part = MIMEText(body, "plain")
            message.attach(text_part)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return {"raw": raw_message}

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        is_html: bool = False,
    ) -> EmailResult:
        """
        Send an email.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text or HTML)
            is_html: Whether body is HTML

        Returns:
            EmailResult with success status and message ID
        """
        await self._ensure_credentials()
        service = self._get_service()

        try:
            message = self._create_message(to, subject, body, is_html)
            result = service.users().messages().send(userId="me", body=message).execute()

            logger.info(
                f"Sent email to {to}, message_id: {result['id']}, company: {self.company_id}"
            )

            return EmailResult(
                success=True,
                message_id=result.get("id"),
                thread_id=result.get("threadId"),
            )

        except HttpError as e:
            logger.error(f"Failed to send email: {e}")
            return EmailResult(
                success=False,
                message_id=None,
                thread_id=None,
                error=str(e),
            )

    async def send_confirmation_email(
        self,
        to: str,
        attendee_name: str,
        service_name: str,
        date: str,
        time: str,
        duration: str,
        company_name: str,
        location: str | None = None,
    ) -> EmailResult:
        """
        Send an appointment confirmation email.

        Args:
            to: Recipient email
            attendee_name: Name of the attendee
            service_name: Service being booked
            date: Formatted date string
            time: Formatted time string
            duration: Duration string (e.g., "30 minutes")
            company_name: Business name
            location: Optional location

        Returns:
            EmailResult
        """
        location_line = f"<p><strong>Location:</strong> {location}</p>" if location else ""

        html_body = APPOINTMENT_CONFIRMATION_TEMPLATE.format(
            attendee_name=attendee_name,
            service_name=service_name,
            date=date,
            time=time,
            duration=duration,
            company_name=company_name,
            location_line=location_line,
        )

        return await self.send_email(
            to=to,
            subject=f"Appointment Confirmed - {service_name} on {date}",
            body=html_body,
            is_html=True,
        )

    async def send_message_notification(
        self,
        to: str,
        caller_name: str,
        caller_phone: str,
        message: str,
        urgency: str = "normal",
        timestamp: str | None = None,
    ) -> EmailResult:
        """
        Send a notification about a received message.

        Args:
            to: Recipient email (business owner)
            caller_name: Name of the caller
            caller_phone: Caller's phone number
            message: Message content
            urgency: Message urgency (low, normal, high, urgent)
            timestamp: When the message was received

        Returns:
            EmailResult
        """
        urgency_colors = {
            "low": "#9CA3AF",
            "normal": "#3B82F6",
            "high": "#F59E0B",
            "urgent": "#EF4444",
        }

        if timestamp is None:
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        html_body = MESSAGE_RECEIVED_TEMPLATE.format(
            caller_name=caller_name,
            caller_phone=caller_phone,
            message=message,
            urgency=urgency,
            urgency_color=urgency_colors.get(urgency, "#3B82F6"),
            timestamp=timestamp,
        )

        subject_prefix = ""
        if urgency == "urgent":
            subject_prefix = "[URGENT] "
        elif urgency == "high":
            subject_prefix = "[High Priority] "

        return await self.send_email(
            to=to,
            subject=f"{subject_prefix}New Message from {caller_name}",
            body=html_body,
            is_html=True,
        )

    async def send_with_template(
        self,
        to: str,
        template: str,
        data: dict[str, Any],
        subject: str,
    ) -> EmailResult:
        """
        Send an email using a custom template.

        Args:
            to: Recipient email
            template: HTML template string with {placeholders}
            data: Dictionary of values to substitute
            subject: Email subject

        Returns:
            EmailResult
        """
        try:
            html_body = template.format(**data)
        except KeyError as e:
            logger.error(f"Template missing key: {e}")
            return EmailResult(
                success=False,
                message_id=None,
                thread_id=None,
                error=f"Template missing required field: {e}",
            )

        return await self.send_email(
            to=to,
            subject=subject,
            body=html_body,
            is_html=True,
        )


async def check_gmail_connected(company_id: str) -> bool:
    """
    Check if Gmail is connected and has proper scopes.

    Args:
        company_id: Company ID to check

    Returns:
        True if Gmail is connected with send permissions
    """
    db = get_database()
    from bson import ObjectId

    company = await db.companies.find_one(
        {"_id": ObjectId(company_id)},
        {"integrations.google": 1},
    )

    if not company:
        return False

    google_data = company.get("integrations", {}).get("google", {})
    if not google_data.get("connected"):
        return False

    scopes = google_data.get("scopes", [])
    return any("gmail" in scope.lower() for scope in scopes)
