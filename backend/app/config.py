"""
Application configuration using Pydantic Settings.

Pydantic settings for all configuration management.
Environment variables are loaded from .env file and environment.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="VoicePlex", description="Application name")
    app_env: Literal["development", "staging", "production"] = Field(
        default="development", description="Application environment"
    )
    debug: bool = Field(default=False, description="Debug mode")
    dev_mode: bool = Field(
        default=False,
        description="Development mode - bypasses subscription limits when True"
    )
    secret_key: str = Field(
        ..., description="Secret key for JWT signing (256-bit)", min_length=32
    )
    encryption_key: str = Field(
        ..., description="Encryption key for OAuth tokens (32 bytes)", min_length=32
    )

    # URLs
    backend_url: str = Field(
        default="http://localhost:8000", description="Backend base URL"
    )
    frontend_url: str = Field(
        default="http://localhost:3000", description="Frontend base URL"
    )
    personaplex_url: str = Field(
        default="", description="PersonaPlex WebSocket URL"
    )

    # MongoDB
    mongodb_uri: str = Field(..., description="MongoDB connection URI")
    mongodb_db_name: str = Field(default="voiceplex", description="MongoDB database name")

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0", description="Redis connection URL"
    )

    # Claude API
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    claude_model: str = Field(
        default="claude-3-haiku-20240307",
        description="Primary Claude model (Haiku for low latency voice)",
    )
    claude_model_fallback: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="Fallback Claude model for complex reasoning",
    )
    claude_max_tokens: int = Field(
        default=1024, description="Max tokens for Claude response"
    )
    claude_temperature: float = Field(
        default=0.7, description="Claude temperature (0-1)"
    )
    claude_timeout_seconds: int = Field(
        default=30, description="Claude API timeout in seconds"
    )

    # Twilio
    twilio_account_sid: str = Field(default="", description="Twilio Account SID")
    twilio_auth_token: str = Field(default="", description="Twilio Auth Token")
    twilio_api_key_sid: str = Field(default="", description="Twilio API Key SID")
    twilio_api_key_secret: str = Field(default="", description="Twilio API Key Secret")

    # Google OAuth
    google_client_id: str = Field(default="", description="Google OAuth Client ID")
    google_client_secret: str = Field(default="", description="Google OAuth Client Secret")
    google_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/integrations/google/callback",
        description="Google OAuth redirect URI",
    )

    # Microsoft OAuth
    microsoft_client_id: str = Field(default="", description="Microsoft OAuth Client ID")
    microsoft_client_secret: str = Field(
        default="", description="Microsoft OAuth Client Secret"
    )
    microsoft_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/integrations/microsoft/callback",
        description="Microsoft OAuth redirect URI",
    )
    microsoft_tenant_id: str = Field(
        default="common", description="Microsoft Tenant ID"
    )

    # Stripe
    stripe_secret_key: str = Field(default="", description="Stripe Secret Key")
    stripe_publishable_key: str = Field(default="", description="Stripe Publishable Key")
    stripe_webhook_secret: str = Field(default="", description="Stripe Webhook Secret")
    stripe_price_starter: str = Field(default="", description="Stripe Starter Plan Price ID")
    stripe_price_growth: str = Field(default="", description="Stripe Growth Plan Price ID")
    stripe_price_professional: str = Field(
        default="", description="Stripe Professional Plan Price ID"
    )
    stripe_price_agency: str = Field(default="", description="Stripe Agency Plan Price ID")

    # RunPod
    runpod_api_key: str = Field(default="", description="RunPod API Key")
    runpod_endpoint_id: str = Field(default="", description="RunPod Endpoint ID")

    # JWT Settings
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    jwt_access_token_expire_minutes: int = Field(
        default=30, description="Access token expiration in minutes"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7, description="Refresh token expiration in days"
    )

    # Rate Limiting
    rate_limit_per_minute: int = Field(
        default=60, description="API rate limit per minute"
    )

    @field_validator("secret_key", "encryption_key")
    @classmethod
    def validate_key_length(cls, v: str, info) -> str:
        """Validate that keys meet minimum length requirements."""
        if len(v) < 32:
            raise ValueError(f"{info.field_name} must be at least 32 characters")
        return v

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env == "production"

    @property
    def cors_origins(self) -> list[str]:
        """Get allowed CORS origins based on environment."""
        if self.is_production:
            return [self.frontend_url]
        # In development, allow all localhost ports (3000-3010) for flexibility
        return [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:3002",
            "http://localhost:3003",
            "http://localhost:3004",
            "http://localhost:3005",
            "http://localhost:3006",
            "http://localhost:3007",
            "http://localhost:3008",
            "http://localhost:3009",
            "http://localhost:3010",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://127.0.0.1:3002",
            "http://127.0.0.1:3003",
            "http://127.0.0.1:3004",
            "http://127.0.0.1:3005",
            "http://127.0.0.1:3006",
            "http://127.0.0.1:3007",
            "http://127.0.0.1:3008",
            "http://127.0.0.1:3009",
            "http://127.0.0.1:3010",
            self.frontend_url,
        ]


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()
