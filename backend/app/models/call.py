"""
Call model definitions.

MongoDB schema for calls collection.
Tracks all call data including transcripts, actions, and outcomes.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CallDirection(str, Enum):
    """Call direction options."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(str, Enum):
    """Call status states."""

    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    FAILED = "failed"


class CallOutcome(str, Enum):
    """Call outcome categories."""

    APPOINTMENT_SCHEDULED = "appointment_scheduled"
    MESSAGE_TAKEN = "message_taken"
    TRANSFERRED = "transferred"
    INFORMATION_PROVIDED = "information_provided"
    LEAD_QUALIFIED = "lead_qualified"
    CALLBACK_REQUESTED = "callback_requested"
    DROPPED = "dropped"
    VOICEMAIL = "voicemail"


class MessageUrgency(str, Enum):
    """Message urgency levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Caller(BaseModel):
    """Caller information collected during call."""

    name: str | None = Field(default=None, description="Caller's name")
    phone: str = Field(..., description="Caller's phone number")
    email: str | None = Field(default=None, description="Caller's email")
    company: str | None = Field(default=None, description="Caller's company")


class TranscriptEntry(BaseModel):
    """Single transcript entry in conversation."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default=None, alias="_id")
    speaker: str = Field(..., description="Speaker (agent or caller)")
    text: str = Field(..., description="Spoken text")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Entry timestamp"
    )
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="STT confidence score"
    )
    sentiment: float | None = Field(
        default=None, ge=-1.0, le=1.0, description="Sentiment score"
    )

    @field_validator("id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v


class SentimentAnalysis(BaseModel):
    """Call sentiment analysis results."""

    overall_score: float = Field(
        default=0.0, ge=-1.0, le=1.0, description="Overall sentiment (-1 to 1)"
    )
    trend: list[float] = Field(
        default_factory=list, description="Sentiment over time"
    )
    keywords: list[str] = Field(
        default_factory=list, description="Key topics/words"
    )
    escalation_needed: bool = Field(
        default=False, description="Flag for escalation"
    )


class CallAction(BaseModel):
    """Action taken during call."""

    type: str = Field(..., description="Action type (tool call)")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Action timestamp"
    )
    details: dict[str, Any] = Field(
        default_factory=dict, description="Action details/parameters"
    )
    success: bool = Field(default=True, description="Action succeeded")
    error: str | None = Field(default=None, description="Error message if failed")


class Appointment(BaseModel):
    """Appointment created during call."""

    calendar_event_id: str | None = Field(
        default=None, description="Calendar event ID"
    )
    title: str = Field(..., description="Appointment title")
    start_time: datetime = Field(..., description="Appointment start time")
    end_time: datetime = Field(..., description="Appointment end time")
    attendee_email: str | None = Field(
        default=None, description="Attendee email address"
    )


class Message(BaseModel):
    """Message taken during call."""

    content: str = Field(..., description="Message content")
    urgency: MessageUrgency = Field(
        default=MessageUrgency.NORMAL, description="Message urgency"
    )
    delivered: bool = Field(default=False, description="Message delivered")
    delivered_at: datetime | None = Field(
        default=None, description="Delivery timestamp"
    )


class Lead(BaseModel):
    """Lead information captured during call."""

    score: int = Field(default=0, ge=0, le=100, description="Lead score (0-100)")
    qualified: bool = Field(default=False, description="Lead qualified")
    fields: dict[str, Any] = Field(
        default_factory=dict, description="Custom lead fields"
    )
    notes: str | None = Field(default=None, description="Lead notes")


class CallBase(BaseModel):
    """Base call model with common fields."""

    direction: CallDirection = Field(..., description="Call direction")
    from_number: str = Field(..., description="Caller's phone number")
    to_number: str = Field(..., description="Called phone number")


class CallCreate(CallBase):
    """Call creation request model (for outbound calls)."""

    agent_id: str = Field(..., description="Agent handling the call")


class Call(CallBase):
    """Complete call model."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default=None, alias="_id")
    agent_id: str = Field(..., description="Agent ID")
    company_id: str = Field(..., description="Company ID")
    user_id: str = Field(..., description="Owner user ID")

    twilio_call_sid: str | None = Field(
        default=None, description="Twilio Call SID"
    )
    twilio_recording_sid: str | None = Field(
        default=None, description="Twilio Recording SID"
    )

    status: CallStatus = Field(
        default=CallStatus.QUEUED, description="Call status"
    )

    initiated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Call initiation time"
    )
    answered_at: datetime | None = Field(
        default=None, description="Call answer time"
    )
    ended_at: datetime | None = Field(
        default=None, description="Call end time"
    )
    duration_seconds: int = Field(default=0, description="Call duration in seconds")

    caller: Caller | None = Field(
        default=None, description="Caller information"
    )
    transcript: list[TranscriptEntry] = Field(
        default_factory=list, description="Call transcript"
    )
    summary: str | None = Field(default=None, description="Call summary")
    outcome: CallOutcome | None = Field(default=None, description="Call outcome")

    sentiment_analysis: SentimentAnalysis = Field(
        default_factory=SentimentAnalysis, description="Sentiment analysis"
    )
    actions: list[CallAction] = Field(
        default_factory=list, description="Actions taken during call"
    )

    appointment: Appointment | None = Field(
        default=None, description="Scheduled appointment"
    )
    message: Message | None = Field(
        default=None, description="Message taken"
    )
    lead: Lead | None = Field(default=None, description="Lead information")

    recording_url: str | None = Field(
        default=None, description="Recording URL"
    )
    recording_duration: int | None = Field(
        default=None, description="Recording duration"
    )
    billable_minutes: float = Field(
        default=0.0, description="Billable minutes"
    )
    cost_cents: int = Field(default=0, description="Call cost in cents")

    tags: list[str] = Field(default_factory=list, description="Call tags")
    internal_notes: str | None = Field(
        default=None, description="Internal notes"
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Record creation time"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Last update time"
    )

    @field_validator("id", "agent_id", "company_id", "user_id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v


class CallResponse(CallBase):
    """Call response model for API."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., alias="_id", description="Call ID")
    agent_id: str = Field(..., description="Agent ID")
    company_id: str = Field(..., description="Company ID")
    status: CallStatus = Field(..., description="Call status")

    twilio_call_sid: str | None = Field(
        default=None, description="Twilio Call SID"
    )

    initiated_at: datetime = Field(..., description="Call initiation time")
    answered_at: datetime | None = Field(
        default=None, description="Call answer time"
    )
    ended_at: datetime | None = Field(default=None, description="Call end time")
    duration_seconds: int = Field(..., description="Call duration in seconds")

    caller: Caller | None = Field(
        default=None, description="Caller information"
    )
    summary: str | None = Field(default=None, description="Call summary")
    outcome: CallOutcome | None = Field(default=None, description="Call outcome")

    sentiment_analysis: SentimentAnalysis = Field(
        ..., description="Sentiment analysis"
    )

    appointment: Appointment | None = Field(
        default=None, description="Scheduled appointment"
    )
    message: Message | None = Field(default=None, description="Message taken")
    lead: Lead | None = Field(default=None, description="Lead information")

    recording_url: str | None = Field(
        default=None, description="Recording URL"
    )
    billable_minutes: float = Field(..., description="Billable minutes")

    tags: list[str] = Field(..., description="Call tags")
    internal_notes: str | None = Field(
        default=None, description="Internal notes"
    )

    created_at: datetime = Field(..., description="Record creation time")

    @field_validator("id", "agent_id", "company_id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v
