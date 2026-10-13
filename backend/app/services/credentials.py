"""
Single source of truth for third-party credentials.

Precedence (highest first):
  1. Per-user values saved in the dashboard (``settings`` collection, encrypted at rest)
  2. Platform-wide values from the environment (``.env`` / container env)

Before this module existed the dashboard wrote credentials to MongoDB while
every runtime consumer (Claude client, Twilio handler, voice-server client)
silently read only the environment, so "Connected" badges were meaningless.
All consumers must go through this resolver.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.utils.security import decrypt_token

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TwilioCredentials:
    account_sid: str
    auth_token: str
    phone_number: str | None = None
    source: str = "env"  # "user" | "env"


class CredentialResolver:
    """Resolve credentials for a given tenant (user)."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def _user_settings(self, user_id: str | None) -> dict:
        if not user_id:
            return {}
        doc = await self.db["settings"].find_one({"user_id": user_id})
        return doc or {}

    # ----- Anthropic -------------------------------------------------------
    async def anthropic_api_key(self, user_id: str | None) -> str:
        doc = await self._user_settings(user_id)
        enc = (doc.get("anthropic") or {}).get("api_key_encrypted")
        if enc:
            try:
                return decrypt_token(enc)
            except Exception:  # noqa: BLE001
                logger.error("Could not decrypt stored Anthropic key for user %s; falling back to env", user_id)
        return get_settings().anthropic_api_key or ""

    # ----- Voice server ----------------------------------------------------
    async def voice_server_url(self, user_id: str | None) -> str:
        doc = await self._user_settings(user_id)
        pp = doc.get("personaplex") or {}
        if pp.get("websocket_url"):
            return pp["websocket_url"]
        return get_settings().personaplex_url or ""

    # ----- Twilio ----------------------------------------------------------
    async def twilio(self, user_id: str | None) -> TwilioCredentials | None:
        doc = await self._user_settings(user_id)
        tw = doc.get("twilio") or {}
        if tw.get("account_sid_encrypted") and tw.get("auth_token_encrypted"):
            try:
                return TwilioCredentials(
                    account_sid=decrypt_token(tw["account_sid_encrypted"]),
                    auth_token=decrypt_token(tw["auth_token_encrypted"]),
                    phone_number=tw.get("phone_number"),
                    source="user",
                )
            except Exception:  # noqa: BLE001
                logger.error("Could not decrypt stored Twilio credentials for user %s; falling back to env", user_id)
        s = get_settings()
        if s.twilio_account_sid and s.twilio_auth_token:
            return TwilioCredentials(s.twilio_account_sid, s.twilio_auth_token, None, "env")
        return None

    async def twilio_auth_tokens_for_webhook(
        self, *, called_number: str | None = None, call_sid: str | None = None
    ) -> list[str]:
        """
        Candidate auth tokens that may have signed an inbound Twilio webhook.

        Twilio signs with the auth token of the account that owns the number /
        call, so we look the tenant up from the webhook payload itself
        (``To`` for new calls, ``CallSid`` for status callbacks) and add the
        platform token as a fallback.
        """
        tokens: list[str] = []
        user_id: str | None = None

        if call_sid:
            call = await self.db["calls"].find_one({"twilio_call_sid": call_sid}, {"user_id": 1})
            if call:
                user_id = call.get("user_id")
        if not user_id and called_number:
            doc = await self.db["settings"].find_one(
                {"twilio.phone_number": called_number}, {"user_id": 1}
            )
            if doc:
                user_id = doc.get("user_id")

        if user_id:
            creds = await self.twilio(user_id)
            if creds and creds.source == "user":
                tokens.append(creds.auth_token)

        env_token = get_settings().twilio_auth_token
        if env_token and env_token not in tokens:
            tokens.append(env_token)
        return tokens

    async def user_id_for_twilio_number(self, phone_number: str) -> str | None:
        """Tenant that registered this Twilio number in Settings."""
        doc = await self.db["settings"].find_one({"twilio.phone_number": phone_number}, {"user_id": 1})
        return doc.get("user_id") if doc else None
