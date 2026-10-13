"""
Settings API endpoints for managing integration configurations.

Secure storage and retrieval of integration credentials.
All sensitive data is encrypted at rest.
"""

import asyncio
import logging
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, Database
from app.models.settings import (
    PersonaplexSettingsRequest,
    PersonaplexTestRequest,
    PersonaplexTestResponse,
    TwilioSettingsRequest,
    TwilioTestResponse,
    AnthropicSettingsRequest,
    AnthropicTestResponse,
    IntegrationStatusResponse,
    PersonaplexSettingsInDB,
    TwilioSettingsInDB,
    AnthropicSettingsInDB,
)
from app.utils.security import encrypt_token, decrypt_token
from app.services.voice.twilio_handler import TwilioHandler, TwilioHandlerError
from bson import ObjectId
from pydantic import BaseModel, Field, EmailStr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


# Profile models
class ProfileUpdateRequest(BaseModel):
    """Request to update user profile."""
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr


class ProfileResponse(BaseModel):
    """Response with user profile."""
    id: str
    name: str
    email: str


@router.put("/profile", response_model=ProfileResponse)
async def update_profile(
    request: ProfileUpdateRequest,
    current_user: CurrentUser,
    db: Database,
) -> ProfileResponse:
    """
    Update user profile (name and email).
    """
    now = datetime.utcnow()

    # Check if email is being changed and if it's already in use
    if request.email != current_user.email:
        existing = await db["users"].find_one({"email": request.email})
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"detail": "Email already in use", "code": "EMAIL_IN_USE"},
            )

    # Update user
    from bson import ObjectId
    result = await db["users"].update_one(
        {"_id": ObjectId(current_user.id)},
        {
            "$set": {
                "name": request.name,
                "email": request.email,
                "updated_at": now,
            }
        },
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "User not found", "code": "USER_NOT_FOUND"},
        )

    logger.info(f"Updated profile for user {current_user.id}")

    return ProfileResponse(
        id=current_user.id,
        name=request.name,
        email=request.email,
    )


@router.get("/integrations", response_model=IntegrationStatusResponse)
async def get_integration_status(
    current_user: CurrentUser,
    db: Database,
) -> IntegrationStatusResponse:
    """
    Get status of all integrations.

    Returns connection status and non-sensitive info for each integration.
    """
    settings = await db["settings"].find_one({"user_id": current_user.id})

    personaplex_status = {"connected": False}
    twilio_status = {"connected": False}
    anthropic_status = {"connected": False}

    if settings:
        if settings.get("personaplex"):
            personaplex_status = {
                "connected": settings["personaplex"].get("connected", False),
                "url": settings["personaplex"].get("websocket_url"),
            }

        if settings.get("twilio"):
            twilio_status = {
                "connected": settings["twilio"].get("connected", False),
                "phone_number": settings["twilio"].get("phone_number"),
                "agent_id": settings["twilio"].get("agent_id"),
                "webhook_configured": settings["twilio"].get("webhook_configured", False),
            }

        if settings.get("anthropic"):
            anthropic_status = {
                "connected": settings["anthropic"].get("connected", False),
                "has_key": bool(settings["anthropic"].get("api_key_encrypted")),
            }

    return IntegrationStatusResponse(
        personaplex=personaplex_status,
        twilio=twilio_status,
        anthropic=anthropic_status,
    )


# PersonaPlex endpoints

@router.post("/personaplex")
async def save_personaplex_settings(
    request: PersonaplexSettingsRequest,
    current_user: CurrentUser,
    db: Database,
):
    """
    Save PersonaPlex WebSocket URL.
    """
    now = datetime.utcnow()

    update_data = {
        "personaplex": {
            "websocket_url": request.websocket_url,
            "connected": False,  # Will be set to True after successful test
            "updated_at": now,
        },
        "updated_at": now,
    }

    # Upsert settings document
    result = await db["settings"].update_one(
        {"user_id": current_user.id},
        {
            "$set": update_data,
            "$setOnInsert": {"user_id": current_user.id, "created_at": now},
        },
        upsert=True,
    )

    logger.info(f"Saved PersonaPlex settings for user {current_user.id}")

    return {"success": True, "message": "PersonaPlex settings saved"}


