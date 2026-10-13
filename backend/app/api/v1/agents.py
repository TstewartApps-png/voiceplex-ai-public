"""
Agents API endpoints.

API endpoints:
- GET    /api/v1/agents
- POST   /api/v1/agents
- GET    /api/v1/agents/{id}
- PUT    /api/v1/agents/{id}
- DELETE /api/v1/agents/{id}
- POST   /api/v1/agents/{id}/activate
- POST   /api/v1/agents/{id}/pause
- POST   /api/v1/agents/{id}/test-call
- GET    /api/v1/agents/{id}/analytics
- POST   /api/v1/agents/{id}/knowledge
- DELETE /api/v1/agents/{id}/knowledge/{item_id}
"""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Database, check_subscription_limit
from app.models.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentStatus,
    AgentAnalytics,
    KnowledgeItem,
    KnowledgeItemType,
)
from app.services.agent_service import (
    AgentService,
    AgentNotFoundError,
    CompanyNotFoundError,
    KnowledgeItemNotFoundError,
)
from app.services.credentials import CredentialResolver
from app.services.ai.claude_client import ClaudeClient, ClaudeClientError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["Agents"])


# Response models
class AgentListResponse(BaseModel):
    """Paginated agent list response."""

    items: list[AgentResponse] = Field(..., description="List of agents")
    total: int = Field(..., description="Total number of agents")
    skip: int = Field(..., description="Number skipped")
    limit: int = Field(..., description="Maximum returned")


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str = Field(..., description="Response message")


class TestCallRequest(BaseModel):
    """Request model for initiating a test call."""

    to_number: str = Field(..., description="Phone number to call for test")


class TestCallResponse(BaseModel):
    """Response for test call initiation."""

    call_id: str = Field(..., description="Call ID for the test call")
    status: str = Field(..., description="Call status")
    message: str = Field(..., description="Status message")


class KnowledgeItemCreate(BaseModel):
    """Request model for creating a knowledge item."""

    type: KnowledgeItemType = Field(..., description="Type of knowledge item")
    title: str = Field(..., min_length=1, max_length=200, description="Item title")
    content: str = Field(..., min_length=1, description="Item content")
    source_url: str | None = Field(default=None, description="Source URL if applicable")


class GeneratePromptRequest(BaseModel):
    """Request model for AI prompt generation."""

    agent_type: str = Field(..., description="Type of agent (receptionist, scheduler, reminder, qualifier)")
    business_description: str = Field(..., min_length=10, max_length=2000, description="Description of the business and agent purpose")
    company_name: str | None = Field(default=None, description="Company name to include")
    additional_context: str | None = Field(default=None, description="Additional context or requirements")


class GeneratePromptResponse(BaseModel):
    """Response for AI prompt generation."""

    prompt: str = Field(..., description="Generated system prompt")
    variables: list[str] = Field(default_factory=list, description="Variables used in the prompt")


def _get_agent_service(db: Database) -> AgentService:
    """Get agent service instance."""
    return AgentService(db)


