"""
Call control tools for managing active voice calls.

Claude tools:
- transfer_call
- end_call
- take_message

These tools control the active call via the Call Orchestrator.
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


class TransferCallTool(BaseTool):
    """
    Transfer the current call to another phone number.
    """

    @property
    def name(self) -> str:
        return "transfer_call"

    @property
    def description(self) -> str:
        return (
            "Transfer the current call to another phone number. "
            "Use this when the caller needs to speak with a human representative "
            "or when the request is beyond what you can handle. "
            "The caller will hear hold music while the transfer is being set up."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.CALL_CONTROL

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="destination",
                type="string",
                description="Phone number to transfer to (E.164 format preferred, e.g., +15551234567)",
                required=True,
            ),
            ToolParameter(
                name="announce",
                type="boolean",
                description="Whether to announce the transfer to the caller",
                required=False,
                default=True,
            ),
            ToolParameter(
                name="whisper",
                type="string",
                description="Message to whisper to the person receiving the transfer",
                required=False,
            ),
            ToolParameter(
                name="reason",
                type="string",
                description="Reason for the transfer (for logging)",
                required=False,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        destination: str,
        announce: bool = True,
        whisper: str | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Transfer the call.

        In production, this signals the Call Orchestrator to initiate
        a call transfer via Twilio.
        """
        logger.info(
            f"Transferring call {context.call_id} to {destination}, "
            f"reason={reason}"
        )

        # Validate phone number format (basic check)
        cleaned = destination.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not cleaned.replace("+", "").isdigit():
            return ToolResult(
                success=False,
                data=None,
                error="Invalid phone number format",
            )

        try:
            # Store transfer intent in context for orchestrator to handle
            transfer_data = {
                "action": "transfer",
                "destination": destination,
                "announce": announce,
                "whisper": whisper,
                "reason": reason,
                "initiated_at": datetime.utcnow().isoformat(),
                "session_id": context.session_id,
            }

            # In production, this would trigger the actual transfer
            # via the Call Orchestrator and Twilio

            message = "Transferring your call now. Please hold."
            if announce:
                message = f"I'll transfer you now. {message}"

            return ToolResult(
                success=True,
                data=transfer_data,
                message=message,
            )

        except Exception as e:
            logger.exception(f"Error initiating transfer: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to transfer call: {e}",
            )