@router.post("/personaplex/test", response_model=PersonaplexTestResponse)
async def test_personaplex_connection(
    request: PersonaplexTestRequest,
    current_user: CurrentUser,
    db: Database,
) -> PersonaplexTestResponse:
    """
    Test PersonaPlex WebSocket connection.

    Attempts to connect to the WebSocket URL and measures latency.
    """
    try:
        import websockets

        start_time = time.time()

        # Attempt WebSocket connection with timeout
        async with asyncio.timeout(10):
            async with websockets.connect(
                request.websocket_url,
                ping_interval=None,
                close_timeout=5,
            ) as ws:
                # Send a ping/config message to verify connection
                await ws.send('{"type": "ping"}')

                # Try to receive a response (with timeout)
                try:
                    async with asyncio.timeout(5):
                        await ws.recv()
                except asyncio.TimeoutError:
                    # Some servers might not respond to ping, but connection is valid
                    pass

        latency_ms = int((time.time() - start_time) * 1000)

        # Update settings to mark as connected
        now = datetime.utcnow()
        await db["settings"].update_one(
            {"user_id": current_user.id},
            {
                "$set": {
                    "personaplex.connected": True,
                    "personaplex.last_tested_at": now,
                    "personaplex.websocket_url": request.websocket_url,
                    "updated_at": now,
                },
                "$setOnInsert": {"user_id": current_user.id, "created_at": now},
            },
            upsert=True,
        )

        logger.info(f"PersonaPlex connection test successful for user {current_user.id}")

        return PersonaplexTestResponse(success=True, latency_ms=latency_ms)

    except asyncio.TimeoutError:
        logger.warning(f"PersonaPlex connection timeout for user {current_user.id}")
        return PersonaplexTestResponse(
            success=False,
            error="Connection timeout. Please check the URL and try again.",
        )
    except Exception as e:
        logger.error(f"PersonaPlex connection error for user {current_user.id}: {e}")
        return PersonaplexTestResponse(
            success=False,
            error=f"Connection failed: {str(e)}",
        )


# Twilio endpoints

@router.post("/twilio")
async def save_twilio_settings(
    request: TwilioSettingsRequest,
    current_user: CurrentUser,
    db: Database,
):
    """
    Save Twilio credentials.

    Credentials are encrypted before storage.
    """
    now = datetime.utcnow()

    # Encrypt sensitive credentials
    account_sid_encrypted = encrypt_token(request.account_sid)
    auth_token_encrypted = encrypt_token(request.auth_token)

    if request.agent_id:
        if not ObjectId.is_valid(request.agent_id) or not await db["agents"].find_one(
            {"_id": ObjectId(request.agent_id), "user_id": current_user.id}
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"detail": "Agent not found", "code": "AGENT_NOT_FOUND"},
            )

    update_data = {
        "twilio": {
            "account_sid_encrypted": account_sid_encrypted,
            "auth_token_encrypted": auth_token_encrypted,
            "phone_number": request.phone_number,
            "agent_id": request.agent_id,
            "webhook_configured": False,
            "connected": False,  # Will be set to True after successful test
            "updated_at": now,
        },
        "updated_at": now,
    }

    # Upsert settings document
    await db["settings"].update_one(
        {"user_id": current_user.id},
        {
            "$set": update_data,
            "$setOnInsert": {"user_id": current_user.id, "created_at": now},
        },
        upsert=True,
    )

    logger.info(f"Saved Twilio settings for user {current_user.id}")

    return {"success": True, "message": "Twilio credentials saved"}


@router.post("/twilio/test", response_model=TwilioTestResponse)
async def test_twilio_connection(
    current_user: CurrentUser,
    db: Database,
) -> TwilioTestResponse:
    """
    Test Twilio connection using stored credentials.

    Verifies account access by fetching account information.
    """
    # Get stored credentials
    settings = await db["settings"].find_one({"user_id": current_user.id})

    if not settings or not settings.get("twilio"):
        return TwilioTestResponse(
            success=False,
            error="Twilio credentials not configured. Please save credentials first.",
        )

    try:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioRestException

        # Decrypt credentials
        account_sid = decrypt_token(settings["twilio"]["account_sid_encrypted"])
        auth_token = decrypt_token(settings["twilio"]["auth_token_encrypted"])

        # Create Twilio client and fetch account info
        client = Client(account_sid, auth_token)
        account = await asyncio.get_running_loop().run_in_executor(
            None, lambda: client.api.accounts(account_sid).fetch()
        )

        # Point the saved number's voice webhook at this backend so inbound
        # calls actually arrive here.  Best-effort: credentials are valid even
        # if the number is not in this account.
        handler = TwilioHandler(account_sid=account_sid, auth_token=auth_token)
        webhook_configured = False
        webhook_error: str | None = None
        phone_number = settings["twilio"].get("phone_number")
        if phone_number:
            try:
                found = await handler.lookup_phone_number(phone_number)
                if not found:
                    webhook_error = f"{phone_number} is not a number in this Twilio account"
                else:
                    await handler.configure_phone_number(found["sid"])
                    webhook_configured = True
            except TwilioHandlerError as e:
                webhook_error = e.message

        # Update settings to mark as connected
        now = datetime.utcnow()
        await db["settings"].update_one(
            {"user_id": current_user.id},
            {
                "$set": {
                    "twilio.connected": True,
                    "twilio.account_name": account.friendly_name,
                    "twilio.webhook_configured": webhook_configured,
                    "twilio.last_tested_at": now,
                    "updated_at": now,
                }
            },
        )

        logger.info(f"Twilio connection test successful for user {current_user.id}")

        return TwilioTestResponse(
            success=True,
            account_name=account.friendly_name,
            webhook_configured=webhook_configured,
            webhook_error=webhook_error,
            inbound_voice_url=handler.inbound_voice_url,
        )

    except TwilioRestException as e:
        logger.warning(f"Twilio API error for user {current_user.id}: {e}")
        return TwilioTestResponse(
            success=False,
            error=f"Twilio API error: {e.msg}",
        )
    except Exception as e:
        logger.error(f"Twilio connection error for user {current_user.id}: {e}")
        return TwilioTestResponse(
            success=False,
            error=f"Connection failed: {str(e)}",
        )


