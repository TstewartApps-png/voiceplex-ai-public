"""
Call service handling call CRUD operations and filtering.

Tracks all call data including transcripts, actions, and outcomes.
Supports filtering by agent, date range, status, and outcome.
"""

import logging
from datetime import datetime
from typing import Tuple

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.call import (
    Call,
    CallCreate,
    CallResponse,
    CallStatus,
    CallOutcome,
    CallDirection,
    Caller,
    TranscriptEntry,
    SentimentAnalysis,
    CallAction,
    Appointment,
    Message,
    Lead,
)

logger = logging.getLogger(__name__)


class CallServiceError(Exception):
    """Base exception for call service errors."""

    def __init__(self, message: str, code: str):
        self.message = message
        self.code = code
        super().__init__(message)


class CallNotFoundError(CallServiceError):
    """Raised when call is not found."""

    def __init__(self, call_id: str):
        super().__init__(
            message=f"Call not found: {call_id}",
            code="CALL_NOT_FOUND",
        )


class AgentNotFoundError(CallServiceError):
    """Raised when agent is not found for call creation."""

    def __init__(self, agent_id: str):
        super().__init__(
            message=f"Agent not found: {agent_id}",
            code="AGENT_NOT_FOUND",
        )


class AgentNotActiveError(CallServiceError):
    """Raised when agent is not active for outbound call."""

    def __init__(self, agent_id: str):
        super().__init__(
            message=f"Agent is not active: {agent_id}",
            code="AGENT_NOT_ACTIVE",
        )


class CallFilter:
    """Filter parameters for call queries."""

    def __init__(
        self,
        agent_id: str | None = None,
        company_id: str | None = None,
        status: CallStatus | None = None,
        outcome: CallOutcome | None = None,
        direction: CallDirection | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
    ):
        self.agent_id = agent_id
        self.company_id = company_id
        self.status = status
        self.outcome = outcome
        self.direction = direction
        self.date_from = date_from
        self.date_to = date_to
        self.search = search

    def to_query(self, user_id: str) -> dict:
        """
        Convert filter to MongoDB query.

        Args:
            user_id: Owner user ID (always required for tenant isolation)

        Returns:
            MongoDB query dict
        """
        query: dict = {"user_id": user_id}

        if self.agent_id:
            query["agent_id"] = self.agent_id
        if self.company_id:
            query["company_id"] = self.company_id
        if self.status:
            query["status"] = self.status.value
        if self.outcome:
            query["outcome"] = self.outcome.value
        if self.direction:
            query["direction"] = self.direction.value

        # Date range filter
        if self.date_from or self.date_to:
            date_query = {}
            if self.date_from:
                date_query["$gte"] = self.date_from
            if self.date_to:
                date_query["$lte"] = self.date_to
            query["created_at"] = date_query

        # Search in caller info or summary
        if self.search:
            query["$or"] = [
                {"caller.name": {"$regex": self.search, "$options": "i"}},
                {"caller.phone": {"$regex": self.search, "$options": "i"}},
                {"summary": {"$regex": self.search, "$options": "i"}},
            ]

        return query


