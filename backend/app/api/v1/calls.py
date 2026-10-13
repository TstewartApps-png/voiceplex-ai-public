"""
Calls API endpoints.

API endpoints:
- GET    /api/v1/calls
- GET    /api/v1/calls/{id}
- GET    /api/v1/calls/{id}/transcript
- GET    /api/v1/calls/{id}/recording
- POST   /api/v1/calls/outbound
- PUT    /api/v1/calls/{id}/notes
- PUT    /api/v1/calls/{id}/tags
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Database, check_minutes_available
from app.models.call import (
    CallCreate,
    CallResponse,
    CallStatus,
    CallOutcome,
    CallDirection,
    TranscriptEntry,
)
from app.services.call_service import (
    CallService,
    CallFilter,
    CallNotFoundError,
    AgentNotFoundError,
    AgentNotActiveError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calls", tags=["Calls"])


# Response models
class CallListResponse(BaseModel):
    """Paginated call list response."""

    items: list[CallResponse] = Field(..., description="List of calls")
    total: int = Field(..., description="Total number of calls")
    skip: int = Field(..., description="Number skipped")
    limit: int = Field(..., description="Maximum returned")


class TranscriptResponse(BaseModel):
    """Call transcript response."""

    call_id: str = Field(..., description="Call ID")
    transcript: list[TranscriptEntry] = Field(..., description="Transcript entries")
    total_entries: int = Field(..., description="Total number of entries")


class RecordingResponse(BaseModel):
    """Call recording response."""

    call_id: str = Field(..., description="Call ID")
    recording_url: str | None = Field(..., description="Recording URL")
    recording_duration: int | None = Field(..., description="Recording duration in seconds")
    available: bool = Field(..., description="Whether recording is available")


class OutboundCallRequest(BaseModel):
    """Request model for initiating an outbound call."""

    agent_id: str = Field(..., description="Agent to use for the call")
    to_number: str = Field(..., description="Phone number to call")
    from_number: str | None = Field(
        default=None, description="Caller ID (must be a number owned by the company)"
    )


class UpdateNotesRequest(BaseModel):
    """Request model for updating call notes."""

    notes: str = Field(..., description="Internal notes content")


class UpdateTagsRequest(BaseModel):
    """Request model for updating call tags."""

    tags: list[str] = Field(..., description="List of tags")


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str = Field(..., description="Response message")


class CallStatsResponse(BaseModel):
    """Call statistics response."""

    total_calls: int = Field(..., description="Total number of calls")
    total_duration_seconds: int = Field(..., description="Total call duration")
    total_billable_minutes: float = Field(..., description="Total billable minutes")
    avg_duration_seconds: float = Field(..., description="Average call duration")
    completed_calls: int = Field(..., description="Number of completed calls")
    appointments_scheduled: int = Field(..., description="Appointments scheduled")
    messages_taken: int = Field(..., description="Messages taken")
    leads_qualified: int = Field(..., description="Leads qualified")


def _get_call_service(db: Database) -> CallService:
    """Get call service instance."""
    return CallService(db)


@router.get(
    "",
    response_model=CallListResponse,
    summary="List calls",
    description="Get all calls for the current user with filtering and pagination.",
)
async def list_calls(
    current_user: CurrentUser,
    db: Database,
    agent_id: Annotated[str | None, Query(description="Filter by agent")] = None,
    company_id: Annotated[str | None, Query(description="Filter by company")] = None,
    status: Annotated[CallStatus | None, Query(description="Filter by status")] = None,
    outcome: Annotated[CallOutcome | None, Query(description="Filter by outcome")] = None,
    direction: Annotated[CallDirection | None, Query(description="Filter by direction")] = None,
    date_from: Annotated[datetime | None, Query(description="Filter from date")] = None,
    date_to: Annotated[datetime | None, Query(description="Filter to date")] = None,
    search: Annotated[str | None, Query(description="Search in caller info/summary")] = None,
    skip: Annotated[int, Query(ge=0, description="Records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records")] = 50,
) -> CallListResponse:
    """
    List calls for the current user.

    Supports filtering by:
    - agent_id: Filter by specific agent
    - company_id: Filter by specific company
    - status: Filter by call status (queued, ringing, in_progress, completed, etc.)
    - outcome: Filter by call outcome (appointment_scheduled, message_taken, etc.)
    - direction: Filter by call direction (inbound, outbound)
    - date_from/date_to: Filter by date range
    - search: Search in caller name, phone, or summary

    Results sorted by creation date (newest first).
    """
    service = _get_call_service(db)

    call_filter = CallFilter(
        agent_id=agent_id,
        company_id=company_id,
        status=status,
        outcome=outcome,
        direction=direction,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    calls, total = await service.list_calls(
        user_id=current_user.id,
        call_filter=call_filter,
        skip=skip,
        limit=limit,
    )

    return CallListResponse(
        items=calls,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/stats",
    response_model=CallStatsResponse,
    summary="Get call statistics",
    description="Get aggregated call statistics for the current user.",
)
async def get_call_stats(
    current_user: CurrentUser,
    db: Database,
    agent_id: Annotated[str | None, Query(description="Filter by agent")] = None,
    company_id: Annotated[str | None, Query(description="Filter by company")] = None,
    date_from: Annotated[datetime | None, Query(description="Filter from date")] = None,
    date_to: Annotated[datetime | None, Query(description="Filter to date")] = None,
) -> CallStatsResponse:
    """
    Get aggregated call statistics.

    Returns counts and totals for:
    - Total calls
    - Call duration
    - Billable minutes
    - Completed calls
    - Appointments scheduled
    - Messages taken
    - Leads qualified
    """
    service = _get_call_service(db)

    stats = await service.get_call_stats(
        user_id=current_user.id,
        agent_id=agent_id,
        company_id=company_id,
        date_from=date_from,
        date_to=date_to,
    )

    return CallStatsResponse(**stats)


@router.get(
    "/{call_id}",
    response_model=CallResponse,
    summary="Get call",
    description="Get a specific call by ID.",
)
async def get_call(
    call_id: str,
    current_user: CurrentUser,
    db: Database,
) -> CallResponse:
    """
    Get call details.

    Returns the call summary without the full transcript.
    Use GET /calls/{id}/transcript for the full transcript.
    """
    service = _get_call_service(db)

    try:
        call = await service.get_call(
            call_id=call_id,
            user_id=current_user.id,
        )
        return call
    except CallNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.get(
    "/{call_id}/transcript",
    response_model=TranscriptResponse,
    summary="Get call transcript",
    description="Get the full transcript for a call.",
)
async def get_call_transcript(
    call_id: str,
    current_user: CurrentUser,
    db: Database,
) -> TranscriptResponse:
    """
    Get full call transcript.

    Returns all transcript entries with:
    - Speaker (agent or caller)
    - Spoken text
    - Timestamp
    - Confidence score (if available)
    - Sentiment score (if available)
    """
    service = _get_call_service(db)

    try:
        transcript = await service.get_transcript(
            call_id=call_id,
            user_id=current_user.id,
        )
        return TranscriptResponse(
            call_id=call_id,
            transcript=transcript,
            total_entries=len(transcript),
        )
    except CallNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.get(
    "/{call_id}/recording",
    response_model=RecordingResponse,
    summary="Get call recording",
    description="Get the recording URL for a call.",
)
async def get_call_recording(
    call_id: str,
    current_user: CurrentUser,
    db: Database,
) -> RecordingResponse:
    """
    Get call recording URL.

    Returns the recording URL if available.
    Recording may not be available for:
    - Calls still in progress
    - Calls where recording was disabled
    - Calls where recording hasn't been processed yet
    """
    service = _get_call_service(db)

    try:
        call = await service.get_call_full(
            call_id=call_id,
            user_id=current_user.id,
        )

        return RecordingResponse(
            call_id=call_id,
            recording_url=call.recording_url,
            recording_duration=call.recording_duration,
            available=call.recording_url is not None,
        )
    except CallNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.post(
    "/outbound",
    response_model=CallResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Initiate outbound call",
    description="Initiate an outbound call using an agent.",
)
async def initiate_outbound_call(
    request: OutboundCallRequest,
    current_user: CurrentUser,
    db: Database,
) -> CallResponse:
    """
    Initiate an outbound call.

    - Requires an active agent
    - Checks if user has available minutes
    - Call is queued and processed asynchronously

    Note: Full implementation requires Twilio integration.
    """
    service = _get_call_service(db)

    # Check minutes available (minimum 1 minute for outbound)
    check_minutes_available(current_user, minutes_needed=1.0)

    # Determine from_number
    from_number = request.from_number
    if not from_number:
        # TODO: Get a default number from the agent's company
        from_number = "+15551234567"  # Placeholder

    try:
        call_data = CallCreate(
            agent_id=request.agent_id,
            direction=CallDirection.OUTBOUND,
            from_number=from_number,
            to_number=request.to_number,
        )

        call = await service.create_outbound_call(
            call_data=call_data,
            user_id=current_user.id,
        )

        logger.info(f"Outbound call initiated: {call.id} to {request.to_number}")

        # TODO: Trigger actual Twilio call via Celery task

        return call
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )
    except AgentNotActiveError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": e.message, "code": e.code},
        )


@router.put(
    "/{call_id}/notes",
    response_model=CallResponse,
    summary="Update call notes",
    description="Update internal notes for a call.",
)
async def update_call_notes(
    call_id: str,
    request: UpdateNotesRequest,
    current_user: CurrentUser,
    db: Database,
) -> CallResponse:
    """
    Update call internal notes.

    Notes are for internal reference and not visible to callers.
    """
    service = _get_call_service(db)

    try:
        call = await service.update_call_notes(
            call_id=call_id,
            notes=request.notes,
            user_id=current_user.id,
        )

        logger.info(f"Call notes updated: {call_id}")

        return call
    except CallNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.put(
    "/{call_id}/tags",
    response_model=CallResponse,
    summary="Update call tags",
    description="Update tags for a call.",
)
async def update_call_tags(
    call_id: str,
    request: UpdateTagsRequest,
    current_user: CurrentUser,
    db: Database,
) -> CallResponse:
    """
    Update call tags.

    Tags can be used for categorization and filtering.
    """
    service = _get_call_service(db)

    try:
        call = await service.update_call_tags(
            call_id=call_id,
            tags=request.tags,
            user_id=current_user.id,
        )

        logger.info(f"Call tags updated: {call_id}")

        return call
    except CallNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )
