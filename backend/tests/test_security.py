"""Security regression tests: Twilio webhook signatures, session endpoint auth, SSRF guard, stream token."""

import pytest
from httpx import AsyncClient
from twilio.request_validator import RequestValidator

from app.config import get_settings
from app.webhooks import twilio_webhooks
from app.services.voice import twilio_handler as th


WEBHOOK = "/api/v1/webhooks/twilio/voice/status"
FORM = {"CallSid": "CA123", "CallStatus": "completed", "CallDuration": "42"}


@pytest.fixture
def twilio_token(monkeypatch):
    """Configure a platform-level Twilio auth token (env) for signature tests."""
    token = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(get_settings(), "twilio_auth_token", token)
    return token


# --- Twilio webhook signature -------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature(async_client: AsyncClient, twilio_token):
    r = await async_client.post(WEBHOOK, data=FORM)
    assert r.status_code == 401
    assert r.json()["code"] == "MISSING_SIGNATURE"


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(async_client: AsyncClient, twilio_token):
    r = await async_client.post(WEBHOOK, data=FORM, headers={"X-Twilio-Signature": "bogus"})
    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_SIGNATURE"


@pytest.mark.asyncio
async def test_webhook_accepts_valid_signature_for_backend_url(async_client: AsyncClient, twilio_token):
    # Twilio signs the public URL it was configured with (BACKEND_URL) + sorted POST params
    url = get_settings().backend_url.rstrip("/") + WEBHOOK
    sig = RequestValidator(twilio_token).compute_signature(url, FORM)
    r = await async_client.post(WEBHOOK, data=FORM, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_webhook_accepts_valid_signature_for_forwarded_host(async_client: AsyncClient, twilio_token):
    # e.g. ngrok in front of the dev server
    url = "https://abc.ngrok.app" + WEBHOOK
    sig = RequestValidator(twilio_token).compute_signature(url, FORM)
    r = await async_client.post(
        WEBHOOK, data=FORM,
        headers={"X-Twilio-Signature": sig, "X-Forwarded-Proto": "https", "X-Forwarded-Host": "abc.ngrok.app"},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_webhook_accepts_tenant_saved_twilio_token(async_client: AsyncClient, auth_headers, db):
    """A tenant's own Twilio token (saved in Settings) validates webhooks for their number."""
    from app.utils.security import encrypt_token

    user = (await async_client.get("/api/v1/auth/me", headers=auth_headers)).json()
    tenant_token = "fedcba9876543210fedcba9876543210"
    await db["settings"].insert_one({
        "user_id": user["id"],
        "twilio": {
            "account_sid_encrypted": encrypt_token("AC" + "1" * 32),
            "auth_token_encrypted": encrypt_token(tenant_token),
            "phone_number": "+15550001111",
            "connected": True,
        },
    })
    form = {"CallSid": "CA9", "From": "+15559998888", "To": "+15550001111", "CallStatus": "ringing"}
    url = get_settings().backend_url.rstrip("/") + "/api/v1/webhooks/twilio/voice"
    sig = RequestValidator(tenant_token).compute_signature(url, form)
    r = await async_client.post("/api/v1/webhooks/twilio/voice", data=form, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200, r.text          # signature accepted (no agent yet -> polite hangup TwiML)
    assert "not currently in service" in r.text

    bad = RequestValidator("0" * 32).compute_signature(url, form)
    r = await async_client.post("/api/v1/webhooks/twilio/voice", data=form, headers={"X-Twilio-Signature": bad})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_all_twilio_routes_are_signature_protected():
    from fastapi.routing import APIRoute

    for route in twilio_webhooks.router.routes:
        if isinstance(route, APIRoute):
            names = {d.call.__name__ for d in route.dependant.dependencies if d.call}
            assert "verify_twilio_webhook" in names, route.path


# --- voice session endpoints require auth and are tenant-scoped --------------

@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/voice/sessions"),
    ("GET", "/api/v1/voice/sessions/abc"),
    ("POST", "/api/v1/voice/sessions/abc/end"),
])
async def test_voice_session_endpoints_require_auth(async_client: AsyncClient, method, path):
    r = await async_client.request(method, path)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_voice_sessions_are_tenant_scoped(async_client: AsyncClient, auth_headers, db):
    # plant a session owned by *another* user directly in the orchestrator
    from app.services.voice.call_orchestrator import get_orchestrator, CallSession
    from app.models.agent import AgentResponse, Voice, Persona, Capabilities, CalendarSettings, TransferSettings, ConversationSettings, AgentAnalytics
    from datetime import datetime

    agent = AgentResponse(
        _id="64b000000000000000000001", company_id="c", user_id="someone-else", name="A", type="receptionist",
        status="active", voice=Voice(), persona=Persona(), capabilities=Capabilities(),
        calendar_settings=CalendarSettings(), transfer_settings=TransferSettings(),
        conversation_settings=ConversationSettings(), knowledge_base=[], analytics=AgentAnalytics(),
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    orch = get_orchestrator(db)
    orch._sessions["sess_other"] = CallSession(
        session_id="sess_other", call_id="call1", agent=agent, company_id="c",
        user_id="someone-else", twilio_call_sid="CA1",
    )
    r = await async_client.get("/api/v1/voice/sessions", headers=auth_headers)
    assert r.status_code == 200 and r.json()["active_sessions"] == 0
    r = await async_client.get("/api/v1/voice/sessions/sess_other", headers=auth_headers)
    assert r.status_code == 404
    r = await async_client.post("/api/v1/voice/sessions/sess_other/end", headers=auth_headers)
    assert r.status_code == 404
    assert "sess_other" in orch._sessions  # not ended by a foreign tenant


# --- SSRF guard on /knowledge/scrape -------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://localhost:8000/health",
    "http://127.0.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/internal",
    "http://[::1]/",
    "ftp://example.com/x",
    "http://user:pass@example.com/",
])
async def test_scrape_blocks_private_and_invalid_targets(async_client: AsyncClient, auth_headers, url):
    r = await async_client.post("/api/v1/knowledge/scrape", json={"url": url}, headers=auth_headers)
    assert r.status_code in (400, 422), (url, r.text)


# --- stream token is embedded in TwiML ------------------------------------------

def test_twiml_contains_stream_token():
    handler = th.TwilioHandler()
    twiml = handler.generate_answer_twiml(session_id="call_abc", stream_token="tok123")
    assert 'name="session_id" value="call_abc"' in twiml
    assert 'name="token" value="tok123"' in twiml
    twiml = handler.generate_outbound_twiml(session_id="call_abc", stream_token="tok123")
    assert 'name="token" value="tok123"' in twiml
