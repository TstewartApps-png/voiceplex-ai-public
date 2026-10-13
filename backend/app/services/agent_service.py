"""
Agent service handling agent CRUD operations.

Agents handle receptionist, scheduler, reminder, qualifier use cases.
Tenant isolation via user_id and company ownership validation.
"""

import logging
from datetime import datetime
from typing import Tuple

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.agent import (
    Agent,
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentStatus,
    AgentAnalytics,
    KnowledgeItem,
    KnowledgeItemType,
    Voice,
    Persona,
    Capabilities,
    CalendarSettings,
    TransferSettings,
    ConversationSettings,
)

logger = logging.getLogger(__name__)


class AgentServiceError(Exception):
    """Base exception for agent service errors."""

    def __init__(self, message: str, code: str):
        self.message = message
        self.code = code
        super().__init__(message)


class AgentNotFoundError(AgentServiceError):
    """Raised when agent is not found."""

    def __init__(self, agent_id: str):
        super().__init__(
            message=f"Agent not found: {agent_id}",
            code="AGENT_NOT_FOUND",
        )


class CompanyNotFoundError(AgentServiceError):
    """Raised when company is not found for agent creation."""

    def __init__(self, company_id: str):
        super().__init__(
            message=f"Company not found: {company_id}",
            code="COMPANY_NOT_FOUND",
        )


class KnowledgeItemNotFoundError(AgentServiceError):
    """Raised when knowledge item is not found."""

    def __init__(self, item_id: str):
        super().__init__(
            message=f"Knowledge item not found: {item_id}",
            code="KNOWLEDGE_ITEM_NOT_FOUND",
        )


class AgentNotActiveError(AgentServiceError):
    """Raised when operation requires active agent."""

    def __init__(self, agent_id: str):
        super().__init__(
            message=f"Agent is not active: {agent_id}",
            code="AGENT_NOT_ACTIVE",
        )


