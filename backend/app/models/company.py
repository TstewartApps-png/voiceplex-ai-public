"""
Company model definitions.

MongoDB schema for companies collection.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator, HttpUrl


class PhoneNumberType(str, Enum):
    """Phone number type options."""

    LOCAL = "local"
    TOLL_FREE = "toll_free"


class PhoneNumberStatus(str, Enum):
    """Phone number status options."""

    ACTIVE = "active"
    RELEASED = "released"


class PhoneNumber(BaseModel):
    """Phone number associated with a company."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default=None, validation_alias="_id", serialization_alias="id")
    number: str = Field(..., description="Phone number in E.164 format")
    twilio_sid: str = Field(..., description="Twilio phone number SID")
    friendly_name: str = Field(default="", description="Human-readable name")
    agent_id: str | None = Field(default=None, description="Assigned agent ID")
    type: PhoneNumberType = Field(
        default=PhoneNumberType.LOCAL, description="Phone number type"
    )
    status: PhoneNumberStatus = Field(
        default=PhoneNumberStatus.ACTIVE, description="Phone number status"
    )

    @field_validator("id", "agent_id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v


class PhoneNumberCreate(BaseModel):
    """Request model for adding a phone number."""

    number: str = Field(..., description="Phone number to add")
    friendly_name: str = Field(default="", description="Human-readable name")
    agent_id: str | None = Field(default=None, description="Agent to assign")


class GoogleIntegration(BaseModel):
    """Google OAuth integration settings."""

    connected: bool = Field(default=False, description="Integration connected")
    email: str | None = Field(default=None, description="Connected Google account")
    access_token_encrypted: str | None = Field(
        default=None, description="Encrypted access token"
    )
    refresh_token_encrypted: str | None = Field(
        default=None, description="Encrypted refresh token"
    )
    token_expires_at: datetime | None = Field(
        default=None, description="Token expiration time"
    )
    calendar_id: str | None = Field(default=None, description="Selected calendar ID")
    scopes: list[str] = Field(default_factory=list, description="Granted OAuth scopes")


class MicrosoftIntegration(BaseModel):
    """Microsoft OAuth integration settings."""

    connected: bool = Field(default=False, description="Integration connected")
    email: str | None = Field(default=None, description="Connected Microsoft account")
    access_token_encrypted: str | None = Field(
        default=None, description="Encrypted access token"
    )
    refresh_token_encrypted: str | None = Field(
        default=None, description="Encrypted refresh token"
    )
    token_expires_at: datetime | None = Field(
        default=None, description="Token expiration time"
    )
    calendar_id: str | None = Field(default=None, description="Selected calendar ID")


class Integration(BaseModel):
    """Company integrations container."""

    google: GoogleIntegration = Field(
        default_factory=GoogleIntegration, description="Google integration"
    )
    microsoft: MicrosoftIntegration = Field(
        default_factory=MicrosoftIntegration, description="Microsoft integration"
    )


class Branding(BaseModel):
    """Company branding settings."""

    logo_url: str | None = Field(default=None, description="Company logo URL")
    primary_color: str = Field(default="#3B82F6", description="Primary brand color")
    company_greeting: str = Field(
        default="Thank you for calling", description="Default greeting"
    )


class DaySchedule(BaseModel):
    """Schedule for a single day."""

    day: int = Field(..., ge=0, le=6, description="Day of week (0=Sunday)")
    enabled: bool = Field(default=True, description="Business open this day")
    open: str = Field(default="09:00", description="Opening time (HH:MM)")
    close: str = Field(default="17:00", description="Closing time (HH:MM)")


class BusinessHours(BaseModel):
    """Company business hours configuration."""

    timezone: str = Field(default="America/New_York", description="Business timezone")
    schedule: list[DaySchedule] = Field(
        default_factory=lambda: [
            DaySchedule(day=0, enabled=False),  # Sunday
            DaySchedule(day=1, enabled=True),   # Monday
            DaySchedule(day=2, enabled=True),   # Tuesday
            DaySchedule(day=3, enabled=True),   # Wednesday
            DaySchedule(day=4, enabled=True),   # Thursday
            DaySchedule(day=5, enabled=True),   # Friday
            DaySchedule(day=6, enabled=False),  # Saturday
        ],
        description="Weekly schedule",
    )
    holidays: list[datetime] = Field(
        default_factory=list, description="Holiday dates (closed)"
    )


class CompanyBase(BaseModel):
    """Base company model with common fields."""

    name: str = Field(..., min_length=1, max_length=200, description="Company name")
    industry: str | None = Field(default=None, description="Industry category")
    website: str | None = Field(default=None, description="Company website")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Strip whitespace from name."""
        return v.strip()


class CompanyCreate(CompanyBase):
    """Company creation request model."""

    pass


class CompanyUpdate(BaseModel):
    """Company update request model."""

    name: str | None = Field(
        default=None, min_length=1, max_length=200, description="Company name"
    )
    industry: str | None = Field(default=None, description="Industry category")
    website: str | None = Field(default=None, description="Company website")
    branding: Branding | None = Field(default=None, description="Branding settings")
    business_hours: BusinessHours | None = Field(
        default=None, description="Business hours"
    )


class Company(CompanyBase):
    """Complete company model."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default=None, validation_alias="_id", serialization_alias="id")
    user_id: str = Field(..., description="Owner user ID")
    phone_numbers: list[PhoneNumber] = Field(
        default_factory=list, description="Assigned phone numbers"
    )
    integrations: Integration = Field(
        default_factory=Integration, description="OAuth integrations"
    )
    branding: Branding = Field(
        default_factory=Branding, description="Branding settings"
    )
    business_hours: BusinessHours = Field(
        default_factory=BusinessHours, description="Business hours"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Last update timestamp"
    )

    @field_validator("id", "user_id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v


class CompanyResponse(CompanyBase):
    """Company response model for API."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., validation_alias="_id", serialization_alias="id", description="Company ID")
    user_id: str = Field(..., description="Owner user ID")
    phone_numbers: list[PhoneNumber] = Field(..., description="Assigned phone numbers")
    integrations: Integration = Field(..., description="OAuth integrations")
    branding: Branding = Field(..., description="Branding settings")
    business_hours: BusinessHours = Field(..., description="Business hours")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    @field_validator("id", "user_id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v
