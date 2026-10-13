"""Authentication endpoint tests (in-memory MongoDB)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_login_me(async_client: AsyncClient, sample_user_data: dict):
    r = await async_client.post("/api/v1/auth/register", json=sample_user_data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert "access_token" in body and "refresh_token" in body

    r = await async_client.post(
        "/api/v1/auth/login",
        json={"email": sample_user_data["email"], "password": sample_user_data["password"]},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    r = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == sample_user_data["email"]
    assert "password_hash" not in r.json()


@pytest.mark.asyncio
async def test_register_duplicate_email(async_client: AsyncClient, sample_user_data: dict):
    assert (await async_client.post("/api/v1/auth/register", json=sample_user_data)).status_code == 201
    r = await async_client.post("/api/v1/auth/register", json=sample_user_data)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_register_invalid_email(async_client: AsyncClient):
    r = await async_client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "TestPassword123", "name": "x"},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_register_weak_password(async_client: AsyncClient):
    r = await async_client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.co", "password": "weak", "name": "x"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_login_invalid_credentials(async_client: AsyncClient, sample_user_data: dict):
    await async_client.post("/api/v1/auth/register", json=sample_user_data)
    r = await async_client.post(
        "/api/v1/auth/login", json={"email": sample_user_data["email"], "password": "Wrong123456"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(async_client: AsyncClient):
    assert (await async_client.get("/api/v1/auth/me")).status_code in (401, 403)
    r = await async_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(async_client: AsyncClient, sample_user_data: dict):
    r = await async_client.post("/api/v1/auth/register", json=sample_user_data)
    refresh = r.json()["refresh_token"]
    r = await async_client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
    assert (await async_client.post("/api/v1/auth/refresh", json={"refresh_token": "bad"})).status_code == 401


@pytest.mark.asyncio
async def test_health(async_client: AsyncClient):
    r = await async_client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy"
