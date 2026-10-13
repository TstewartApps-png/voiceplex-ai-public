"""Inbound call routing: Twilio number -> tenant -> agent; attach-number endpoint."""

import pytest
from httpx import AsyncClient

from app.services.voice import twilio_handler as th
from app.utils.security import encrypt_token

NUMBER = "+15550001111"
INBOUND = "/api/v1/webhooks/twilio/voice"


async def _make_agent(client: AsyncClient, headers, company_id, name="Sarah", activate=True) -> str:
    r = await client.post("/api/v1/agents", json={"name": name, "type": "receptionist", "company_id": company_id}, headers=headers)
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]
    if activate:
        r = await client.post(f"/api/v1/agents/{agent_id}/activate", headers=headers)
        assert r.status_code == 200, r.text
    return agent_id


async def _save_twilio(db, user_id, agent_id=None):
    await db["settings"].insert_one({
        "user_id": user_id,
        "twilio": {
            "account_sid_encrypted": encrypt_token("AC" + "1" * 32),
            "auth_token_encrypted": encrypt_token("t" * 32),
            "phone_number": NUMBER,
            "agent_id": agent_id,
            "connected": True,
        },
    })


@pytest.fixture
def debug_mode(monkeypatch):
    """Skip webhook signatures for routing tests (covered separately in test_security)."""
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "debug", True)


@pytest.mark.asyncio
async def test_inbound_routes_to_single_active_agent(async_client, auth_headers, company, db, debug_mode):
    user = (await async_client.get("/api/v1/auth/me", headers=auth_headers)).json()
    agent_id = await _make_agent(async_client, auth_headers, company["id"])
    await _save_twilio(db, user["id"])

    r = await async_client.post(INBOUND, data={"CallSid": "CA1", "From": "+15559990000", "To": NUMBER, "CallStatus": "ringing"})
    assert r.status_code == 200
    assert "<Connect>" in r.text and "<Stream" in r.text and 'name="token"' in r.text
    call = await db["calls"].find_one({"twilio_call_sid": "CA1"})
    assert call and call["agent_id"] == agent_id and call["user_id"] == user["id"]


@pytest.mark.asyncio
async def test_inbound_uses_default_agent_when_several_active(async_client, auth_headers, company, db, debug_mode):
    user = (await async_client.get("/api/v1/auth/me", headers=auth_headers)).json()
    a1 = await _make_agent(async_client, auth_headers, company["id"], "One")
    a2 = await _make_agent(async_client, auth_headers, company["id"], "Two")
    await _save_twilio(db, user["id"], agent_id=a2)

    r = await async_client.post(INBOUND, data={"CallSid": "CA2", "From": "+1", "To": NUMBER, "CallStatus": "ringing"})
    assert r.status_code == 200 and "<Stream" in r.text
    assert (await db["calls"].find_one({"twilio_call_sid": "CA2"}))["agent_id"] == a2


@pytest.mark.asyncio
async def test_inbound_ambiguous_without_default_is_rejected_politely(async_client, auth_headers, company, db, debug_mode):
    user = (await async_client.get("/api/v1/auth/me", headers=auth_headers)).json()
    await _make_agent(async_client, auth_headers, company["id"], "One")
    await _make_agent(async_client, auth_headers, company["id"], "Two")
    await _save_twilio(db, user["id"])
    r = await async_client.post(INBOUND, data={"CallSid": "CA3", "From": "+1", "To": NUMBER, "CallStatus": "ringing"})
    assert r.status_code == 200 and "<Hangup" in r.text and "<Stream" not in r.text


@pytest.mark.asyncio
async def test_paused_agent_does_not_answer(async_client, auth_headers, company, db, debug_mode):
    user = (await async_client.get("/api/v1/auth/me", headers=auth_headers)).json()
    await _make_agent(async_client, auth_headers, company["id"], activate=False)
    await _save_twilio(db, user["id"])
    r = await async_client.post(INBOUND, data={"CallSid": "CA4", "From": "+1", "To": NUMBER, "CallStatus": "ringing"})
    assert "<Hangup" in r.text


