"""Regression: tools/integrations used `await get_database()` (sync function) and raised TypeError
before doing any work, so calendar/email tools and OAuth token storage could never run."""

from datetime import datetime

import pytest
from bson import ObjectId

from app.services.ai.tools import get_tool_registry, register_all_tools, ToolContext
from app.services.ai.tools.calendar import _get_calendar_service


def _ctx(company_id: str) -> ToolContext:
    return ToolContext(
        session_id="s", call_id="c", agent_id="a", company_id=company_id, user_id="u",
        caller_phone="+1", caller_name=None, current_time=datetime.utcnow(), extra={},
    )


@pytest.mark.asyncio
async def test_calendar_service_lookup_without_integration(company, db):
    service, provider = await _get_calendar_service(company["id"])
    assert service is None and provider is None


@pytest.mark.asyncio
async def test_check_availability_tool_runs(company, db):
    register_all_tools()
    result = await get_tool_registry().execute_tool(
        tool_name="check_calendar_availability",
        context=_ctx(company["id"]),
        input_data={"start_date": "2030-01-07", "end_date": "2030-01-08", "duration_minutes": 30},
        timeout=5.0,
    )
    assert result.success, result.error
    assert result.data  # mock slots when no calendar is connected


@pytest.mark.asyncio
async def test_google_service_reads_company(company, db):
    from app.services.integrations.google_calendar import GoogleCalendarService

    svc = GoogleCalendarService(company["id"])
    # no tokens stored -> a clean "not connected" error, not a TypeError
    with pytest.raises(Exception) as exc:
        await svc._ensure_credentials()
    assert not isinstance(exc.value, TypeError), exc.value
