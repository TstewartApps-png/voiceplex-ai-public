"""The seed script must produce data the API can actually see (string foreign keys)."""

import pytest

import seed_database


@pytest.mark.asyncio
async def test_seed_is_visible_through_api_and_idempotent(async_client, db, monkeypatch):
    async def _noop():
        return None

    monkeypatch.setattr(seed_database, "connect_to_mongodb", _noop)
    monkeypatch.setattr(seed_database, "close_mongodb_connection", _noop)

    await seed_database.seed()
    await seed_database.seed()  # re-run must not duplicate

    r = await async_client.post("/api/v1/auth/login", json={"email": seed_database.DEMO_EMAIL, "password": seed_database.DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    companies = (await async_client.get("/api/v1/companies", headers=headers)).json()
    companies = companies if isinstance(companies, list) else companies["items"]
    assert len(companies) == 1 and companies[0]["name"] == "Acme Corporation"

    agents = (await async_client.get("/api/v1/agents", headers=headers)).json()
    agents = agents if isinstance(agents, list) else agents["items"]
    assert len(agents) == 3
    assert {a["status"] for a in agents} == {"active", "draft"}
    assert all(a["company_id"] == companies[0]["id"] for a in agents)
