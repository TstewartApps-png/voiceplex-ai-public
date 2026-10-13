"""
Security utilities for authentication and encryption.

- JWT + OAuth 2.0 for authentication
- OAuth tokens encrypted at rest with ENCRYPTION_KEY
- Secrets in environment variables, never in code
"""

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from app.config import get_settings


# Token type constants
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# Bcrypt work factor (rounds)
BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password to hash

    Returns:
        Hashed password string
    """
    # Bcrypt has a 72-byte limit - truncate if needed
    password_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against

    Returns:
        True if password matches, False otherwise
    """
    try:
        # Bcrypt has a 72-byte limit - truncate to match hash_password
        password_bytes = plain_password.encode("utf-8")[:72]
        return bcrypt.checkpw(
            password_bytes,
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def create_access_token(
    subject: str,
    additional_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        subject: Token subject (typically user ID)
        additional_claims: Extra claims to include in token
        expires_delta: Custom expiration time

    Returns:
        Encoded JWT access token
    """
    settings = get_settings()

    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)

    expire = datetime.now(timezone.utc) + expires_delta

    to_encode = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": TOKEN_TYPE_ACCESS,
        "jti": str(uuid.uuid4()),
    }

    if additional_claims:
        to_encode.update(additional_claims)

    return jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(
    subject: str,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a JWT refresh token.

    Args:
        subject: Token subject (typically user ID)
        expires_delta: Custom expiration time

    Returns:
        Encoded JWT refresh token
    """
    settings = get_settings()

    if expires_delta is None:
        expires_delta = timedelta(days=settings.jwt_refresh_token_expire_days)

    expire = datetime.now(timezone.utc) + expires_delta

    to_encode = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": TOKEN_TYPE_REFRESH,
        "jti": str(uuid.uuid4()),
    }

    return jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token.

    Args:
        token: JWT token to decode

    Returns:
        Decoded token payload

    Raises:
        JWTError: If token is invalid or expired
    """
    settings = get_settings()

    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def get_fernet() -> Fernet:
    """
    Get Fernet instance for encryption/decryption.

    Uses the ENCRYPTION_KEY from settings, deriving a proper
    Fernet key from it using SHA256.

    Returns:
        Fernet instance for encryption operations
    """
    settings = get_settings()

    # Derive a 32-byte key using SHA256, then base64 encode for Fernet
    key_bytes = hashlib.sha256(settings.encryption_key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)

    return Fernet(fernet_key)


def encrypt_token(token: str) -> str:
    """
    Encrypt an OAuth token for secure storage.

    OAuth tokens encrypted at rest with ENCRYPTION_KEY

    Args:
        token: Plain text token to encrypt

    Returns:
        Encrypted token as string (Fernet tokens are already base64-url-safe)
    """
    fernet = get_fernet()
    encrypted = fernet.encrypt(token.encode())
    # Fernet already returns base64-url-safe bytes, just decode to string
    return encrypted.decode('utf-8')


def decrypt_token(encrypted_token: str) -> str:
    """
    Decrypt an OAuth token from storage.

    Args:
        encrypted_token: Fernet encrypted token string

    Returns:
        Decrypted plain text token

    Raises:
        cryptography.fernet.InvalidToken: If decryption fails
    """
    fernet = get_fernet()
    # Handle both old (double-encoded) and new (single-encoded) formats
    try:
        # Try new format first (direct Fernet token)
        decrypted = fernet.decrypt(encrypted_token.encode('utf-8'))
        return decrypted.decode()
    except Exception:
        # Fall back to old format (double base64 encoded)
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_token.encode())
            decrypted = fernet.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception:
            raise


def generate_correlation_id() -> str:
    """
    Generate a unique correlation ID for request tracing.

    Returns:
        UUID string for correlation tracking
    """
    return str(uuid.uuid4())


def generate_secure_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token.

    Args:
        length: Number of bytes for the token

    Returns:
        URL-safe base64 encoded token
    """
    return secrets.token_urlsafe(length)


def validate_token_type(payload: dict[str, Any], expected_type: str) -> bool:
    """
    Validate that a token payload has the expected type.

    Args:
        payload: Decoded token payload
        expected_type: Expected token type (access/refresh)

    Returns:
        True if token type matches, False otherwise
    """
    return payload.get("type") == expected_type
