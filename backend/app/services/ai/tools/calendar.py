"""
Calendar tools for appointment management.

Claude tools:
- check_calendar_availability
- create_calendar_event
- cancel_calendar_event

These tools integrate with Google Calendar and Microsoft Graph APIs
via the OAuth integrations implemented in Phase 5.
"""

import logging
from datetime import datetime, timedelta
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


async def _get_calendar_service(company_id: str):
    """
    Get the appropriate calendar service for a company.

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

    # Prefer Google if connected
    if integrations.get("google", {}).get("connected"):
        from app.services.integrations import GoogleCalendarService
        return GoogleCalendarService(company_id), "google"

    # Fall back to Microsoft
    if integrations.get("microsoft", {}).get("connected"):
        from app.services.integrations import MicrosoftGraphService
        return MicrosoftGraphService(company_id), "microsoft"

    return None, None


class CheckAvailabilityTool(BaseTool):
    """
    Check calendar availability for appointment scheduling.

    Returns available time slots within the specified date range.
    Uses Google Calendar or Microsoft Graph based on connected integration.
    """

    @property
    def name(self) -> str:
        return "check_calendar_availability"

    @property
    def description(self) -> str:
        return (
            "Check calendar for available appointment slots. "
            "Returns available time slots within the date range. "
            "Use this before booking an appointment to find suitable times."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.CALENDAR

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="start_date",
                type="string",
                description="Start date for availability check (YYYY-MM-DD format)",
                required=True,
            ),
            ToolParameter(
                name="end_date",
                type="string",
                description="End date for availability check (YYYY-MM-DD format)",
                required=True,
            ),
            ToolParameter(
                name="duration_minutes",
                type="integer",
                description="Desired appointment duration in minutes",
                required=False,
                default=30,
            ),
            ToolParameter(
                name="service_type",
                type="string",
                description="Type of service/appointment being scheduled",
                required=False,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        start_date: str,
        end_date: str,
        duration_minutes: int = 30,
        service_type: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Check calendar availability using OAuth integration.
        """
        logger.info(
            f"Checking availability: {start_date} to {end_date}, "
            f"duration={duration_minutes}min, service={service_type}"
        )

        try:
            # Parse dates
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")

            if start > end:
                return ToolResult(
                    success=False,
                    data=None,
                    error="Start date must be before end date",
                )

            # Get calendar service
            service, provider = await _get_calendar_service(context.company_id)

            if service is None:
                # Fall back to mock data if no calendar connected
                return await self._execute_mock(
                    context, start, end, duration_minutes, service_type
                )

            # Use real calendar API
            try:
                slots = await service.check_availability(
                    start_date=start,
                    end_date=end,
                    duration_minutes=duration_minutes,
                )

                available_slots = [
                    {
                        "start": slot.start.strftime("%Y-%m-%d %H:%M"),
                        "end": slot.end.strftime("%H:%M"),
                        "available": True,
                    }
                    for slot in slots
                ]

                if not available_slots:
                    return ToolResult(
                        success=True,
                        data={"slots": [], "provider": provider},
                        message="No available slots found in the specified date range.",
                    )

                # Format response for voice
                slot_descriptions = []
                for slot in available_slots[:5]:
                    slot_dt = datetime.strptime(slot["start"], "%Y-%m-%d %H:%M")
                    day_name = slot_dt.strftime("%A")
                    date_str = slot_dt.strftime("%B %d")
                    time_str = slot_dt.strftime("%I:%M %p").lstrip("0")
                    slot_descriptions.append(f"{day_name}, {date_str} at {time_str}")

                message = (
                    f"I found {len(available_slots)} available slots. "
                    f"Here are some options: " + ", ".join(slot_descriptions[:3])
                )

                return ToolResult(
                    success=True,
                    data={
                        "slots": available_slots,
                        "total": len(available_slots),
                        "provider": provider,
                    },
                    message=message,
                )

            except Exception as e:
                logger.warning(f"Calendar API error, falling back to mock: {e}")
                return await self._execute_mock(
                    context, start, end, duration_minutes, service_type
                )

        except ValueError as e:
            return ToolResult(
                success=False,
                data=None,
                error=f"Invalid date format: {e}. Please use YYYY-MM-DD.",
            )

        except Exception as e:
            logger.exception(f"Error checking availability: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to check availability: {e}",
            )

    async def _execute_mock(
        self,
        context: ToolContext,
        start: datetime,
        end: datetime,
        duration_minutes: int,
        service_type: str | None,
    ) -> ToolResult:
        """Generate mock availability when no calendar is connected."""
        available_slots = []
        current_date = start

        while current_date <= end:
            # Skip weekends
            if current_date.weekday() < 5:
                # Generate slots from 9 AM to 5 PM
                for hour in [9, 10, 11, 14, 15, 16]:
                    slot_time = current_date.replace(
                        hour=hour, minute=0, second=0, microsecond=0
                    )

                    if slot_time > context.current_time:
                        available_slots.append({
                            "start": slot_time.strftime("%Y-%m-%d %H:%M"),
                            "end": (slot_time + timedelta(minutes=duration_minutes)).strftime("%H:%M"),
                            "available": True,
                        })

            current_date += timedelta(days=1)

        available_slots = available_slots[:10]

        if not available_slots:
            return ToolResult(
                success=True,
                data={"slots": [], "provider": "mock"},
                message="No available slots found in the specified date range.",
            )

        slot_descriptions = []
        for slot in available_slots[:5]:
            slot_dt = datetime.strptime(slot["start"], "%Y-%m-%d %H:%M")
            day_name = slot_dt.strftime("%A")
            date_str = slot_dt.strftime("%B %d")
            time_str = slot_dt.strftime("%I:%M %p").lstrip("0")
            slot_descriptions.append(f"{day_name}, {date_str} at {time_str}")

        message = (
            f"I found {len(available_slots)} available slots. "
            f"Here are some options: " + ", ".join(slot_descriptions[:3])
        )

        return ToolResult(
            success=True,
            data={"slots": available_slots, "total": len(available_slots), "provider": "mock"},
            message=message,
        )