# Anthropic endpoints

@router.post("/anthropic")
async def save_anthropic_settings(
    request: AnthropicSettingsRequest,
    current_user: CurrentUser,
    db: Database,
):
    """
    Save Anthropic API key.

    API key is encrypted before storage.
    """
    now = datetime.utcnow()

    # Trim whitespace and encrypt API key
    api_key = request.api_key.strip()
    api_key_encrypted = encrypt_token(api_key)

    update_data = {
        "anthropic": {
            "api_key_encrypted": api_key_encrypted,
            "connected": False,  # Will be set to True after successful test
            "updated_at": now,
        },
        "updated_at": now,
    }

    # Upsert settings document
    await db["settings"].update_one(
        {"user_id": current_user.id},
        {
            "$set": update_data,
            "$setOnInsert": {"user_id": current_user.id, "created_at": now},
        },
        upsert=True,
    )

    logger.info(f"Saved Anthropic settings for user {current_user.id}")

    return {"success": True, "message": "Anthropic API key saved"}


@router.post("/anthropic/test", response_model=AnthropicTestResponse)
async def test_anthropic_connection(
    current_user: CurrentUser,
    db: Database,
) -> AnthropicTestResponse:
    """
    Test Anthropic API connection using stored API key.

    Verifies API access by making a simple API call.
    """
    # Get stored credentials
    settings = await db["settings"].find_one({"user_id": current_user.id})

    if not settings or not settings.get("anthropic"):
        return AnthropicTestResponse(
            success=False,
            error="Anthropic API key not configured. Please save API key first.",
        )

    try:
        from anthropic import AsyncAnthropic, APIError

        # Decrypt API key
        api_key = decrypt_token(settings["anthropic"]["api_key_encrypted"])

        # Debug: log key info (obfuscated) to diagnose 401 errors
        logger.info(f"Anthropic key length: {len(api_key)}, starts with: {api_key[:15]}..., ends with: ...{api_key[-4:]}")

        # Create client and make a simple request
        client = AsyncAnthropic(api_key=api_key)

        # Use a minimal message to verify API access
        response = await client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}],
        )

        # Update settings to mark as connected
        now = datetime.utcnow()
        await db["settings"].update_one(
            {"user_id": current_user.id},
            {
                "$set": {
                    "anthropic.connected": True,
                    "anthropic.last_tested_at": now,
                    "updated_at": now,
                }
            },
        )

        logger.info(f"Anthropic connection test successful for user {current_user.id}")

        return AnthropicTestResponse(
            success=True,
            model=response.model,
        )

    except APIError as e:
        logger.warning(f"Anthropic API error for user {current_user.id}: {e}")
        return AnthropicTestResponse(
            success=False,
            error=f"API error: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Anthropic connection error for user {current_user.id}: {e}")
        return AnthropicTestResponse(
            success=False,
            error=f"Connection failed: {str(e)}",
        )


@router.delete("/anthropic")
async def delete_anthropic_settings(
    current_user: CurrentUser,
    db: Database,
):
    """
    Delete stored Anthropic API key.

    Removes the API key from storage so user can re-enter it.
    """
    now = datetime.utcnow()

    # Remove anthropic settings
    result = await db["settings"].update_one(
        {"user_id": current_user.id},
        {
            "$unset": {"anthropic": ""},
            "$set": {"updated_at": now},
        },
    )

    if result.modified_count > 0:
        logger.info(f"Deleted Anthropic settings for user {current_user.id}")
        return {"success": True, "message": "Anthropic API key deleted"}

    return {"success": False, "message": "No API key was stored"}