class AgentService:
    """Service for agent operations."""

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize agent service.

        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.collection = db["agents"]
        self.companies_collection = db["companies"]

    async def list_agents(
        self,
        user_id: str,
        company_id: str | None = None,
        status: AgentStatus | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[list[AgentResponse], int]:
        """
        List agents for a user with optional filtering.

        Args:
            user_id: Owner user ID
            company_id: Optional company filter
            status: Optional status filter
            skip: Number of records to skip
            limit: Maximum records to return

        Returns:
            Tuple of (agents list, total count)
        """
        query: dict = {"user_id": user_id}

        if company_id:
            query["company_id"] = company_id
        if status:
            query["status"] = status.value

        # Get total count
        total = await self.collection.count_documents(query)

        # Get paginated results
        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        agents = await cursor.to_list(length=limit)

        return [AgentResponse.model_validate(a) for a in agents], total

    async def get_agent(
        self,
        agent_id: str,
        user_id: str,
    ) -> AgentResponse:
        """
        Get an agent by ID.

        Args:
            agent_id: Agent ID
            user_id: Owner user ID (for access control)

        Returns:
            Agent response

        Raises:
            AgentNotFoundError: If agent not found or access denied
        """
        if not ObjectId.is_valid(agent_id):
            raise AgentNotFoundError(agent_id)

        agent = await self.collection.find_one({
            "_id": ObjectId(agent_id),
            "user_id": user_id,
        })

        if not agent:
            raise AgentNotFoundError(agent_id)

        return AgentResponse.model_validate(agent)

    async def create_agent(
        self,
        agent_data: AgentCreate,
        user_id: str,
    ) -> AgentResponse:
        """
        Create a new agent.

        Args:
            agent_data: Agent creation data
            user_id: Owner user ID

        Returns:
            Created agent response

        Raises:
            CompanyNotFoundError: If company doesn't exist or user doesn't own it
        """
        # Verify company ownership
        if not ObjectId.is_valid(agent_data.company_id):
            raise CompanyNotFoundError(agent_data.company_id)

        company = await self.companies_collection.find_one({
            "_id": ObjectId(agent_data.company_id),
            "user_id": user_id,
        })

        if not company:
            raise CompanyNotFoundError(agent_data.company_id)

        now = datetime.utcnow()

        agent_doc = {
            "name": agent_data.name,
            "type": agent_data.type.value,
            "company_id": agent_data.company_id,
            "user_id": user_id,
            "status": AgentStatus.DRAFT.value,
            "voice": (agent_data.voice or Voice()).model_dump(),
            "persona": (agent_data.persona or Persona()).model_dump(),
            "capabilities": (agent_data.capabilities or Capabilities()).model_dump(),
            "calendar_settings": (agent_data.calendar_settings or CalendarSettings()).model_dump(),
            "transfer_settings": (agent_data.transfer_settings or TransferSettings()).model_dump(),
            "conversation_settings": (agent_data.conversation_settings or ConversationSettings()).model_dump(),
            "knowledge_base": [],
            "analytics": AgentAnalytics().model_dump(),
            "created_at": now,
            "updated_at": now,
        }

        result = await self.collection.insert_one(agent_doc)
        agent_doc["_id"] = result.inserted_id

        logger.info(f"Agent created: {result.inserted_id} for company {agent_data.company_id}")

        return AgentResponse.model_validate(agent_doc)

    async def update_agent(
        self,
        agent_id: str,
        agent_data: AgentUpdate,
        user_id: str,
    ) -> AgentResponse:
        """
        Update an agent.

        Args:
            agent_id: Agent ID
            agent_data: Update data
            user_id: Owner user ID (for access control)

        Returns:
            Updated agent response

        Raises:
            AgentNotFoundError: If agent not found or access denied
        """
        if not ObjectId.is_valid(agent_id):
            raise AgentNotFoundError(agent_id)

        # Build update document with only provided fields
        update_fields: dict = {"updated_at": datetime.utcnow()}

        if agent_data.name is not None:
            update_fields["name"] = agent_data.name
        if agent_data.type is not None:
            update_fields["type"] = agent_data.type.value
        if agent_data.status is not None:
            update_fields["status"] = agent_data.status.value
        if agent_data.voice is not None:
            update_fields["voice"] = agent_data.voice.model_dump()
        if agent_data.persona is not None:
            update_fields["persona"] = agent_data.persona.model_dump()
        if agent_data.capabilities is not None:
            update_fields["capabilities"] = agent_data.capabilities.model_dump()
        if agent_data.calendar_settings is not None:
            update_fields["calendar_settings"] = agent_data.calendar_settings.model_dump()
        if agent_data.transfer_settings is not None:
            update_fields["transfer_settings"] = agent_data.transfer_settings.model_dump()
        if agent_data.conversation_settings is not None:
            update_fields["conversation_settings"] = agent_data.conversation_settings.model_dump()

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(agent_id), "user_id": user_id},
            {"$set": update_fields},
            return_document=True,
        )

        if not result:
            raise AgentNotFoundError(agent_id)

        logger.info(f"Agent updated: {agent_id}")

        return AgentResponse.model_validate(result)

    async def delete_agent(
        self,
        agent_id: str,
        user_id: str,
    ) -> bool:
        """
        Delete an agent.

        Args:
            agent_id: Agent ID
            user_id: Owner user ID (for access control)

        Returns:
            True if deleted

        Raises:
            AgentNotFoundError: If agent not found or access denied
        """
        if not ObjectId.is_valid(agent_id):
            raise AgentNotFoundError(agent_id)

        result = await self.collection.delete_one({
            "_id": ObjectId(agent_id),
            "user_id": user_id,
        })

        if result.deleted_count == 0:
            raise AgentNotFoundError(agent_id)

        # Unassign from any phone numbers
        await self.companies_collection.update_many(
            {"phone_numbers.agent_id": agent_id},
            {"$set": {"phone_numbers.$[elem].agent_id": None}},
            array_filters=[{"elem.agent_id": agent_id}],
        )

        logger.info(f"Agent deleted: {agent_id}")

        return True

    async def activate_agent(
        self,
        agent_id: str,
        user_id: str,
    ) -> AgentResponse:
        """
        Activate an agent to start handling calls.

        Args:
            agent_id: Agent ID
            user_id: Owner user ID

        Returns:
            Updated agent response
        """
        if not ObjectId.is_valid(agent_id):
            raise AgentNotFoundError(agent_id)

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(agent_id), "user_id": user_id},
            {
                "$set": {
                    "status": AgentStatus.ACTIVE.value,
                    "updated_at": datetime.utcnow(),
                },
            },
            return_document=True,
        )

        if not result:
            raise AgentNotFoundError(agent_id)

        logger.info(f"Agent activated: {agent_id}")

        return AgentResponse.model_validate(result)

    async def pause_agent(
        self,
        agent_id: str,
        user_id: str,
    ) -> AgentResponse:
        """
        Pause an agent to stop handling calls.

        Args:
            agent_id: Agent ID
            user_id: Owner user ID

        Returns:
            Updated agent response
        """
        if not ObjectId.is_valid(agent_id):
            raise AgentNotFoundError(agent_id)

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(agent_id), "user_id": user_id},
            {
                "$set": {
                    "status": AgentStatus.PAUSED.value,
                    "updated_at": datetime.utcnow(),
                },
            },
            return_document=True,
        )

        if not result:
            raise AgentNotFoundError(agent_id)

        logger.info(f"Agent paused: {agent_id}")

        return AgentResponse.model_validate(result)

    async def get_agent_analytics(
        self,
        agent_id: str,
        user_id: str,
    ) -> AgentAnalytics:
        """
        Get analytics for an agent.

        Args:
            agent_id: Agent ID
            user_id: Owner user ID

        Returns:
            Agent analytics
        """
        agent = await self.get_agent(agent_id, user_id)
        return agent.analytics

    async def add_knowledge_item(
        self,
        agent_id: str,
        user_id: str,
        item_type: KnowledgeItemType,
        title: str,
        content: str,
        source_url: str | None = None,
    ) -> AgentResponse:
        """
        Add a knowledge base item to an agent.

        Args:
            agent_id: Agent ID
            user_id: Owner user ID
            item_type: Type of knowledge item
            title: Item title
            content: Item content
            source_url: Optional source URL

        Returns:
            Updated agent response
        """
        if not ObjectId.is_valid(agent_id):
            raise AgentNotFoundError(agent_id)

        knowledge_item = KnowledgeItem(
            _id=str(ObjectId()),
            type=item_type,
            title=title,
            content=content,
            source_url=source_url,
            created_at=datetime.utcnow(),
        )

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(agent_id), "user_id": user_id},
            {
                "$push": {"knowledge_base": knowledge_item.model_dump(by_alias=True)},
                "$set": {"updated_at": datetime.utcnow()},
            },
            return_document=True,
        )

        if not result:
            raise AgentNotFoundError(agent_id)

        logger.info(f"Knowledge item added to agent {agent_id}: {title}")

        return AgentResponse.model_validate(result)

    async def remove_knowledge_item(
        self,
        agent_id: str,
        item_id: str,
        user_id: str,
    ) -> AgentResponse:
        """
        Remove a knowledge base item from an agent.

        Args:
            agent_id: Agent ID
            item_id: Knowledge item ID
            user_id: Owner user ID

        Returns:
            Updated agent response

        Raises:
            KnowledgeItemNotFoundError: If item not found
        """
        if not ObjectId.is_valid(agent_id):
            raise AgentNotFoundError(agent_id)

        # First verify the item exists
        agent = await self.collection.find_one({
            "_id": ObjectId(agent_id),
            "user_id": user_id,
            "knowledge_base._id": item_id,
        })

        if not agent:
            # Check if agent exists but item doesn't
            exists = await self.collection.find_one({
                "_id": ObjectId(agent_id),
                "user_id": user_id,
            })
            if not exists:
                raise AgentNotFoundError(agent_id)
            raise KnowledgeItemNotFoundError(item_id)

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(agent_id), "user_id": user_id},
            {
                "$pull": {"knowledge_base": {"_id": item_id}},
                "$set": {"updated_at": datetime.utcnow()},
            },
            return_document=True,
        )

        logger.info(f"Knowledge item removed from agent {agent_id}: {item_id}")

        return AgentResponse.model_validate(result)

    async def count_agents(
        self,
        user_id: str,
        company_id: str | None = None,
    ) -> int:
        """
        Count agents for a user.

        Args:
            user_id: Owner user ID
            company_id: Optional company filter

        Returns:
            Number of agents
        """
        query: dict = {"user_id": user_id}
        if company_id:
            query["company_id"] = company_id

        return await self.collection.count_documents(query)

    async def get_agent_by_phone(self, phone_number: str) -> AgentResponse | None:
        """
        Resolve the active agent that answers a phone number (inbound routing).

        Resolution order:
          1. A company phone number explicitly assigned to an agent
             (``companies.phone_numbers[].agent_id``).
          2. The tenant whose Settings > Twilio number matches, using either the
             default ``twilio.agent_id`` they chose or, failing that, their single
             active agent.

        Args:
            phone_number: Called number in E.164 format

        Returns:
            Active agent or None
        """
        agent_id: str | None = None

        # 1. explicit company number assignment
        company = await self.companies_collection.find_one({
            "phone_numbers.number": phone_number,
            "phone_numbers.status": "active",
        })
        if company:
            for pn in company.get("phone_numbers", []):
                if pn.get("number") == phone_number and pn.get("status", "active") == "active":
                    agent_id = pn.get("agent_id")
                    break

        # 2. tenant-level Twilio number from Settings
        if not agent_id:
            tenant = await self.db["settings"].find_one(
                {"twilio.phone_number": phone_number}, {"user_id": 1, "twilio.agent_id": 1}
            )
            if tenant:
                agent_id = (tenant.get("twilio") or {}).get("agent_id")
                if not agent_id:
                    active = await self.collection.find(
                        {"user_id": tenant["user_id"], "status": AgentStatus.ACTIVE.value}
                    ).to_list(length=2)
                    if len(active) == 1:
                        agent_id = str(active[0]["_id"])
                    elif len(active) > 1:
                        logger.warning(
                            "Number %s belongs to user %s who has several active agents and no "
                            "default agent selected in Settings > Twilio",
                            phone_number, tenant["user_id"],
                        )

        if not agent_id or not ObjectId.is_valid(agent_id):
            return None

        agent = await self.collection.find_one({
            "_id": ObjectId(agent_id),
            "status": AgentStatus.ACTIVE.value,
        })
        if not agent:
            logger.warning("Agent %s assigned to %s is missing or not active", agent_id, phone_number)
            return None

        return AgentResponse.model_validate(agent)

    async def update_analytics(
        self,
        agent_id: str,
        analytics_update: dict,
    ) -> None:
        """
        Update agent analytics (internal use).

        Args:
            agent_id: Agent ID
            analytics_update: Analytics fields to update
        """
        if not ObjectId.is_valid(agent_id):
            return

        await self.collection.update_one(
            {"_id": ObjectId(agent_id)},
            {
                "$inc": analytics_update,
                "$set": {"updated_at": datetime.utcnow()},
            },
        )
