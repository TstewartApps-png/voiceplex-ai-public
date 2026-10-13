"""CredentialResolver: dashboard-saved credentials take precedence over env, env is the fallback."""

import pytest

from app.config import get_settings
from app.services.credentials import CredentialResolver
from app.utils.security import encrypt_token


@pytest.mark.asyncio
async def test_env_fallbacks(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-env")
    monkeypatch.setattr(get_settings(), "personaplex_url", "ws://env:8765/ws")
    monkeypatch.setattr(get_settings(), "twilio_account_sid", "ACenv")
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "tokenv")
    r = CredentialResolver(db)
    assert await r.anthropic_api_key("u1") == "sk-env"
    assert await r.voice_server_url("u1") == "ws://env:8765/ws"
    tw = await r.twilio("u1")
    assert tw and tw.source == "env" and tw.account_sid == "ACenv"


@pytest.mark.asyncio
async def test_user_settings_take_precedence(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-env")
    monkeypatch.setattr(get_settings(), "personaplex_url", "ws://env:8765/ws")
    await db["settings"].insert_one({
        "user_id": "u1",
        "anthropic": {"api_key_encrypted": encrypt_token("sk-user")},
        "personaplex": {"websocket_url": "wss://pod-8765.proxy.runpod.net/ws", "connected": True},
        "twilio": {
            "account_sid_encrypted": encrypt_token("ACuser"),
            "auth_token_encrypted": encrypt_token("tokuser"),
            "phone_number": "+15550001111",
        },
    })
    r = CredentialResolver(db)
    assert await r.anthropic_api_key("u1") == "sk-user"
    assert await r.anthropic_api_key("u2") == "sk-env"
    assert await r.voice_server_url("u1") == "wss://pod-8765.proxy.runpod.net/ws"
    tw = await r.twilio("u1")
    assert tw.source == "user" and tw.auth_token == "tokuser" and tw.phone_number == "+15550001111"
    assert await r.user_id_for_twilio_number("+15550001111") == "u1"
    assert await r.twilio_auth_tokens_for_webhook(called_number="+15550001111") == ["tokuser"]


@pytest.mark.asyncio
async def test_nothing_configured(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    monkeypatch.setattr(get_settings(), "twilio_account_sid", "")
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "")
    r = CredentialResolver(db)
    assert await r.anthropic_api_key("u1") == ""
    assert await r.twilio("u1") is None
    assert await r.twilio_auth_tokens_for_webhook(called_number="+1") == []


@pytest.mark.asyncio
async def test_generate_prompt_503_without_key(async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    r = await async_client.post(
        "/api/v1/agents/generate-prompt",
        json={"agent_type": "receptionist", "business_description": "A dental clinic"},
        headers=auth_headers,
    )
    assert r.status_code == 503 and r.json()["code"] == "AI_NOT_CONFIGURED"