@pytest.mark.asyncio
async def test_company_number_assignment_wins(async_client, auth_headers, company, db, debug_mode):
    from bson import ObjectId
    user = (await async_client.get("/api/v1/auth/me", headers=auth_headers)).json()
    a1 = await _make_agent(async_client, auth_headers, company["id"], "Default")
    a2 = await _make_agent(async_client, auth_headers, company["id"], "Explicit")
    await _save_twilio(db, user["id"], agent_id=a1)
    await db["companies"].update_one({"_id": ObjectId(company["id"])}, {"$push": {"phone_numbers": {
        "_id": ObjectId(), "number": NUMBER, "twilio_sid": "PNreal", "friendly_name": "", "agent_id": a2, "type": "local", "status": "active"}}})
    r = await async_client.post(INBOUND, data={"CallSid": "CA5", "From": "+1", "To": NUMBER, "CallStatus": "ringing"})
    assert (await db["calls"].find_one({"twilio_call_sid": "CA5"}))["agent_id"] == a2


# --- attach endpoint ---------------------------------------------------------

class _FakeNumber:
    sid = "PN" + "a" * 32
    phone_number = NUMBER
    friendly_name = "Main line"
    voice_url = ""


class _FakeTwilioClient:
    """Minimal stand-in for twilio.rest.Client used by TwilioHandler."""

    def __init__(self):
        self.updated = {}

        outer = self

        class _Numbers:
            def list(self, phone_number=None, limit=1):
                return [_FakeNumber()] if phone_number == NUMBER else []

            def __call__(self, sid):
                class _One:
                    def update(_s, **kw):
                        outer.updated[sid] = kw
                        return _FakeNumber()
                return _One()

        self.incoming_phone_numbers = _Numbers()


@pytest.fixture
def fake_twilio(monkeypatch):
    fake = _FakeTwilioClient()
    monkeypatch.setattr(th, "TwilioClient", lambda sid, tok: fake)
    return fake


@pytest.mark.asyncio
async def test_attach_requires_twilio_configured(async_client, auth_headers, company, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "twilio_account_sid", "")
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "")
    r = await async_client.post(f"/api/v1/companies/{company['id']}/phone-numbers", json={"number": NUMBER}, headers=auth_headers)
    assert r.status_code == 400 and r.json()["code"] == "TWILIO_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_attach_verifies_number_and_configures_webhook(async_client, auth_headers, company, db, fake_twilio):
    user = (await async_client.get("/api/v1/auth/me", headers=auth_headers)).json()
    agent_id = await _make_agent(async_client, auth_headers, company["id"])
    await _save_twilio(db, user["id"])

    r = await async_client.post(
        f"/api/v1/companies/{company['id']}/phone-numbers",
        json={"number": NUMBER, "friendly_name": "Front desk", "agent_id": agent_id},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    pn = r.json()["phone_numbers"][0]
    assert pn["number"] == NUMBER and pn["twilio_sid"] == _FakeNumber.sid and pn["agent_id"] == agent_id
    cfg = fake_twilio.updated[_FakeNumber.sid]
    assert cfg["voice_url"].endswith("/api/v1/webhooks/twilio/voice")
    assert cfg["status_callback"].endswith("/api/v1/webhooks/twilio/voice/status")

    # unknown number in the account -> 404, bad format -> 422
    r = await async_client.post(f"/api/v1/companies/{company['id']}/phone-numbers", json={"number": "+15550009999"}, headers=auth_headers)
    assert r.status_code == 404 and r.json()["code"] == "TWILIO_NUMBER_NOT_FOUND"
    r = await async_client.post(f"/api/v1/companies/{company['id']}/phone-numbers", json={"number": "555-1234"}, headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_twilio_test_configures_webhook(async_client, auth_headers, db, fake_twilio, monkeypatch):
    """Settings > Twilio > Test also points the saved number at this backend."""
    user = (await async_client.get("/api/v1/auth/me", headers=auth_headers)).json()
    await _save_twilio(db, user["id"])

    class _Acct:
        friendly_name = "Acme Twilio"

    class _FakeRestClient(_FakeTwilioClient):
        def __init__(self, sid, tok):
            super().__init__()
            self.api = type("api", (), {"accounts": lambda _s, sid: type("a", (), {"fetch": lambda _x: _Acct()})()})()

    import twilio.rest
    monkeypatch.setattr(twilio.rest, "Client", _FakeRestClient)
    monkeypatch.setattr(th, "TwilioClient", lambda sid, tok: fake_twilio)

    r = await async_client.post("/api/v1/settings/twilio/test", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] and body["webhook_configured"] is True
    assert body["inbound_voice_url"].endswith("/api/v1/webhooks/twilio/voice")
    assert (await db["settings"].find_one({"user_id": user["id"]}))["twilio"]["webhook_configured"] is True