@router.get(
    "",
    response_model=AgentListResponse,
    summary="List agents",
    description="Get all agents for the current user with optional filtering.",
)
async def list_agents(
    current_user: CurrentUser,
    db: Database,
    company_id: Annotated[str | None, Query(description="Filter by company")] = None,
    status: Annotated[AgentStatus | None, Query(description="Filter by status")] = None,
    skip: Annotated[int, Query(ge=0, description="Records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records")] = 50,
) -> AgentListResponse:
    """
    List agents for the current user.

    - Supports filtering by company_id and status
    - Supports pagination with skip/limit
    - Results sorted by creation date (newest first)
    """
    service = _get_agent_service(db)
    agents, total = await service.list_agents(
        user_id=current_user.id,
        company_id=company_id,
        status=status,
        skip=skip,
        limit=limit,
    )

    return AgentListResponse(
        items=agents,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create agent",
    description="Create a new agent for a company.",
)
async def create_agent(
    agent_data: AgentCreate,
    current_user: CurrentUser,
    db: Database,
) -> AgentResponse:
    """
    Create a new agent.

    - Agent is created in DRAFT status
    - Must specify a valid company_id owned by the user
    - Checks subscription limit for agents
    """
    service = _get_agent_service(db)

    # Check subscription limit
    current_count = await service.count_agents(current_user.id)
    check_subscription_limit(current_user, "agents", current_count)

    try:
        agent = await service.create_agent(
            agent_data=agent_data,
            user_id=current_user.id,
        )

        logger.info(f"Agent created: {agent.id} for company {agent_data.company_id}")

        return agent
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.post(
    "/generate-prompt",
    response_model=GeneratePromptResponse,
    summary="Generate agent prompt",
    description="Use AI to generate a system prompt based on business description.",
)
async def generate_prompt(
    request: GeneratePromptRequest,
    current_user: CurrentUser,
    db: Database,
) -> GeneratePromptResponse:
    """
    Generate a system prompt using AI.

    - Uses Claude to create a customized prompt
    - Tailored to the agent type and business description
    - Returns variables found in the prompt
    - Uses the Anthropic key saved in Settings (falls back to ANTHROPIC_API_KEY)
    """
    api_key = await CredentialResolver(db).anthropic_api_key(current_user.id)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "detail": "Anthropic API key not configured. Add it under Settings > Anthropic.",
                "code": "AI_NOT_CONFIGURED",
            },
        )
    claude = ClaudeClient(api_key=api_key)

    agent_type_descriptions = {
        "receptionist": "a professional virtual receptionist that answers calls, routes inquiries, and takes messages",
        "scheduler": "an appointment scheduling assistant that books, reschedules, and manages calendar appointments",
        "reminder": "an outbound calling agent that reminds customers of upcoming appointments",
        "qualifier": "a lead qualification specialist that captures and scores potential customers",
    }

    agent_desc = agent_type_descriptions.get(request.agent_type, "a helpful voice assistant")

    system_prompt = """You are an expert at writing system prompts for AI voice agents.
Create a comprehensive, professional system prompt for a voice agent.

Guidelines:
- Keep instructions clear and actionable
- Include specific behaviors and responses
- Use variables like {{company_name}}, {{agent_name}}, {{business_hours}} where appropriate
- Keep voice responses short (1-2 sentences typically)
- Include error handling guidance
- Be conversational, not robotic

Output ONLY the system prompt text, no explanations or markdown formatting."""

    user_message = f"""Create a system prompt for {agent_desc}.

Business: {request.business_description}
{f"Company Name: {request.company_name}" if request.company_name else ""}
{f"Additional Requirements: {request.additional_context}" if request.additional_context else ""}

Generate a complete system prompt that this agent should follow."""

    try:
        response = await claude.create_message(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            max_tokens=2000,
            use_fallback=True,  # Use Sonnet for better quality
        )

        prompt = response.content.strip()

        # Extract variables from the prompt
        import re
        variables = list(set(re.findall(r'\{\{(\w+)\}\}', prompt)))

        logger.info(f"Generated prompt for user {current_user.id}, type: {request.agent_type}")

        return GeneratePromptResponse(
            prompt=prompt,
            variables=variables,
        )

    except ClaudeClientError as e:
        logger.error(f"Claude error generating prompt: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": str(e.message), "code": e.code},
        )


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Get agent",
    description="Get a specific agent by ID.",
)
async def get_agent(
    agent_id: str,
    current_user: CurrentUser,
    db: Database,
) -> AgentResponse:
    """
    Get agent details.

    - Returns 404 if agent not found or user doesn't have access
    """
    service = _get_agent_service(db)

    try:
        agent = await service.get_agent(
            agent_id=agent_id,
            user_id=current_user.id,
        )
        return agent
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.put(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Update agent",
    description="Update an agent's configuration.",
)
async def update_agent(
    agent_id: str,
    agent_data: AgentUpdate,
    current_user: CurrentUser,
    db: Database,
) -> AgentResponse:
    """
    Update agent details.

    - Only updates provided fields
    - Can update name, type, status, voice, persona, capabilities, etc.
    """
    service = _get_agent_service(db)

    try:
        agent = await service.update_agent(
            agent_id=agent_id,
            agent_data=agent_data,
            user_id=current_user.id,
        )

        logger.info(f"Agent updated: {agent_id}")

        return agent
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.delete(
    "/{agent_id}",
    response_model=MessageResponse,
    summary="Delete agent",
    description="Delete an agent.",
)
async def delete_agent(
    agent_id: str,
    current_user: CurrentUser,
    db: Database,
) -> MessageResponse:
    """
    Delete an agent.

    - Unassigns agent from any phone numbers
    - Call history is preserved
    """
    service = _get_agent_service(db)

    try:
        await service.delete_agent(
            agent_id=agent_id,
            user_id=current_user.id,
        )

        logger.info(f"Agent deleted: {agent_id}")

        return MessageResponse(message="Agent deleted successfully")
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.post(
    "/{agent_id}/activate",
    response_model=AgentResponse,
    summary="Activate agent",
    description="Activate an agent to start handling calls.",
)
async def activate_agent(
    agent_id: str,
    current_user: CurrentUser,
    db: Database,
) -> AgentResponse:
    """
    Activate an agent.

    - Changes status from DRAFT or PAUSED to ACTIVE
    - Agent will start handling assigned phone number calls
    """
    service = _get_agent_service(db)

    try:
        agent = await service.activate_agent(
            agent_id=agent_id,
            user_id=current_user.id,
        )

        logger.info(f"Agent activated: {agent_id}")

        return agent
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.post(
    "/{agent_id}/pause",
    response_model=AgentResponse,
    summary="Pause agent",
    description="Pause an agent to stop handling calls.",
)
async def pause_agent(
    agent_id: str,
    current_user: CurrentUser,
    db: Database,
) -> AgentResponse:
    """
    Pause an agent.

    - Changes status to PAUSED
    - Agent will stop handling calls
    - Existing calls in progress will continue
    """
    service = _get_agent_service(db)

    try:
        agent = await service.pause_agent(
            agent_id=agent_id,
            user_id=current_user.id,
        )

        logger.info(f"Agent paused: {agent_id}")

        return agent
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.post(
    "/{agent_id}/test-call",
    response_model=TestCallResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Initiate test call",
    description="Initiate a test call with the agent.",
)
async def initiate_test_call(
    agent_id: str,
    request: TestCallRequest,
    current_user: CurrentUser,
    db: Database,
) -> TestCallResponse:
    """
    Initiate a test call.

    - Creates an outbound call to the specified number
    - Uses the agent's configuration
    - Requires agent to be ACTIVE

    Note: Full implementation requires Twilio integration.
    """
    service = _get_agent_service(db)

    try:
        agent = await service.get_agent(
            agent_id=agent_id,
            user_id=current_user.id,
        )

        if agent.status != AgentStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "detail": "Agent must be active to initiate test calls",
                    "code": "AGENT_NOT_ACTIVE",
                },
            )

        # TODO: Integrate with Twilio to initiate actual call
        # For now, return placeholder response
        import random
        mock_call_id = f"call_{random.randint(100000, 999999)}"

        logger.info(f"Test call initiated for agent {agent_id} to {request.to_number}")

        return TestCallResponse(
            call_id=mock_call_id,
            status="queued",
            message=f"Test call queued to {request.to_number}. Full Twilio integration pending.",
        )
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.get(
    "/{agent_id}/analytics",
    response_model=AgentAnalytics,
    summary="Get agent analytics",
    description="Get performance analytics for an agent.",
)
async def get_agent_analytics(
    agent_id: str,
    current_user: CurrentUser,
    db: Database,
) -> AgentAnalytics:
    """
    Get agent analytics.

    Returns aggregated statistics:
    - Total calls handled
    - Total call minutes
    - Average call duration
    - Appointments booked
    - Messages taken
    - Transfers made
    - Satisfaction score (if available)
    """
    service = _get_agent_service(db)

    try:
        analytics = await service.get_agent_analytics(
            agent_id=agent_id,
            user_id=current_user.id,
        )
        return analytics
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.post(
    "/{agent_id}/knowledge",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add knowledge item",
    description="Add a knowledge base item to the agent.",
)
async def add_knowledge_item(
    agent_id: str,
    item_data: KnowledgeItemCreate,
    current_user: CurrentUser,
    db: Database,
) -> AgentResponse:
    """
    Add a knowledge base item.

    Knowledge items provide context for the agent:
    - FAQ: Common questions and answers
    - Document: Uploaded document content
    - Website: Scraped website content

    Checks subscription limit for knowledge items per agent.
    """
    service = _get_agent_service(db)

    # Get current agent to check knowledge base count
    try:
        agent = await service.get_agent(agent_id, current_user.id)
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )

    # Check subscription limit
    check_subscription_limit(
        current_user, "knowledge_items", len(agent.knowledge_base)
    )

    try:
        updated_agent = await service.add_knowledge_item(
            agent_id=agent_id,
            user_id=current_user.id,
            item_type=item_data.type,
            title=item_data.title,
            content=item_data.content,
            source_url=item_data.source_url,
        )

        logger.info(f"Knowledge item added to agent {agent_id}: {item_data.title}")

        return updated_agent
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.delete(
    "/{agent_id}/knowledge/{item_id}",
    response_model=AgentResponse,
    summary="Remove knowledge item",
    description="Remove a knowledge base item from the agent.",
)
async def remove_knowledge_item(
    agent_id: str,
    item_id: str,
    current_user: CurrentUser,
    db: Database,
) -> AgentResponse:
    """
    Remove a knowledge base item.
    """
    service = _get_agent_service(db)

    try:
        agent = await service.remove_knowledge_item(
            agent_id=agent_id,
            item_id=item_id,
            user_id=current_user.id,
        )

        logger.info(f"Knowledge item removed from agent {agent_id}: {item_id}")

        return agent
    except AgentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )
    except KnowledgeItemNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )
