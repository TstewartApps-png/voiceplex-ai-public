"""
OAuth Manager for token encryption, decryption, and state management.

OAuth tokens encrypted at rest using ENCRYPTION_KEY.
Handles token storage, refresh, and CSRF protection via state parameter.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import get_settings

logger = logging.getLogger(__name__)


class OAuthError(Exception):
    """Base exception for OAuth errors."""

    pass


class TokenEncryptionError(OAuthError):
    """Token encryption/decryption failed."""

    pass


class TokenExpiredError(OAuthError):
    """Token has expired and refresh failed."""

    pass


class InvalidStateError(OAuthError):
    """OAuth state parameter validation failed."""

    pass


class IntegrationNotConnectedError(OAuthError):
    """Integration is not connected."""

    pass


@dataclass
class OAuthTokens:
    """Container for OAuth tokens."""

    access_token: str
    refresh_token: str | None
    token_type: str
    expires_at: datetime | None
    scopes: list[str]


@dataclass
class OAuthState:
    """OAuth state for CSRF protection."""

    state: str
    company_id: str
    provider: str
    created_at: datetime
    redirect_after: str | None = None


class TokenEncryption:
    """
    Handles encryption and decryption of OAuth tokens.

    Uses Fernet symmetric encryption (AES-128-CBC with HMAC).
    Derives key from ENCRYPTION_KEY using PBKDF2.
    """

    def __init__(self, encryption_key: str | None = None):
        """
        Initialize encryption with key derivation.

        Args:
            encryption_key: Base encryption key (uses config if not provided)
        """
        settings = get_settings()
        key = encryption_key or settings.encryption_key

        # Derive a proper Fernet key using PBKDF2
        # Using a fixed salt - in production you might want per-token salts
        salt = b"voiceplex_oauth_token_encryption"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(key.encode()))
        self._fernet = Fernet(derived_key)

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a token string.

        Args:
            plaintext: Token to encrypt

        Returns:
            Base64-encoded encrypted token

        Raises:
            TokenEncryptionError: If encryption fails
        """
        try:
            encrypted = self._fernet.encrypt(plaintext.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Token encryption failed: {e}")
            raise TokenEncryptionError("Failed to encrypt token") from e

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a token string.

        Args:
            ciphertext: Base64-encoded encrypted token

        Returns:
            Decrypted token string

        Raises:
            TokenEncryptionError: If decryption fails
        """
        try:
            decoded = base64.urlsafe_b64decode(ciphertext.encode())
            decrypted = self._fernet.decrypt(decoded)
            return decrypted.decode()
        except InvalidToken:
            logger.error("Invalid token - decryption failed (wrong key or corrupted)")
            raise TokenEncryptionError("Failed to decrypt token - invalid or corrupted")
        except Exception as e:
            logger.error(f"Token decryption failed: {e}")
            raise TokenEncryptionError("Failed to decrypt token") from e


class OAuthStateManager:
    """
    Manages OAuth state parameters for CSRF protection.

    States are stored in Redis with TTL for automatic cleanup.
    Falls back to in-memory storage if Redis unavailable.
    """

    # In-memory fallback storage (for development)
    _states: dict[str, OAuthState] = {}

    # State TTL (10 minutes)
    STATE_TTL_SECONDS = 600

    @classmethod
    def generate_state(
        cls,
        company_id: str,
        provider: str,
        redirect_after: str | None = None,
    ) -> str:
        """
        Generate a new OAuth state parameter.

        Args:
            company_id: Company initiating the OAuth flow
            provider: OAuth provider (google, microsoft)
            redirect_after: URL to redirect to after OAuth completes

        Returns:
            State string to include in OAuth URL
        """
        state = secrets.token_urlsafe(32)
        oauth_state = OAuthState(
            state=state,
            company_id=company_id,
            provider=provider,
            created_at=datetime.utcnow(),
            redirect_after=redirect_after,
        )

        # Store state (in production, use Redis)
        cls._states[state] = oauth_state

        logger.info(
            f"Generated OAuth state for company {company_id}, provider {provider}"
        )
        return state

    @classmethod
    def validate_state(cls, state: str) -> OAuthState:
        """
        Validate and consume an OAuth state parameter.

        Args:
            state: State string from OAuth callback

        Returns:
            OAuthState with company and provider info

        Raises:
            InvalidStateError: If state is invalid or expired
        """
        oauth_state = cls._states.pop(state, None)

        if oauth_state is None:
            logger.warning(f"Invalid OAuth state: {state[:10]}...")
            raise InvalidStateError("Invalid or expired OAuth state")

        # Check if state is expired
        age = datetime.utcnow() - oauth_state.created_at
        if age.total_seconds() > cls.STATE_TTL_SECONDS:
            logger.warning(f"Expired OAuth state: {state[:10]}...")
            raise InvalidStateError("OAuth state has expired")

        logger.info(
            f"Validated OAuth state for company {oauth_state.company_id}, "
            f"provider {oauth_state.provider}"
        )
        return oauth_state

    @classmethod
    def cleanup_expired(cls) -> int:
        """
        Remove expired states from storage.

        Returns:
            Number of states removed
        """
        now = datetime.utcnow()
        expired = [
            state
            for state, data in cls._states.items()
            if (now - data.created_at).total_seconds() > cls.STATE_TTL_SECONDS
        ]

        for state in expired:
            del cls._states[state]

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired OAuth states")

        return len(expired)


class OAuthManager:
    """
    Central manager for OAuth operations.

    Provides unified interface for:
    - Token encryption/decryption
    - State management
    - Token expiry checking
    - Integration helpers
    """

    def __init__(self):
        """Initialize OAuth manager with encryption."""
        self._encryption = TokenEncryption()

    def encrypt_token(self, token: str) -> str:
        """
        Encrypt a token for storage.

        Args:
            token: Plain token string

        Returns:
            Encrypted token string
        """
        return self._encryption.encrypt(token)

    def decrypt_token(self, encrypted_token: str) -> str:
        """
        Decrypt a token from storage.

        Args:
            encrypted_token: Encrypted token string

        Returns:
            Plain token string
        """
        return self._encryption.decrypt(encrypted_token)

    def generate_state(
        self,
        company_id: str,
        provider: str,
        redirect_after: str | None = None,
    ) -> str:
        """
        Generate OAuth state for CSRF protection.

        Args:
            company_id: Company ID
            provider: OAuth provider name
            redirect_after: Post-OAuth redirect URL

        Returns:
            State parameter string
        """
        return OAuthStateManager.generate_state(
            company_id=company_id,
            provider=provider,
            redirect_after=redirect_after,
        )

    def validate_state(self, state: str) -> OAuthState:
        """
        Validate OAuth state parameter.

        Args:
            state: State from callback

        Returns:
            OAuthState with request info
        """
        return OAuthStateManager.validate_state(state)

    def is_token_expired(
        self,
        expires_at: datetime | None,
        buffer_seconds: int = 300,
    ) -> bool:
        """
        Check if a token is expired or about to expire.

        Args:
            expires_at: Token expiration time
            buffer_seconds: Buffer before expiry to consider expired

        Returns:
            True if token is expired or will expire within buffer
        """
        if expires_at is None:
            return False

        threshold = datetime.utcnow() + timedelta(seconds=buffer_seconds)
        return expires_at <= threshold

    def prepare_tokens_for_storage(
        self,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime | None,
        scopes: list[str],
    ) -> dict[str, Any]:
        """
        Prepare tokens for MongoDB storage with encryption.

        Args:
            access_token: OAuth access token
            refresh_token: OAuth refresh token (optional)
            expires_at: Token expiration time
            scopes: Granted scopes

        Returns:
            Dictionary ready for MongoDB update
        """
        encrypted_access = self.encrypt_token(access_token)
        encrypted_refresh = (
            self.encrypt_token(refresh_token) if refresh_token else None
        )

        return {
            "access_token_encrypted": encrypted_access,
            "refresh_token_encrypted": encrypted_refresh,
            "token_expires_at": expires_at,
            "scopes": scopes,
            "connected": True,
        }

    def extract_tokens_from_storage(
        self,
        integration_data: dict[str, Any],
    ) -> OAuthTokens | None:
        """
        Extract and decrypt tokens from MongoDB storage.

        Args:
            integration_data: Integration subdocument from company

        Returns:
            OAuthTokens if connected and valid, None otherwise
        """
        if not integration_data.get("connected"):
            return None

        encrypted_access = integration_data.get("access_token_encrypted")
        if not encrypted_access:
            return None

        try:
            access_token = self.decrypt_token(encrypted_access)

            encrypted_refresh = integration_data.get("refresh_token_encrypted")
            refresh_token = (
                self.decrypt_token(encrypted_refresh)
                if encrypted_refresh
                else None
            )

            return OAuthTokens(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="Bearer",
                expires_at=integration_data.get("token_expires_at"),
                scopes=integration_data.get("scopes", []),
            )
        except TokenEncryptionError:
            logger.error("Failed to decrypt stored tokens")
            return None


# Global instance
_oauth_manager: OAuthManager | None = None


def get_oauth_manager() -> OAuthManager:
    """Get or create global OAuth manager instance."""
    global _oauth_manager
    if _oauth_manager is None:
        _oauth_manager = OAuthManager()
    return _oauth_manager
