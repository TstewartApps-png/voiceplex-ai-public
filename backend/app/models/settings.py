"""
User settings model for storing integration configurations.

Secure storage of API keys and integration credentials.
All sensitive data is encrypted at rest using ENCRYPTION_KEY.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from bson import ObjectId
from pydantic import BaseModel, Field


class IntegrationType(str, Enum):
    """Types of integrations."""

    PERSONAPLEX = "personaplex"
    TWILIO = "twilio"
    ANTHROPIC = "anthropic"


class PersonaplexSettingsInDB(BaseModel):
    """PersonaPlex settings stored in database."""

    websocket_url: str
    connected: bool = False
    last_tested_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TwilioSettingsInDB(BaseModel):
    """Twilio settings stored in database."""

    account_sid_encrypted: str  # Encrypted
    auth_token_encrypted: str  # Encrypted
    phone_number: str
    agent_id: str | None = None  # default agent for inbound calls to phone_number
    webhook_configured: bool = False
    connected: bool = False
    account_name: str | None = None
    last_tested_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AnthropicSettingsInDB(BaseModel):
    """Anthropic settings stored in database."""

    api_key_encrypted: str  # Encrypted
    connected: bool = False
    last_tested_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UserSettingsInDB(BaseModel):
    """Complete user settings document in database."""

    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    user_id: str
    personaplex: PersonaplexSettingsInDB | None = None
    twilio: TwilioSettingsInDB | None = None
    anthropic: AnthropicSettingsInDB | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


# Request/Response models

class PersonaplexSettingsRequest(BaseModel):
    """Request to save PersonaPlex settings."""

    websocket_url: str = Field(
        ...,
        description="PersonaPlex WebSocket URL",
        examples=["wss://your-endpoint.runpod.net/ws"],
    )


class PersonaplexTestRequest(BaseModel):
    """Request to test PersonaPlex connection."""

    websocket_url: str = Field(
        ...,
        description="PersonaPlex WebSocket URL to test",
    )


class PersonaplexTestResponse(BaseModel):
    """Response from PersonaPlex connection test."""

    success: bool
    latency_ms: int | None = None
    error: str | None = None


class TwilioSettingsRequest(BaseModel):
    """Request to save Twilio settings."""

    account_sid: str = Field(
        ...,
        description="Twilio Account SID",
        min_length=34,
        max_length=34,
    )
    auth_token: str = Field(
        ...,
        description="Twilio Auth Token",
        min_length=32,
        max_length=32,
    )
    phone_number: str = Field(
        ...,
        description="Twilio Phone Number (E.164 format)",
        examples=["+1234567890"],
        pattern=r"^\+[1-9]\d{6,14}$",
    )
    agent_id: str | None = Field(
        default=None,
        description="Agent that answers inbound calls to this number "
        "(optional; if omitted the tenant's single active agent is used)",
    )


class TwilioTestResponse(BaseModel):
    """Response from Twilio connection test."""

    success: bool
    account_name: str | None = None
    error: str | None = None
    webhook_configured: bool | None = None
    webhook_error: str | None = None
    inbound_voice_url: str | None = None


class AnthropicSettingsRequest(BaseModel):
    """Request to save Anthropic settings."""

    api_key: str = Field(
        ...,
        description="Anthropic API Key",
        min_length=10,
    )


class AnthropicTestResponse(BaseModel):
    """Response from Anthropic connection test."""

    success: bool
    model: str | None = None
    error: str | None = None


class IntegrationStatusResponse(BaseModel):
    """Response showing all integration statuses."""

    personaplex: dict[str, Any]
    twilio: dict[str, Any]
    anthropic: dict[str, Any]
