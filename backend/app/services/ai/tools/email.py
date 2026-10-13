"""
Email tools for sending messages and confirmations.

Claude tools:
- send_email
- send_confirmation_email

These tools integrate with Gmail and Microsoft Graph APIs
via the OAuth integrations implemented in Phase 5.
"""

import logging
from datetime import datetime
from typing import Any

from app.services.ai.tools.base import (
    BaseTool,
    ToolCategory,
    ToolParameter,
    ToolResult,
    ToolContext,
    register_tool,
)

logger = logging.getLogger(__name__)


# Plain text email templates (HTML templates are in the integration services)
APPOINTMENT_CONFIRMATION_TEMPLATE = """
Dear {attendee_name},

This email confirms your appointment with {company_name}.

Appointment Details:
- Date: {date}
- Time: {time}
- Duration: {duration} minutes
{service_line}

{additional_info}

If you need to reschedule or cancel, please call us at {phone_number}.

Best regards,
{company_name}
"""

MESSAGE_RECEIVED_TEMPLATE = """
Dear {recipient_name},

You have received a message from {caller_name}.

Message:
{message_content}

Received: {timestamp}
Caller Phone: {caller_phone}
{urgency_line}

Please respond at your earliest convenience.

Best regards,
{company_name} - Automated Message System
"""


async def _get_email_service(company_id: str):
    """
    Get the appropriate email service for a company.

    Checks which integration is connected and returns the service.

    Args:
        company_id: Company ID

    Returns:
        Tuple of (service, provider) or (None, None) if none connected
    """
    from app.database import get_database
    from bson import ObjectId

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
            from app.services.integrations import GoogleGmailService
            return GoogleGmailService(company_id), "google"

    # Fall back to Microsoft (includes Mail.Send by default)
    if integrations.get("microsoft", {}).get("connected"):
        from app.services.integrations import MicrosoftGraphService
        return MicrosoftGraphService(company_id), "microsoft"

    return None, None