class EndCallTool(BaseTool):
    """
    End the current call.
    """

    @property
    def name(self) -> str:
        return "end_call"

    @property
    def description(self) -> str:
        return (
            "End the current call. "
            "Use this when the conversation is complete and the caller is ready to hang up. "
            "Always be polite and thank the caller before ending."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.CALL_CONTROL

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="reason",
                type="string",
                description="Reason for ending the call",
                required=False,
                enum=["completed", "caller_request", "transfer", "timeout", "error"],
                default="completed",
            ),
            ToolParameter(
                name="farewell_message",
                type="string",
                description="Custom farewell message to speak before hanging up",
                required=False,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        reason: str = "completed",
        farewell_message: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        End the call.
        """
        logger.info(f"Ending call {context.call_id}, reason={reason}")

        try:
            end_data = {
                "action": "end_call",
                "reason": reason,
                "ended_at": datetime.utcnow().isoformat(),
                "session_id": context.session_id,
            }

            message = farewell_message or "Thank you for calling. Goodbye!"

            return ToolResult(
                success=True,
                data=end_data,
                message=message,
            )

        except Exception as e:
            logger.exception(f"Error ending call: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to end call: {e}",
            )


class TakeMessageTool(BaseTool):
    """
    Record a message from the caller.
    """

    @property
    def name(self) -> str:
        return "take_message"

    @property
    def description(self) -> str:
        return (
            "Record a message from the caller to be delivered to someone. "
            "Use this when the caller wants to leave a message for someone who is unavailable. "
            "Collect the caller's name, phone number, message content, and urgency level."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.CALL_CONTROL

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="caller_name",
                type="string",
                description="Name of the person leaving the message",
                required=True,
            ),
            ToolParameter(
                name="caller_phone",
                type="string",
                description="Phone number to call back",
                required=True,
            ),
            ToolParameter(
                name="message",
                type="string",
                description="The message content",
                required=True,
            ),
            ToolParameter(
                name="for_person",
                type="string",
                description="Name of the person the message is for",
                required=False,
            ),
            ToolParameter(
                name="urgency",
                type="string",
                description="Message urgency level",
                required=False,
                enum=["low", "normal", "high", "urgent"],
                default="normal",
            ),
            ToolParameter(
                name="callback_requested",
                type="boolean",
                description="Whether the caller requested a callback",
                required=False,
                default=True,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        caller_name: str,
        caller_phone: str,
        message: str,
        for_person: str | None = None,
        urgency: str = "normal",
        callback_requested: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Record a message.
        """
        logger.info(
            f"Taking message from {caller_name} ({caller_phone}), "
            f"urgency={urgency}"
        )

        try:
            message_data = {
                "action": "take_message",
                "caller_name": caller_name,
                "caller_phone": caller_phone or context.caller_phone,
                "message": message,
                "for_person": for_person,
                "urgency": urgency,
                "callback_requested": callback_requested,
                "taken_at": datetime.utcnow().isoformat(),
                "session_id": context.session_id,
                "call_id": context.call_id,
            }

            # In production, this would:
            # 1. Save message to database
            # 2. Send notification (email/SMS) if configured
            # 3. Update call record with message outcome

            confirmation = f"I've recorded your message"
            if for_person:
                confirmation += f" for {for_person}"
            confirmation += "."

            if callback_requested:
                confirmation += " They will call you back as soon as possible."

            if urgency in ("high", "urgent"):
                confirmation += " I've marked it as urgent."

            return ToolResult(
                success=True,
                data=message_data,
                message=confirmation,
            )

        except Exception as e:
            logger.exception(f"Error taking message: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to record message: {e}",
            )


class PutOnHoldTool(BaseTool):
    """
    Put the caller on hold with music.
    """

    @property
    def name(self) -> str:
        return "put_on_hold"

    @property
    def description(self) -> str:
        return (
            "Put the caller on hold with hold music. "
            "Use this when you need to look something up or process a request. "
            "Always tell the caller how long they might be on hold."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.CALL_CONTROL

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="reason",
                type="string",
                description="Reason for putting on hold (to tell the caller)",
                required=True,
            ),
            ToolParameter(
                name="estimated_seconds",
                type="integer",
                description="Estimated hold time in seconds",
                required=False,
                default=30,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        reason: str,
        estimated_seconds: int = 30,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Put caller on hold.
        """
        logger.info(f"Putting call {context.call_id} on hold: {reason}")

        try:
            hold_data = {
                "action": "hold",
                "reason": reason,
                "estimated_seconds": estimated_seconds,
                "started_at": datetime.utcnow().isoformat(),
                "session_id": context.session_id,
            }

            # Estimate in human-friendly terms
            if estimated_seconds < 30:
                time_estimate = "just a moment"
            elif estimated_seconds < 60:
                time_estimate = "about 30 seconds"
            elif estimated_seconds < 120:
                time_estimate = "about a minute"
            else:
                minutes = estimated_seconds // 60
                time_estimate = f"about {minutes} minutes"

            message = f"Please hold for {time_estimate} while I {reason}."

            return ToolResult(
                success=True,
                data=hold_data,
                message=message,
            )

        except Exception as e:
            logger.exception(f"Error putting on hold: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to put on hold: {e}",
            )


class CollectInformationTool(BaseTool):
    """
    Collect specific information from the caller.
    """

    @property
    def name(self) -> str:
        return "collect_information"

    @property
    def description(self) -> str:
        return (
            "Record information collected from the caller. "
            "Use this to store important details like names, phone numbers, "
            "email addresses, or other data mentioned during the conversation."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.CALL_CONTROL

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="field_name",
                type="string",
                description="Name of the information field (e.g., 'caller_name', 'email', 'company')",
                required=True,
            ),
            ToolParameter(
                name="value",
                type="string",
                description="The collected value",
                required=True,
            ),
            ToolParameter(
                name="confirmed",
                type="boolean",
                description="Whether the caller confirmed this information",
                required=False,
                default=False,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        field_name: str,
        value: str,
        confirmed: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Store collected information.
        """
        logger.info(f"Collecting info for call {context.call_id}: {field_name}={value}")

        try:
            info_data = {
                "action": "collect_info",
                "field_name": field_name,
                "value": value,
                "confirmed": confirmed,
                "collected_at": datetime.utcnow().isoformat(),
                "session_id": context.session_id,
            }

            # In production, this updates the call record and session state

            return ToolResult(
                success=True,
                data=info_data,
                message=f"Got it, I've noted your {field_name.replace('_', ' ')}.",
            )

        except Exception as e:
            logger.exception(f"Error collecting information: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to store information: {e}",
            )


def register_call_control_tools() -> None:
    """Register all call control tools."""
    register_tool(TransferCallTool())
    register_tool(EndCallTool())
    register_tool(TakeMessageTool())
    register_tool(PutOnHoldTool())
    register_tool(CollectInformationTool())

    logger.info("Call control tools registered")