class CallService:
    """Service for call operations."""

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize call service.

        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.collection = db["calls"]
        self.agents_collection = db["agents"]

    async def list_calls(
        self,
        user_id: str,
        call_filter: CallFilter | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[list[CallResponse], int]:
        """
        List calls for a user with optional filtering.

        Args:
            user_id: Owner user ID
            call_filter: Optional filter parameters
            skip: Number of records to skip
            limit: Maximum records to return

        Returns:
            Tuple of (calls list, total count)
        """
        if call_filter:
            query = call_filter.to_query(user_id)
        else:
            query = {"user_id": user_id}

        # Get total count
        total = await self.collection.count_documents(query)

        # Get paginated results
        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        calls = await cursor.to_list(length=limit)

        return [CallResponse.model_validate(c) for c in calls], total

    async def get_call(
        self,
        call_id: str,
        user_id: str,
    ) -> CallResponse:
        """
        Get a call by ID.

        Args:
            call_id: Call ID
            user_id: Owner user ID (for access control)

        Returns:
            Call response

        Raises:
            CallNotFoundError: If call not found or access denied
        """
        if not ObjectId.is_valid(call_id):
            raise CallNotFoundError(call_id)

        call = await self.collection.find_one({
            "_id": ObjectId(call_id),
            "user_id": user_id,
        })

        if not call:
            raise CallNotFoundError(call_id)

        return CallResponse.model_validate(call)

    async def get_call_full(
        self,
        call_id: str,
        user_id: str,
    ) -> Call:
        """
        Get full call details including transcript.

        Args:
            call_id: Call ID
            user_id: Owner user ID

        Returns:
            Full call object
        """
        if not ObjectId.is_valid(call_id):
            raise CallNotFoundError(call_id)

        call = await self.collection.find_one({
            "_id": ObjectId(call_id),
            "user_id": user_id,
        })

        if not call:
            raise CallNotFoundError(call_id)

        return Call.model_validate(call)

    async def get_transcript(
        self,
        call_id: str,
        user_id: str,
    ) -> list[TranscriptEntry]:
        """
        Get call transcript.

        Args:
            call_id: Call ID
            user_id: Owner user ID

        Returns:
            List of transcript entries
        """
        call = await self.get_call_full(call_id, user_id)
        return call.transcript

    async def get_recording_url(
        self,
        call_id: str,
        user_id: str,
    ) -> str | None:
        """
        Get call recording URL.

        Args:
            call_id: Call ID
            user_id: Owner user ID

        Returns:
            Recording URL or None if not available
        """
        call = await self.get_call_full(call_id, user_id)
        return call.recording_url

    async def create_outbound_call(
        self,
        call_data: CallCreate,
        user_id: str,
    ) -> CallResponse:
        """
        Create a new outbound call.

        Args:
            call_data: Call creation data
            user_id: Owner user ID

        Returns:
            Created call response

        Raises:
            AgentNotFoundError: If agent doesn't exist
            AgentNotActiveError: If agent is not active
        """
        # Verify agent exists and belongs to user
        if not ObjectId.is_valid(call_data.agent_id):
            raise AgentNotFoundError(call_data.agent_id)

        agent = await self.agents_collection.find_one({
            "_id": ObjectId(call_data.agent_id),
            "user_id": user_id,
        })

        if not agent:
            raise AgentNotFoundError(call_data.agent_id)

        if agent["status"] != "active":
            raise AgentNotActiveError(call_data.agent_id)

        now = datetime.utcnow()

        call_doc = {
            "agent_id": call_data.agent_id,
            "company_id": agent["company_id"],
            "user_id": user_id,
            "direction": CallDirection.OUTBOUND.value,
            "from_number": call_data.from_number,
            "to_number": call_data.to_number,
            "status": CallStatus.QUEUED.value,
            "initiated_at": now,
            "answered_at": None,
            "ended_at": None,
            "duration_seconds": 0,
            "caller": Caller(phone=call_data.to_number).model_dump(),
            "transcript": [],
            "summary": None,
            "outcome": None,
            "sentiment_analysis": SentimentAnalysis().model_dump(),
            "actions": [],
            "appointment": None,
            "message": None,
            "lead": None,
            "recording_url": None,
            "recording_duration": None,
            "billable_minutes": 0.0,
            "cost_cents": 0,
            "tags": [],
            "internal_notes": None,
            "twilio_call_sid": None,
            "twilio_recording_sid": None,
            "created_at": now,
            "updated_at": now,
        }

        result = await self.collection.insert_one(call_doc)
        call_doc["_id"] = result.inserted_id

        logger.info(f"Outbound call created: {result.inserted_id} to {call_data.to_number}")

        return CallResponse.model_validate(call_doc)

    async def create_inbound_call(
        self,
        agent_id: str,
        company_id: str,
        user_id: str,
        from_number: str,
        to_number: str,
        twilio_call_sid: str,
    ) -> Call:
        """
        Create a new inbound call (internal use for webhooks).

        Args:
            agent_id: Agent handling the call
            company_id: Company receiving the call
            user_id: Owner user ID
            from_number: Caller's phone number
            to_number: Called phone number
            twilio_call_sid: Twilio call SID

        Returns:
            Created call object
        """
        now = datetime.utcnow()

        call_doc = {
            "agent_id": agent_id,
            "company_id": company_id,
            "user_id": user_id,
            "direction": CallDirection.INBOUND.value,
            "from_number": from_number,
            "to_number": to_number,
            "status": CallStatus.RINGING.value,
            "twilio_call_sid": twilio_call_sid,
            "initiated_at": now,
            "answered_at": None,
            "ended_at": None,
            "duration_seconds": 0,
            "caller": Caller(phone=from_number).model_dump(),
            "transcript": [],
            "summary": None,
            "outcome": None,
            "sentiment_analysis": SentimentAnalysis().model_dump(),
            "actions": [],
            "appointment": None,
            "message": None,
            "lead": None,
            "recording_url": None,
            "recording_duration": None,
            "billable_minutes": 0.0,
            "cost_cents": 0,
            "tags": [],
            "internal_notes": None,
            "twilio_recording_sid": None,
            "created_at": now,
            "updated_at": now,
        }

        result = await self.collection.insert_one(call_doc)
        call_doc["_id"] = result.inserted_id

        logger.info(f"Inbound call created: {result.inserted_id} from {from_number}")

        return Call.model_validate(call_doc)

    async def update_call_notes(
        self,
        call_id: str,
        notes: str,
        user_id: str,
    ) -> CallResponse:
        """
        Update call internal notes.

        Args:
            call_id: Call ID
            notes: New notes content
            user_id: Owner user ID

        Returns:
            Updated call response
        """
        if not ObjectId.is_valid(call_id):
            raise CallNotFoundError(call_id)

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(call_id), "user_id": user_id},
            {
                "$set": {
                    "internal_notes": notes,
                    "updated_at": datetime.utcnow(),
                },
            },
            return_document=True,
        )

        if not result:
            raise CallNotFoundError(call_id)

        logger.info(f"Call notes updated: {call_id}")

        return CallResponse.model_validate(result)

    async def update_call_tags(
        self,
        call_id: str,
        tags: list[str],
        user_id: str,
    ) -> CallResponse:
        """
        Update call tags.

        Args:
            call_id: Call ID
            tags: New tags list
            user_id: Owner user ID

        Returns:
            Updated call response
        """
        if not ObjectId.is_valid(call_id):
            raise CallNotFoundError(call_id)

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(call_id), "user_id": user_id},
            {
                "$set": {
                    "tags": tags,
                    "updated_at": datetime.utcnow(),
                },
            },
            return_document=True,
        )

        if not result:
            raise CallNotFoundError(call_id)

        logger.info(f"Call tags updated: {call_id}")

        return CallResponse.model_validate(result)

    async def update_call_status(
        self,
        call_id: str,
        status: CallStatus,
        **additional_fields,
    ) -> Call:
        """
        Update call status (internal use).

        Args:
            call_id: Call ID
            status: New status
            **additional_fields: Additional fields to update

        Returns:
            Updated call object
        """
        if not ObjectId.is_valid(call_id):
            raise CallNotFoundError(call_id)

        update_fields = {
            "status": status.value,
            "updated_at": datetime.utcnow(),
            **additional_fields,
        }

        if status == CallStatus.IN_PROGRESS and "answered_at" not in additional_fields:
            update_fields["answered_at"] = datetime.utcnow()
        elif status == CallStatus.COMPLETED and "ended_at" not in additional_fields:
            update_fields["ended_at"] = datetime.utcnow()

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(call_id)},
            {"$set": update_fields},
            return_document=True,
        )

        if not result:
            raise CallNotFoundError(call_id)

        return Call.model_validate(result)

    async def add_transcript_entry(
        self,
        call_id: str,
        speaker: str,
        text: str,
        confidence: float | None = None,
        sentiment: float | None = None,
    ) -> None:
        """
        Add a transcript entry to a call (internal use).

        Args:
            call_id: Call ID
            speaker: Speaker identifier (agent or caller)
            text: Spoken text
            confidence: Optional STT confidence score
            sentiment: Optional sentiment score
        """
        if not ObjectId.is_valid(call_id):
            return

        entry = TranscriptEntry(
            _id=str(ObjectId()),
            speaker=speaker,
            text=text,
            timestamp=datetime.utcnow(),
            confidence=confidence,
            sentiment=sentiment,
        )

        await self.collection.update_one(
            {"_id": ObjectId(call_id)},
            {
                "$push": {"transcript": entry.model_dump(by_alias=True)},
                "$set": {"updated_at": datetime.utcnow()},
            },
        )

    async def add_call_action(
        self,
        call_id: str,
        action_type: str,
        details: dict,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """
        Add an action to a call (internal use).

        Args:
            call_id: Call ID
            action_type: Type of action (tool name)
            details: Action details
            success: Whether action succeeded
            error: Error message if failed
        """
        if not ObjectId.is_valid(call_id):
            return

        action = CallAction(
            type=action_type,
            timestamp=datetime.utcnow(),
            details=details,
            success=success,
            error=error,
        )

        await self.collection.update_one(
            {"_id": ObjectId(call_id)},
            {
                "$push": {"actions": action.model_dump()},
                "$set": {"updated_at": datetime.utcnow()},
            },
        )

    async def finalize_call(
        self,
        call_id: str,
        outcome: CallOutcome,
        summary: str | None = None,
        duration_seconds: int = 0,
        billable_minutes: float = 0.0,
        appointment: Appointment | None = None,
        message: Message | None = None,
        lead: Lead | None = None,
        sentiment_analysis: SentimentAnalysis | None = None,
    ) -> Call:
        """
        Finalize a completed call (internal use).

        Args:
            call_id: Call ID
            outcome: Call outcome
            summary: Call summary
            duration_seconds: Call duration
            billable_minutes: Billable minutes
            appointment: Scheduled appointment if any
            message: Message taken if any
            lead: Lead info if any
            sentiment_analysis: Sentiment analysis results

        Returns:
            Updated call object
        """
        if not ObjectId.is_valid(call_id):
            raise CallNotFoundError(call_id)

        update_fields: dict = {
            "status": CallStatus.COMPLETED.value,
            "outcome": outcome.value,
            "ended_at": datetime.utcnow(),
            "duration_seconds": duration_seconds,
            "billable_minutes": billable_minutes,
            "updated_at": datetime.utcnow(),
        }

        if summary:
            update_fields["summary"] = summary
        if appointment:
            update_fields["appointment"] = appointment.model_dump()
        if message:
            update_fields["message"] = message.model_dump()
        if lead:
            update_fields["lead"] = lead.model_dump()
        if sentiment_analysis:
            update_fields["sentiment_analysis"] = sentiment_analysis.model_dump()

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(call_id)},
            {"$set": update_fields},
            return_document=True,
        )

        if not result:
            raise CallNotFoundError(call_id)

        logger.info(f"Call finalized: {call_id} with outcome {outcome.value}")

        return Call.model_validate(result)

    async def get_call_by_twilio_sid(self, twilio_call_sid: str) -> Call | None:
        """
        Get call by Twilio call SID.

        Args:
            twilio_call_sid: Twilio call SID

        Returns:
            Call if found, None otherwise
        """
        call = await self.collection.find_one({"twilio_call_sid": twilio_call_sid})

        if not call:
            return None

        return Call.model_validate(call)

    async def count_calls(
        self,
        user_id: str,
        agent_id: str | None = None,
        company_id: str | None = None,
    ) -> int:
        """
        Count calls for a user.

        Args:
            user_id: Owner user ID
            agent_id: Optional agent filter
            company_id: Optional company filter

        Returns:
            Number of calls
        """
        query: dict = {"user_id": user_id}
        if agent_id:
            query["agent_id"] = agent_id
        if company_id:
            query["company_id"] = company_id

        return await self.collection.count_documents(query)

    async def get_call_stats(
        self,
        user_id: str,
        agent_id: str | None = None,
        company_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict:
        """
        Get aggregated call statistics.

        Args:
            user_id: Owner user ID
            agent_id: Optional agent filter
            company_id: Optional company filter
            date_from: Optional start date
            date_to: Optional end date

        Returns:
            Statistics dict
        """
        match_stage: dict = {"user_id": user_id}
        if agent_id:
            match_stage["agent_id"] = agent_id
        if company_id:
            match_stage["company_id"] = company_id
        if date_from or date_to:
            date_query = {}
            if date_from:
                date_query["$gte"] = date_from
            if date_to:
                date_query["$lte"] = date_to
            match_stage["created_at"] = date_query

        pipeline = [
            {"$match": match_stage},
            {
                "$group": {
                    "_id": None,
                    "total_calls": {"$sum": 1},
                    "total_duration_seconds": {"$sum": "$duration_seconds"},
                    "total_billable_minutes": {"$sum": "$billable_minutes"},
                    "avg_duration_seconds": {"$avg": "$duration_seconds"},
                    "completed_calls": {
                        "$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}
                    },
                    "appointments_scheduled": {
                        "$sum": {"$cond": [{"$eq": ["$outcome", "appointment_scheduled"]}, 1, 0]}
                    },
                    "messages_taken": {
                        "$sum": {"$cond": [{"$eq": ["$outcome", "message_taken"]}, 1, 0]}
                    },
                    "leads_qualified": {
                        "$sum": {"$cond": [{"$eq": ["$outcome", "lead_qualified"]}, 1, 0]}
                    },
                }
            },
        ]

        result = await self.collection.aggregate(pipeline).to_list(length=1)

        if not result:
            return {
                "total_calls": 0,
                "total_duration_seconds": 0,
                "total_billable_minutes": 0.0,
                "avg_duration_seconds": 0.0,
                "completed_calls": 0,
                "appointments_scheduled": 0,
                "messages_taken": 0,
                "leads_qualified": 0,
            }

        stats = result[0]
        del stats["_id"]
        return stats
