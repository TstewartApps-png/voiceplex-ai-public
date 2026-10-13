"""Ending a call bills minutes to the user and rolls up agent analytics."""

from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from app.models.call import CallOutcome
from app.services.voice.call_orchestrator import CallOrchestrator, CallSession, SessionState
from app.models.agent import AgentResponse


async def _setup(async_client, auth_headers, company):
    r = await async_client.post(
        "/api/v1/agents", json={"name": "Sarah", "type": "receptionist", "company_id": company["id"]}, headers=auth_headers
    )
    agent = AgentResponse.model_validate({**r.json(), "_id": r.json()["id"]})
    user = (await async_client.get("/api/v1/auth/me", headers=auth_headers)).json()
    return agent, user


@pytest.mark.asyncio
async def test_end_session_records_usage_and_analytics(async_client, auth_headers, company, db):
    agent, user = await _setup(async_client, auth_headers, company)
    call_id = str((await db["calls"].insert_one({
        "agent_id": agent.id, "company_id": company["id"], "user_id": user["id"], "direction": "inbound",
        "from_number": "+1", "to_number": "+2", "status": "in_progress", "transcript": [],
        "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
    })).inserted_id)

    orch = CallOrchestrator(db)
    session = CallSession(session_id="s1", call_id=call_id, agent=agent, company_id=company["id"],
                          user_id=user["id"], twilio_call_sid="CA1", state=SessionState.ACTIVE)
    session.answered_at = datetime.utcnow() - timedelta(seconds=125)   # 2m05s -> 3 billable minutes (ceil)
    orch._sessions["s1"] = session

    await orch.end_session("s1", "caller_hangup")

    assert "s1" not in orch._sessions
    user_doc = await db["users"].find_one({"_id": ObjectId(user["id"])})
    assert user_doc["subscription"]["minutes_used"] == 3
    usage = await db["usage_records"].find_one({"call_id": call_id})
    assert usage and usage["agent_id"] == agent.id and usage["duration_seconds"] >= 125
    agent_doc = await db["agents"].find_one({"_id": ObjectId(agent.id)})
    assert agent_doc["analytics"]["total_calls"] == 1
    assert 2.0 <= agent_doc["analytics"]["total_minutes"] <= 2.2
    call_doc = await db["calls"].find_one({"_id": ObjectId(call_id)})
    assert call_doc["status"] == "completed" and call_doc["duration_seconds"] >= 125


@pytest.mark.asyncio
async def test_unanswered_call_is_not_billed(async_client, auth_headers, company, db):
    agent, user = await _setup(async_client, auth_headers, company)
    call_id = str((await db["calls"].insert_one({
        "agent_id": agent.id, "company_id": company["id"], "user_id": user["id"], "direction": "inbound",
        "from_number": "+1", "to_number": "+2", "status": "ringing", "transcript": [],
        "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
    })).inserted_id)
    orch = CallOrchestrator(db)
    orch._sessions["s2"] = CallSession(session_id="s2", call_id=call_id, agent=agent, company_id=company["id"],
                                       user_id=user["id"], twilio_call_sid="CA2")
    await orch.end_session("s2", "failed")
    assert (await db["users"].find_one({"_id": ObjectId(user["id"])}))["subscription"]["minutes_used"] == 0
    assert await db["usage_records"].count_documents({}) == 0
    assert (await db["agents"].find_one({"_id": ObjectId(agent.id)}))["analytics"]["total_calls"] == 1


def test_analytics_increment_by_outcome():
    inc = CallOrchestrator._analytics_increment(CallOutcome.APPOINTMENT_SCHEDULED, 90)
    assert inc["analytics.appointments_booked"] == 1 and inc["analytics.total_minutes"] == 1.5
    assert "analytics.messages_taken" not in inc
    assert CallOrchestrator._analytics_increment(CallOutcome.TRANSFERRED, 10)["analytics.transfers_made"] == 1


@pytest.mark.asyncio
async def test_billing_usage_endpoint_works(async_client, auth_headers):
    """Regression: UsageTracker awaited the synchronous get_database() and raised TypeError."""
    r = await async_client.get("/api/v1/billing/usage", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "minutes_used" in r.json()
