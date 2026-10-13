"""
User model definitions.

MongoDB schema for users collection.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class SubscriptionPlan(str, Enum):
    """Subscription plan tiers."""

    FREE = "free"
    STARTER = "starter"
    GROWTH = "growth"
    PROFESSIONAL = "professional"
    AGENCY = "agency"


class SubscriptionStatus(str, Enum):
    """Subscription status states."""

    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    TRIALING = "trialing"


class UserSettings(BaseModel):
    """User preferences and settings."""

    timezone: str = Field(default="America/New_York", description="User's timezone")
    notifications_email: bool = Field(
        default=True, description="Email notifications enabled"
    )
    notifications_sms: bool = Field(
        default=False, description="SMS notifications enabled"
    )


class Subscription(BaseModel):
    """User subscription information."""

    plan: SubscriptionPlan = Field(
        default=SubscriptionPlan.FREE, description="Subscription plan"
    )
    stripe_customer_id: str | None = Field(
        default=None, description="Stripe customer ID"
    )
    stripe_subscription_id: str | None = Field(
        default=None, description="Stripe subscription ID"
    )
    status: SubscriptionStatus = Field(
        default=SubscriptionStatus.ACTIVE, description="Subscription status"
    )
    trial_ends_at: datetime | None = Field(
        default=None, description="Trial period end date"
    )
    current_period_end: datetime | None = Field(
        default=None, description="Current billing period end"
    )
    minutes_included: int = Field(
        default=0, description="Monthly minutes included in plan"
    )
    minutes_used: int = Field(
        default=0, description="Minutes used this billing period"
    )


class PyObjectId(str):
    """Custom type for MongoDB ObjectId."""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v, handler):
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, str):
            if ObjectId.is_valid(v):
                return v
            raise ValueError("Invalid ObjectId")
        raise ValueError("Invalid ObjectId type")


# Base user fields
class UserBase(BaseModel):
    """Base user model with common fields."""

    email: EmailStr = Field(..., description="User email address")
    name: str = Field(..., min_length=1, max_length=100, description="User's full name")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Strip whitespace from name."""
        return v.strip()


class UserCreate(UserBase):
    """User creation request model."""

    password: str = Field(
        ..., min_length=8, max_length=128, description="User password"
    )

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserUpdate(BaseModel):
    """User update request model."""

    name: str | None = Field(
        default=None, min_length=1, max_length=100, description="User's full name"
    )
    avatar_url: str | None = Field(default=None, description="Avatar image URL")
    settings: UserSettings | None = Field(default=None, description="User settings")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Strip whitespace from name if provided."""
        return v.strip() if v else v


class UserInDB(UserBase):
    """User model as stored in database."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default=None, alias="_id")
    password_hash: str = Field(..., description="Hashed password")
    avatar_url: str | None = Field(default=None, description="Avatar image URL")
    subscription: Subscription = Field(
        default_factory=Subscription, description="Subscription details"
    )
    settings: UserSettings = Field(
        default_factory=UserSettings, description="User settings"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Account creation time"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(), description="Last update time"
    )
    last_login_at: datetime | None = Field(
        default=None, description="Last login timestamp"
    )

    @field_validator("id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v


class UserResponse(UserBase):
    """User response model (excludes sensitive fields)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., validation_alias="_id", serialization_alias="id", description="User ID")
    avatar_url: str | None = Field(default=None, description="Avatar image URL")
    subscription: Subscription = Field(..., description="Subscription details")
    settings: UserSettings = Field(..., description="User settings")
    created_at: datetime = Field(..., description="Account creation time")
    last_login_at: datetime | None = Field(
        default=None, description="Last login timestamp"
    )

    @field_validator("id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v


class User(UserBase):
    """Complete user model for internal use."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default=None, alias="_id")
    password_hash: str | None = Field(default=None, exclude=True)
    avatar_url: str | None = None
    subscription: Subscription = Field(default_factory=Subscription)
    settings: UserSettings = Field(default_factory=UserSettings)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    last_login_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def convert_object_id(cls, v):
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v
