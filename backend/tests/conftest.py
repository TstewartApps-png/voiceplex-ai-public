"""
Pytest configuration and fixtures.

Tests run against an in-memory MongoDB (mongomock-motor) so no external
services are needed.  Settings are injected via environment variables *before*
`app.main` is imported (pydantic-settings reads them at import time).
"""

from __future__ import annotations

import os
from typing import AsyncGenerator

# --- test environment must be set before importing the app ------------------
# forced (tests depend on them); the rest only default
os.environ["APP_ENV"] = "development"
os.environ["DEBUG"] = "false"
os.environ["DEV_MODE"] = "true"
os.environ["TWILIO_AUTH_TOKEN"] = ""
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-characters-long")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-at-least-32-chars-long")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/voiceplex_test")
os.environ.setdefault("MONGODB_DB_NAME", "voiceplex_test")
os.environ.setdefault("BACKEND_URL", "https://api.example.test")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

import app.database as database_module
from app.main import app


@pytest_asyncio.fixture
async def db():
    """Fresh in-memory database for every test, wired into the app."""
    client = AsyncMongoMockClient()
    mock_db = client["voiceplex_test"]
    database_module._client = client  # type: ignore[assignment]
    database_module._database = mock_db  # type: ignore[assignment]
    # reset lazily-created singletons that cache the db
    import app.services.voice.call_orchestrator as orch

    orch._orchestrator = None
    yield mock_db
    database_module._database = None
    database_module._client = None


@pytest_asyncio.fixture
async def async_client(db) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client bound to the ASGI app (lifespan is intentionally not run)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def sample_user_data() -> dict:
    return {"email": "test@example.com", "password": "TestPassword123", "name": "Test User"}


@pytest.fixture
def sample_company_data() -> dict:
    return {"name": "Test Company", "industry": "Technology", "website": "https://example.com"}


@pytest.fixture
def sample_agent_data() -> dict:
    return {"name": "Test Agent", "type": "receptionist"}


@pytest_asyncio.fixture
async def auth_headers(async_client: AsyncClient, sample_user_data: dict) -> dict:
    """Register a user and return bearer headers."""
    r = await async_client.post("/api/v1/auth/register", json=sample_user_data)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest_asyncio.fixture
async def company(async_client: AsyncClient, auth_headers: dict, sample_company_data: dict) -> dict:
    r = await async_client.post("/api/v1/companies", json=sample_company_data, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()