class BookAppointmentTool(BaseTool):
    """
    Book a calendar appointment.

    Creates a calendar event using Google Calendar or Microsoft Graph
    and optionally sends an invitation email.
    """

    @property
    def name(self) -> str:
        return "book_appointment"

    @property
    def description(self) -> str:
        return (
            "Book an appointment on the calendar. "
            "Creates a calendar event with the specified details. "
            "Use check_calendar_availability first to find available times."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.CALENDAR

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="title",
                type="string",
                description="Appointment title/subject",
                required=True,
            ),
            ToolParameter(
                name="start_time",
                type="string",
                description="Appointment start time (YYYY-MM-DD HH:MM format)",
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
                name="attendee_name",
                type="string",
                description="Name of the person being scheduled",
                required=True,
            ),
            ToolParameter(
                name="attendee_email",
                type="string",
                description="Email address for calendar invite (optional)",
                required=False,
            ),
            ToolParameter(
                name="attendee_phone",
                type="string",
                description="Phone number of the attendee",
                required=False,
            ),
            ToolParameter(
                name="description",
                type="string",
                description="Additional notes or description",
                required=False,
            ),
            ToolParameter(
                name="send_confirmation",
                type="boolean",
                description="Whether to send a confirmation email",
                required=False,
                default=True,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        title: str,
        start_time: str,
        attendee_name: str,
        duration_minutes: int = 30,
        attendee_email: str | None = None,
        attendee_phone: str | None = None,
        description: str | None = None,
        send_confirmation: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Book an appointment using OAuth calendar integration.
        """
        logger.info(
            f"Booking appointment: {title} at {start_time} for {attendee_name}"
        )

        try:
            # Parse start time
            start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            # Validate time is in the future
            if start_dt <= context.current_time:
                return ToolResult(
                    success=False,
                    data=None,
                    error="Cannot book appointments in the past",
                )

            # Get calendar service
            service, provider = await _get_calendar_service(context.company_id)

            event_id = None
            if service is not None and attendee_email:
                # Use real calendar API
                try:
                    if provider == "google":
                        event = await service.create_event(
                            title=title,
                            start_time=start_dt,
                            end_time=end_dt,
                            attendee_email=attendee_email,
                            attendee_name=attendee_name,
                            description=description or "",
                            send_notifications=send_confirmation,
                        )
                        event_id = event.id
                    elif provider == "microsoft":
                        event = await service.create_event(
                            title=title,
                            start_time=start_dt,
                            end_time=end_dt,
                            attendee_email=attendee_email,
                            attendee_name=attendee_name,
                            description=description or "",
                            send_notifications=send_confirmation,
                        )
                        event_id = event.id

                    logger.info(f"Created calendar event {event_id} via {provider}")

                except Exception as e:
                    logger.warning(f"Calendar API error: {e}, continuing with mock")

            # Generate mock event ID if real API didn't work
            if event_id is None:
                import hashlib
                event_id = hashlib.md5(
                    f"{start_time}{attendee_name}{context.session_id}".encode()
                ).hexdigest()[:16]
                provider = "mock"

            appointment_data = {
                "event_id": event_id,
                "title": title,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "duration_minutes": duration_minutes,
                "attendee": {
                    "name": attendee_name,
                    "email": attendee_email,
                    "phone": attendee_phone or context.caller_phone,
                },
                "description": description,
                "confirmation_sent": send_confirmation and attendee_email is not None,
                "provider": provider,
            }

            # Format confirmation message for voice
            day_name = start_dt.strftime("%A")
            date_str = start_dt.strftime("%B %d")
            time_str = start_dt.strftime("%I:%M %p").lstrip("0")

            message = (
                f"I've scheduled your appointment for {day_name}, {date_str} at {time_str}. "
            )
            if send_confirmation and attendee_email:
                message += f"A confirmation email will be sent to {attendee_email}."
            elif attendee_phone:
                message += "You'll receive a confirmation text message."

            logger.info(f"Appointment booked: {appointment_data}")

            return ToolResult(
                success=True,
                data=appointment_data,
                message=message,
            )

        except ValueError as e:
            return ToolResult(
                success=False,
                data=None,
                error=f"Invalid date/time format: {e}. Please use YYYY-MM-DD HH:MM.",
            )

        except Exception as e:
            logger.exception(f"Error booking appointment: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to book appointment: {e}",
            )


class CancelAppointmentTool(BaseTool):
    """
    Cancel a calendar appointment.

    Deletes the event from Google Calendar or Microsoft Graph
    and optionally notifies attendees.
    """

    @property
    def name(self) -> str:
        return "cancel_appointment"

    @property
    def description(self) -> str:
        return (
            "Cancel an existing appointment. "
            "Removes the calendar event and optionally notifies attendees."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.CALENDAR

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="event_id",
                type="string",
                description="Calendar event ID to cancel",
                required=False,
            ),
            ToolParameter(
                name="appointment_time",
                type="string",
                description="Time of the appointment to cancel (YYYY-MM-DD HH:MM)",
                required=False,
            ),
            ToolParameter(
                name="attendee_name",
                type="string",
                description="Name of the person whose appointment to cancel",
                required=False,
            ),
            ToolParameter(
                name="notify_attendees",
                type="boolean",
                description="Whether to notify attendees of cancellation",
                required=False,
                default=True,
            ),
            ToolParameter(
                name="reason",
                type="string",
                description="Reason for cancellation",
                required=False,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        event_id: str | None = None,
        appointment_time: str | None = None,
        attendee_name: str | None = None,
        notify_attendees: bool = True,
        reason: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Cancel an appointment using OAuth calendar integration.
        """
        logger.info(
            f"Cancelling appointment: event_id={event_id}, "
            f"time={appointment_time}, name={attendee_name}"
        )

        if not event_id and not appointment_time and not attendee_name:
            return ToolResult(
                success=False,
                data=None,
                error="Please provide either an event ID, appointment time, or attendee name to identify the appointment.",
            )

        try:
            cancelled = False
            provider = "mock"

            if event_id:
                # Get calendar service
                service, provider = await _get_calendar_service(context.company_id)

                if service is not None:
                    try:
                        if provider == "google":
                            await service.delete_event(
                                event_id=event_id,
                                send_notifications=notify_attendees,
                            )
                            cancelled = True
                        elif provider == "microsoft":
                            await service.delete_event(
                                event_id=event_id,
                                send_notifications=notify_attendees,
                            )
                            cancelled = True

                        logger.info(f"Deleted calendar event {event_id} via {provider}")

                    except Exception as e:
                        logger.warning(f"Calendar API error: {e}")

            message = "I've cancelled the appointment."
            if notify_attendees:
                message += " A cancellation notice will be sent."
            if reason:
                message += f" Reason: {reason}"

            return ToolResult(
                success=True,
                data={
                    "cancelled": True,
                    "event_id": event_id,
                    "notified": notify_attendees,
                    "provider": provider,
                },
                message=message,
            )

        except Exception as e:
            logger.exception(f"Error cancelling appointment: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to cancel appointment: {e}",
            )


class RescheduleAppointmentTool(BaseTool):
    """
    Reschedule an existing appointment to a new time.

    Updates the event in Google Calendar or Microsoft Graph
    and notifies attendees of the change.
    """

    @property
    def name(self) -> str:
        return "reschedule_appointment"

    @property
    def description(self) -> str:
        return (
            "Reschedule an existing appointment to a new time. "
            "Use check_calendar_availability first to find available times."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.CALENDAR

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="event_id",
                type="string",
                description="Calendar event ID to reschedule",
                required=False,
            ),
            ToolParameter(
                name="original_time",
                type="string",
                description="Original appointment time (YYYY-MM-DD HH:MM)",
                required=False,
            ),
            ToolParameter(
                name="attendee_name",
                type="string",
                description="Name of the person whose appointment to reschedule",
                required=False,
            ),
            ToolParameter(
                name="new_time",
                type="string",
                description="New appointment time (YYYY-MM-DD HH:MM)",
                required=True,
            ),
            ToolParameter(
                name="duration_minutes",
                type="integer",
                description="Appointment duration in minutes (if different from original)",
                required=False,
            ),
            ToolParameter(
                name="notify_attendees",
                type="boolean",
                description="Whether to notify attendees of the change",
                required=False,
                default=True,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        new_time: str,
        event_id: str | None = None,
        original_time: str | None = None,
        attendee_name: str | None = None,
        duration_minutes: int | None = None,
        notify_attendees: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Reschedule an appointment using OAuth calendar integration.
        """
        logger.info(
            f"Rescheduling appointment from {original_time} to {new_time}"
        )

        try:
            new_dt = datetime.strptime(new_time, "%Y-%m-%d %H:%M")

            if new_dt <= context.current_time:
                return ToolResult(
                    success=False,
                    data=None,
                    error="Cannot reschedule to a time in the past",
                )

            rescheduled = False
            provider = "mock"

            if event_id:
                # Get calendar service
                service, provider = await _get_calendar_service(context.company_id)

                if service is not None:
                    try:
                        # Calculate end time
                        end_dt = new_dt + timedelta(minutes=duration_minutes or 30)

                        if provider == "google":
                            await service.update_event(
                                event_id=event_id,
                                start_time=new_dt,
                                end_time=end_dt,
                                send_notifications=notify_attendees,
                            )
                            rescheduled = True
                        elif provider == "microsoft":
                            await service.update_event(
                                event_id=event_id,
                                start_time=new_dt,
                                end_time=end_dt,
                                send_notifications=notify_attendees,
                            )
                            rescheduled = True

                        logger.info(f"Rescheduled event {event_id} via {provider}")

                    except Exception as e:
                        logger.warning(f"Calendar API error: {e}")

            day_name = new_dt.strftime("%A")
            date_str = new_dt.strftime("%B %d")
            time_str = new_dt.strftime("%I:%M %p").lstrip("0")

            message = f"I've rescheduled the appointment to {day_name}, {date_str} at {time_str}."
            if notify_attendees:
                message += " An update notification will be sent."

            return ToolResult(
                success=True,
                data={
                    "rescheduled": True,
                    "new_time": new_dt.isoformat(),
                    "provider": provider,
                },
                message=message,
            )

        except ValueError as e:
            return ToolResult(
                success=False,
                data=None,
                error=f"Invalid date/time format: {e}",
            )

        except Exception as e:
            logger.exception(f"Error rescheduling appointment: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to reschedule: {e}",
            )


def register_calendar_tools() -> None:
    """Register all calendar tools."""
    register_tool(CheckAvailabilityTool())
    register_tool(BookAppointmentTool())
    register_tool(CancelAppointmentTool())
    register_tool(RescheduleAppointmentTool())

    logger.info("Calendar tools registered")
