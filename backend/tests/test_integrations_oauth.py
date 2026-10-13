"""OAuth endpoints: query contract and redirect targets match the frontend routes."""

import pytest

from app.config import get_settings


@pytest.mark.asyncio
async def test_auth_url_requires_company_id(async_client, auth_headers):
    r = await async_client.get("/api/v1/integrations/google/auth-url", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_auth_url_reports_unconfigured(async_client, auth_headers, company, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "")
    r = await async_client.get(
        "/api/v1/integrations/google/auth-url", params={"company_id": company["id"]}, headers=auth_headers
    )
    assert r.status_code == 503 and r.json()["code"] == "GOOGLE_NOT_CONFIGURED"
    monkeypatch.setattr(get_settings(), "microsoft_client_id", "")
    r = await async_client.get(
        "/api/v1/integrations/microsoft/auth-url", params={"company_id": company["id"]}, headers=auth_headers
    )
    assert r.status_code == 503 and r.json()["code"] == "MICROSOFT_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_auth_url_is_tenant_scoped(async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "id")
    monkeypatch.setattr(get_settings(), "google_client_secret", "secret")
    r = await async_client.get(
        "/api/v1/integrations/google/auth-url",
        params={"company_id": "64b000000000000000000099"}, headers=auth_headers,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_auth_url_generates_google_url(async_client, auth_headers, company, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(get_settings(), "google_client_secret", "secret")
    r = await async_client.get(
        "/api/v1/integrations/google/auth-url",
        params={"company_id": company["id"], "redirect_after": "http://localhost:3000/dashboard/integrations"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["auth_url"].startswith("https://accounts.google.com/o/oauth2/")
    assert "state=" in r.json()["auth_url"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_callback_error_redirects_to_existing_frontend_route(async_client, provider):
    r = await async_client.get(
        f"/api/v1/integrations/{provider}/callback", params={"code": "x", "state": "y", "error": "access_denied"}
    )
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith(get_settings().frontend_url + "/dashboard/integrations?error=")


@pytest.mark.asyncio
async def test_callback_invalid_state_redirects(async_client):
    r = await async_client.get("/api/v1/integrations/google/callback", params={"code": "x", "state": "bogus"})
    assert r.status_code in (302, 307)
    assert "/dashboard/integrations?error=" in r.headers["location"]