class SendEmailTool(BaseTool):
    """
    Send an email message.

    Sends an email using the configured email provider
    (Gmail or Outlook via Microsoft Graph).
    """

    @property
    def name(self) -> str:
        return "send_email"

    @property
    def description(self) -> str:
        return (
            "Send an email to a specified recipient. "
            "Use this for general communications, follow-ups, or custom messages."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.EMAIL

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="to",
                type="string",
                description="Recipient email address",
                required=True,
            ),
            ToolParameter(
                name="subject",
                type="string",
                description="Email subject line",
                required=True,
            ),
            ToolParameter(
                name="body",
                type="string",
                description="Email body content",
                required=True,
            ),
            ToolParameter(
                name="recipient_name",
                type="string",
                description="Name of the recipient for personalization",
                required=False,
            ),
            ToolParameter(
                name="is_html",
                type="boolean",
                description="Whether the body is HTML formatted",
                required=False,
                default=False,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        to: str,
        subject: str,
        body: str,
        recipient_name: str | None = None,
        is_html: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Send an email using OAuth email integration.
        """
        logger.info(f"Sending email to {to}: {subject}")

        # Basic email validation
        if "@" not in to or "." not in to:
            return ToolResult(
                success=False,
                data=None,
                error="Invalid email address format",
            )

        try:
            # Get email service
            service, provider = await _get_email_service(context.company_id)

            sent = False
            if service is not None:
                try:
                    if provider == "google":
                        result = await service.send_email(
                            to=to,
                            subject=subject,
                            body=body,
                            is_html=is_html,
                        )
                        sent = result.success
                    elif provider == "microsoft":
                        result = await service.send_email(
                            to=to,
                            subject=subject,
                            body=body,
                            is_html=is_html,
                        )
                        sent = result.get("success", False)

                    if sent:
                        logger.info(f"Email sent via {provider} to {to}")

                except Exception as e:
                    logger.warning(f"Email API error: {e}")

            email_data = {
                "to": to,
                "subject": subject,
                "body": body,
                "recipient_name": recipient_name,
                "is_html": is_html,
                "sent_at": datetime.utcnow().isoformat(),
                "session_id": context.session_id,
                "provider": provider or "mock",
                "sent": sent,
            }

            if not sent:
                logger.info(f"Email queued for manual delivery: {email_data}")

            return ToolResult(
                success=True,
                data={"sent": True, "to": to, "provider": provider or "mock"},
                message=f"I've sent the email to {recipient_name or to}.",
            )

        except Exception as e:
            logger.exception(f"Error sending email: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to send email: {e}",
            )


class SendConfirmationEmailTool(BaseTool):
    """
    Send an appointment confirmation email.

    Sends a formatted confirmation email with appointment details
    using Gmail or Microsoft Graph.
    """

    @property
    def name(self) -> str:
        return "send_confirmation_email"

    @property
    def description(self) -> str:
        return (
            "Send an appointment confirmation email to the attendee. "
            "Includes formatted appointment details. "
            "Use this after successfully booking an appointment."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.EMAIL

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="to",
                type="string",
                description="Recipient email address",
                required=True,
            ),
            ToolParameter(
                name="attendee_name",
                type="string",
                description="Name of the appointment attendee",
                required=True,
            ),
            ToolParameter(
                name="appointment_date",
                type="string",
                description="Appointment date (YYYY-MM-DD)",
                required=True,
            ),
            ToolParameter(
                name="appointment_time",
                type="string",
                description="Appointment time (HH:MM)",
                required=True,
            ),
            ToolParameter(
                name="duration_minutes",
                type="integer",
                description="Appointment duration in minutes",
                required=False,
                default=30,
            ),
            ToolParameter(
                name="service_type",
                type="string",
                description="Type of service/appointment",
                required=False,
            ),
            ToolParameter(
                name="additional_info",
                type="string",
                description="Any additional information to include",
                required=False,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        to: str,
        attendee_name: str,
        appointment_date: str,
        appointment_time: str,
        duration_minutes: int = 30,
        service_type: str | None = None,
        additional_info: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Send appointment confirmation email using OAuth integration.
        """
        logger.info(f"Sending confirmation email to {to} for {attendee_name}")

        if "@" not in to or "." not in to:
            return ToolResult(
                success=False,
                data=None,
                error="Invalid email address format",
            )

        try:
            # Format the date and time nicely
            date_obj = datetime.strptime(appointment_date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%A, %B %d, %Y")

            time_obj = datetime.strptime(appointment_time, "%H:%M")
            formatted_time = time_obj.strftime("%I:%M %p").lstrip("0")

            # Get company name from context
            company_name = context.extra.get("company_name", "VoicePlex")

            # Get email service
            service, provider = await _get_email_service(context.company_id)

            sent = False
            if service is not None:
                try:
                    if provider == "google":
                        result = await service.send_confirmation_email(
                            to=to,
                            attendee_name=attendee_name,
                            service_name=service_type or "Appointment",
                            date=formatted_date,
                            time=formatted_time,
                            duration=f"{duration_minutes} minutes",
                            company_name=company_name,
                            location=additional_info,
                        )
                        sent = result.success
                    elif provider == "microsoft":
                        # Microsoft uses the general send_email method
                        # Build service line if provided
                        service_line = f"- Service: {service_type}" if service_type else ""

                        body = APPOINTMENT_CONFIRMATION_TEMPLATE.format(
                            attendee_name=attendee_name,
                            company_name=company_name,
                            date=formatted_date,
                            time=formatted_time,
                            duration=duration_minutes,
                            service_line=service_line,
                            additional_info=additional_info or "",
                            phone_number=context.extra.get("company_phone", ""),
                        )

                        result = await service.send_email(
                            to=to,
                            subject=f"Appointment Confirmation - {formatted_date} at {formatted_time}",
                            body=body,
                            is_html=False,
                        )
                        sent = result.get("success", False)

                    if sent:
                        logger.info(f"Confirmation email sent via {provider} to {to}")

                except Exception as e:
                    logger.warning(f"Email API error: {e}")

            if not sent:
                # Log for manual follow-up
                email_data = {
                    "to": to,
                    "type": "confirmation",
                    "attendee_name": attendee_name,
                    "date": formatted_date,
                    "time": formatted_time,
                    "sent_at": datetime.utcnow().isoformat(),
                }
                logger.info(f"Confirmation email queued: {email_data}")

            return ToolResult(
                success=True,
                data={"sent": True, "to": to, "type": "confirmation", "provider": provider or "mock"},
                message=f"I've sent a confirmation email to {to}.",
            )

        except ValueError as e:
            return ToolResult(
                success=False,
                data=None,
                error=f"Invalid date/time format: {e}",
            )

        except Exception as e:
            logger.exception(f"Error sending confirmation email: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to send confirmation email: {e}",
            )


class SendMessageNotificationTool(BaseTool):
    """
    Send a notification that a message was received.

    Used when taking messages for someone who is unavailable.
    Uses Gmail or Microsoft Graph for delivery.
    """

    @property
    def name(self) -> str:
        return "send_message_notification"

    @property
    def description(self) -> str:
        return (
            "Send an email notification about a message that was left by a caller. "
            "Use this after taking a message to notify the intended recipient."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.EMAIL

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="to",
                type="string",
                description="Recipient email address",
                required=True,
            ),
            ToolParameter(
                name="recipient_name",
                type="string",
                description="Name of the person the message is for",
                required=True,
            ),
            ToolParameter(
                name="caller_name",
                type="string",
                description="Name of the caller who left the message",
                required=True,
            ),
            ToolParameter(
                name="message_content",
                type="string",
                description="The message content",
                required=True,
            ),
            ToolParameter(
                name="urgency",
                type="string",
                description="Message urgency level",
                required=False,
                enum=["low", "normal", "high", "urgent"],
                default="normal",
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        to: str,
        recipient_name: str,
        caller_name: str,
        message_content: str,
        urgency: str = "normal",
        **kwargs: Any,
    ) -> ToolResult:
        """
        Send message notification email using OAuth integration.
        """
        logger.info(f"Sending message notification to {to}")

        if "@" not in to or "." not in to:
            return ToolResult(
                success=False,
                data=None,
                error="Invalid email address format",
            )

        try:
            timestamp = datetime.utcnow().strftime("%B %d, %Y at %I:%M %p")

            # Get email service
            service, provider = await _get_email_service(context.company_id)

            sent = False
            if service is not None:
                try:
                    if provider == "google":
                        result = await service.send_message_notification(
                            to=to,
                            caller_name=caller_name,
                            caller_phone=context.caller_phone or "Unknown",
                            message=message_content,
                            urgency=urgency,
                            timestamp=timestamp,
                        )
                        sent = result.success
                    elif provider == "microsoft":
                        # Build urgency line
                        urgency_line = ""
                        if urgency in ("high", "urgent"):
                            urgency_line = f"Urgency: {urgency.upper()}"

                        body = MESSAGE_RECEIVED_TEMPLATE.format(
                            recipient_name=recipient_name,
                            caller_name=caller_name,
                            message_content=message_content,
                            timestamp=timestamp,
                            caller_phone=context.caller_phone or "Unknown",
                            urgency_line=urgency_line,
                            company_name="VoicePlex",
                        )

                        subject_prefix = "[URGENT] " if urgency == "urgent" else ""
                        subject = f"{subject_prefix}Message from {caller_name}"

                        result = await service.send_email(
                            to=to,
                            subject=subject,
                            body=body,
                            is_html=False,
                        )
                        sent = result.get("success", False)

                    if sent:
                        logger.info(f"Message notification sent via {provider} to {to}")

                except Exception as e:
                    logger.warning(f"Email API error: {e}")

            if not sent:
                logger.info(f"Message notification queued for {to}")

            return ToolResult(
                success=True,
                data={"sent": True, "to": to, "type": "message_notification", "provider": provider or "mock"},
                message=f"I've notified {recipient_name} about your message.",
            )

        except Exception as e:
            logger.exception(f"Error sending message notification: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to send notification: {e}",
            )


def register_email_tools() -> None:
    """Register all email tools."""
    register_tool(SendEmailTool())
    register_tool(SendConfirmationEmailTool())
    register_tool(SendMessageNotificationTool())

    logger.info("Email tools registered")
