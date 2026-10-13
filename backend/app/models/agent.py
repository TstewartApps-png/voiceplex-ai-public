"""
Agent model definitions.

MongoDB schema for agents collection.
Agents handle: receptionist, scheduler, reminder, qualifier use cases.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentType(str, Enum):
    """Agent type/use case options."""

    RECEPTIONIST = "receptionist"
    SCHEDULER = "scheduler"
    REMINDER = "reminder"
    QUALIFIER = "qualifier"


class AgentStatus(str, Enum):
    """Agent operational status."""

    ACTIVE = "active"
    PAUSED = "paused"
    DRAFT = "draft"


class Voice(BaseModel):
    """Voice configuration for the agent."""

    voice_id: str = Field(default="NATF0", description="PersonaPlex voice ID")
    name: str = Field(default="Default", description="Voice name")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed")
    pitch: float = Field(default=1.0, ge=0.5, le=2.0, description="Voice pitch")
    stability: float = Field(default=0.5, ge=0.0, le=1.0, description="Voice stability")
    style: float = Field(default=0.5, ge=0.0, le=1.0, description="Style exaggeration")


class Persona(BaseModel):
    """Agent persona/personality configuration."""

    display_name: str = Field(default="AI Assistant", description="Agent display name")
    role: str = Field(default="Virtual Assistant", description="Agent role/title")
    personality: list[str] = Field(
        default_factory=lambda: ["professional", "friendly", "helpful"],
        description="Personality traits",
    )
    greeting: str = Field(
        default="Hello! How may I assist you today?",
        description="Default greeting message",
    )
    system_prompt: str = Field(
        default="You are a helpful AI assistant.",
        description="System prompt for Claude",
    )
    voice_prompt_audio: str | None = Field(
        default=None, description="Base64 encoded voice prompt audio"
    )


class Capabilities(BaseModel):
    """Agent capability flags."""

    answer_calls: bool = Field(default=True, description="Can answer inbound calls")
    make_calls: bool = Field(default=False, description="Can make outbound calls")
    schedule_appointments: bool = Field(
        default=False, description="Can schedule appointments"
    )
    send_confirmations: bool = Field(
        default=False, description="Can send confirmation emails"
    )
    take_messages: bool = Field(default=True, description="Can take messages")
    transfer_calls: bool = Field(default=False, description="Can transfer calls")
    qualify_leads: bool = Field(default=False, description="Can qualify leads")


class Service(BaseModel):
    """Service offered for scheduling."""

    name: str = Field(..., description="Service name")
    duration_minutes: int = Field(
        default=30, ge=5, le=480, description="Service duration"
    )
    description: str = Field(default="", description="Service description")


class CalendarSettings(BaseModel):
    """Calendar/scheduling configuration."""

    enabled: bool = Field(default=False, description="Calendar integration enabled")
    calendar_id: str | None = Field(
        default=None, description="Connected calendar ID"
    )
    slot_duration_minutes: int = Field(
        default=30, ge=5, le=480, description="Default appointment duration"
    )
    buffer_minutes: int = Field(
        default=15, ge=0, le=120, description="Buffer between appointments"
    )
    max_advance_days: int = Field(
        default=30, ge=1, le=365, description="Max days ahead to book"
    )
    services: list[Service] = Field(
        default_factory=list, description="Services available for booking"
    )


class TransferRule(BaseModel):
    """Call transfer rule configuration."""

    condition: str = Field(..., description="Condition for transfer (e.g., 'urgent')")
    destination: str = Field(..., description="Transfer destination phone number")
    announce: bool = Field(
        default=True, description="Announce transfer to caller"
    )


class TransferSettings(BaseModel):
    """Call transfer configuration."""

    enabled: bool = Field(default=False, description="Call transfer enabled")
    default_number: str | None = Field(
        default=None, description="Default transfer number"
    )
    rules: list[TransferRule] = Field(
        default_factory=list, description="Transfer rules"
    )


class ConversationSettings(BaseModel):
    """Conversation behavior configuration."""

    max_duration_seconds: int = Field(default=300, ge=30, le=3600, description="Max call duration in seconds")
    interruption_handling: str = Field(default="barge_in", description="How to handle caller interruptions: barge_in, wait, or ignore")
    end_phrase: str = Field(default="Thank you for calling. Have a great day!", description="Phrase spoken before ending the call")
    silence_timeout_seconds: int = Field(default=10, ge=3, le=60, description="Seconds of silence before ending call")
    language: str = Field(default="en", description="Primary language")


class KnowledgeItemType(str, Enum):
    """Knowledge base item types."""

    FAQ = "faq"
    DOCUMENT = "document"
    WEBSITE = "website"


class KnowledgeItem(BaseModel):
    """Knowledge base item for agent context."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default=None, validation_alias="_id", serialization_alias="id")
    type: KnowledgeItemType = Field(..., description="Item type")
    title: str = Field(..., description="Item title")
    content: str = Field(..., description="Item content")
    source_url: str | None = Field(default=None, description="Source URL if applicable")
    embedding: list[float] | None = Field(
        default=None, description="Vector embedding for search"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Creation timestamp"
    )

    @field_validator("id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v


class AgentAnalytics(BaseModel):
    """Agent performance analytics."""

    total_calls: int = Field(default=0, description="Total calls handled")
    total_minutes: float = Field(default=0.0, description="Total call minutes")
    avg_duration_seconds: float = Field(
        default=0.0, description="Average call duration"
    )
    appointments_booked: int = Field(default=0, description="Appointments scheduled")
    messages_taken: int = Field(default=0, description="Messages recorded")
    transfers_made: int = Field(default=0, description="Calls transferred")
    satisfaction_avg: float | None = Field(
        default=None, description="Average satisfaction score"
    )


class AgentBase(BaseModel):
    """Base agent model with common fields."""

    name: str = Field(..., min_length=1, max_length=100, description="Agent name")
    type: AgentType = Field(
        default=AgentType.RECEPTIONIST, description="Agent type"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Strip whitespace from name."""
        return v.strip()


class AgentCreate(AgentBase):
    """Agent creation request model."""

    company_id: str = Field(..., description="Company this agent belongs to")
    voice: Voice | None = Field(default=None, description="Voice configuration")
    persona: Persona | None = Field(default=None, description="Persona configuration")
    capabilities: Capabilities | None = Field(
        default=None, description="Capability flags"
    )
    calendar_settings: CalendarSettings | None = Field(
        default=None, description="Calendar settings"
    )
    transfer_settings: TransferSettings | None = Field(
        default=None, description="Transfer settings"
    )
    conversation_settings: ConversationSettings | None = Field(
        default=None, description="Conversation settings"
    )


class AgentUpdate(BaseModel):
    """Agent update request model."""

    name: str | None = Field(
        default=None, min_length=1, max_length=100, description="Agent name"
    )
    type: AgentType | None = Field(default=None, description="Agent type")
    status: AgentStatus | None = Field(default=None, description="Agent status")
    voice: Voice | None = Field(default=None, description="Voice configuration")
    persona: Persona | None = Field(default=None, description="Persona configuration")
    capabilities: Capabilities | None = Field(
        default=None, description="Capability flags"
    )
    calendar_settings: CalendarSettings | None = Field(
        default=None, description="Calendar settings"
    )
    transfer_settings: TransferSettings | None = Field(
        default=None, description="Transfer settings"
    )
    conversation_settings: ConversationSettings | None = Field(
        default=None, description="Conversation settings"
    )


class Agent(AgentBase):
    """Complete agent model."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default=None, alias="_id")
    company_id: str = Field(..., description="Company ID")
    user_id: str = Field(..., description="Owner user ID")
    status: AgentStatus = Field(default=AgentStatus.DRAFT, description="Agent status")
    voice: Voice = Field(default_factory=Voice, description="Voice configuration")
    persona: Persona = Field(
        default_factory=Persona, description="Persona configuration"
    )
    capabilities: Capabilities = Field(
        default_factory=Capabilities, description="Capability flags"
    )
    calendar_settings: CalendarSettings = Field(
        default_factory=CalendarSettings, description="Calendar settings"
    )
    transfer_settings: TransferSettings = Field(
        default_factory=TransferSettings, description="Transfer settings"
    )
    conversation_settings: ConversationSettings = Field(
        default_factory=ConversationSettings, description="Conversation settings"
    )
    knowledge_base: list[KnowledgeItem] = Field(
        default_factory=list, description="Knowledge base items"
    )
    analytics: AgentAnalytics = Field(
        default_factory=AgentAnalytics, description="Performance analytics"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Last update timestamp"
    )

    @field_validator("id", "company_id", "user_id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v


class AgentResponse(AgentBase):
    """Agent response model for API."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., validation_alias="_id", serialization_alias="id", description="Agent ID")
    company_id: str = Field(..., description="Company ID")
    user_id: str = Field(..., description="Owner user ID")
    status: AgentStatus = Field(..., description="Agent status")
    voice: Voice = Field(..., description="Voice configuration")
    persona: Persona = Field(..., description="Persona configuration")
    capabilities: Capabilities = Field(..., description="Capability flags")
    calendar_settings: CalendarSettings = Field(..., description="Calendar settings")
    transfer_settings: TransferSettings = Field(..., description="Transfer settings")
    conversation_settings: ConversationSettings = Field(..., description="Conversation settings")
    knowledge_base: list[KnowledgeItem] = Field(..., description="Knowledge base items")
    analytics: AgentAnalytics = Field(..., description="Performance analytics")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    @field_validator("id", "company_id", "user_id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v
