"""
Knowledge base tools for searching agent knowledge.

These tools allow Claude to search the agent's knowledge base
for relevant information to answer caller questions.
"""

import logging
from datetime import datetime
from typing import Any

from app.services.ai.tools.base import (
    BaseTool,
    ToolCategory,
    ToolParameter,
    ToolResult,
    ToolContext,
    register_tool,
)

logger = logging.getLogger(__name__)


class SearchKnowledgeTool(BaseTool):
    """
    Search the agent's knowledge base for relevant information.

    This tool allows the AI to find answers to caller questions
    from FAQs, documents, and other knowledge sources.
    """

    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return (
            "Search the knowledge base for information to answer a question. "
            "Use this when you need to find specific information about the business, "
            "services, policies, or commonly asked questions. "
            "Returns the most relevant knowledge items."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.KNOWLEDGE

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="The question or topic to search for",
                required=True,
            ),
            ToolParameter(
                name="category",
                type="string",
                description="Optional category to filter by (faq, document, website)",
                required=False,
                enum=["faq", "document", "website"],
            ),
            ToolParameter(
                name="max_results",
                type="integer",
                description="Maximum number of results to return",
                required=False,
                default=3,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        query: str,
        category: str | None = None,
        max_results: int = 3,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Search the knowledge base.

        In production, this would:
        1. Get agent's knowledge base from database
        2. Generate embedding for query
        3. Perform vector similarity search
        4. Return top matching results
        """
        logger.info(
            f"Searching knowledge for agent {context.agent_id}: "
            f"query='{query}', category={category}"
        )

        try:
            # TODO: Implement actual vector search in production
            # For now, return mock results based on common questions

            # Mock knowledge base for demonstration
            mock_knowledge = [
                {
                    "type": "faq",
                    "title": "Business Hours",
                    "content": "We are open Monday through Friday, 9 AM to 5 PM Eastern Time. We are closed on weekends and major holidays.",
                    "keywords": ["hours", "open", "closed", "time", "when"],
                },
                {
                    "type": "faq",
                    "title": "Location",
                    "content": "We are located at 123 Main Street, Suite 100, in downtown. Free parking is available in the lot behind the building.",
                    "keywords": ["where", "location", "address", "parking", "directions"],
                },
                {
                    "type": "faq",
                    "title": "Appointment Cancellation",
                    "content": "You can cancel or reschedule your appointment up to 24 hours before without any fee. Late cancellations may incur a $25 fee.",
                    "keywords": ["cancel", "reschedule", "fee", "policy"],
                },
                {
                    "type": "faq",
                    "title": "Payment Methods",
                    "content": "We accept all major credit cards, cash, and checks. Payment is due at the time of service.",
                    "keywords": ["pay", "payment", "credit card", "cash", "cost"],
                },
                {
                    "type": "faq",
                    "title": "Contact Information",
                    "content": "You can reach us by phone at 555-0100, by email at info@example.com, or through our website contact form.",
                    "keywords": ["contact", "phone", "email", "reach", "call"],
                },
                {
                    "type": "document",
                    "title": "Services Offered",
                    "content": "We offer a wide range of services including consultations, assessments, follow-up appointments, and emergency visits. Each service type has different durations and pricing.",
                    "keywords": ["service", "services", "offer", "do", "provide"],
                },
                {
                    "type": "faq",
                    "title": "First Visit",
                    "content": "For your first visit, please arrive 15 minutes early to complete paperwork. Bring your ID and insurance card if applicable.",
                    "keywords": ["first", "new", "visit", "bring", "expect"],
                },
            ]

            # Simple keyword matching (in production, use embeddings)
            query_lower = query.lower()
            query_words = set(query_lower.split())

            scored_results = []
            for item in mock_knowledge:
                # Skip if category filter doesn't match
                if category and item["type"] != category:
                    continue

                # Calculate simple relevance score
                keyword_matches = sum(
                    1 for kw in item["keywords"]
                    if kw in query_lower or any(kw in w for w in query_words)
                )

                title_match = any(
                    word in item["title"].lower() for word in query_words
                )

                score = keyword_matches + (2 if title_match else 0)

                if score > 0:
                    scored_results.append((score, item))

            # Sort by score and limit results
            scored_results.sort(key=lambda x: x[0], reverse=True)
            results = [item for _, item in scored_results[:max_results]]

            if not results:
                return ToolResult(
                    success=True,
                    data={"results": [], "total": 0},
                    message="I don't have specific information about that in my knowledge base. Let me try to help you another way.",
                )

            # Format results for voice response
            if len(results) == 1:
                message = results[0]["content"]
            else:
                # Combine relevant information
                message = results[0]["content"]
                if len(results) > 1:
                    message += f" Also, {results[1]['content'].lower()}"

            return ToolResult(
                success=True,
                data={
                    "results": [
                        {"title": r["title"], "content": r["content"], "type": r["type"]}
                        for r in results
                    ],
                    "total": len(results),
                },
                message=message,
            )

        except Exception as e:
            logger.exception(f"Error searching knowledge base: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to search knowledge base: {e}",
            )


class GetBusinessInfoTool(BaseTool):
    """
    Get specific business information.
    """

    @property
    def name(self) -> str:
        return "get_business_info"

    @property
    def description(self) -> str:
        return (
            "Get specific business information like hours, location, contact details, "
            "or services offered. Use this when the caller asks about the business."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.KNOWLEDGE

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="info_type",
                type="string",
                description="Type of information to retrieve",
                required=True,
                enum=["hours", "location", "contact", "services", "policies", "about"],
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        info_type: str,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Get business information.

        In production, this retrieves from the company's settings.
        """
        logger.info(f"Getting business info: {info_type}")

        try:
            # TODO: Get from company settings in database
            # For now, return mock data

            info_map = {
                "hours": "We're open Monday through Friday, 9 AM to 5 PM Eastern Time. We're closed on weekends and holidays.",
                "location": "We're located at 123 Main Street, Suite 100. There's free parking behind the building.",
                "contact": "You can reach us at 555-0100 or email us at info@example.com.",
                "services": "We offer consultations, assessments, follow-up appointments, and emergency visits.",
                "policies": "Appointments can be cancelled up to 24 hours in advance without fee. Payment is due at time of service.",
                "about": "We've been serving the community since 2010. Our team of professionals is dedicated to providing excellent service.",
            }

            info = info_map.get(info_type, "I don't have that information available.")

            return ToolResult(
                success=True,
                data={"info_type": info_type, "info": info},
                message=info,
            )

        except Exception as e:
            logger.exception(f"Error getting business info: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to get information: {e}",
            )


class CheckServiceAvailabilityTool(BaseTool):
    """
    Check if a specific service is available.
    """

    @property
    def name(self) -> str:
        return "check_service_availability"

    @property
    def description(self) -> str:
        return (
            "Check if a specific service is offered and get details about it. "
            "Use this when the caller asks about a particular service."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.KNOWLEDGE

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="service_name",
                type="string",
                description="Name or description of the service to check",
                required=True,
            ),
        ]

    async def execute(
        self,
        context: ToolContext,
        service_name: str,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Check service availability.

        In production, this checks the agent's calendar_settings.services.
        """
        logger.info(f"Checking service availability: {service_name}")

        try:
            # TODO: Get from agent's calendar_settings.services
            # For now, return mock data

            mock_services = {
                "consultation": {
                    "name": "Initial Consultation",
                    "duration": 60,
                    "available": True,
                    "description": "A comprehensive initial meeting to discuss your needs.",
                },
                "follow-up": {
                    "name": "Follow-up Appointment",
                    "duration": 30,
                    "available": True,
                    "description": "A shorter follow-up to check on progress.",
                },
                "assessment": {
                    "name": "Full Assessment",
                    "duration": 90,
                    "available": True,
                    "description": "A detailed assessment of your situation.",
                },
            }

            # Simple matching
            service_lower = service_name.lower()
            matched_service = None

            for key, service in mock_services.items():
                if key in service_lower or service_lower in service["name"].lower():
                    matched_service = service
                    break

            if matched_service:
                message = (
                    f"Yes, we offer {matched_service['name']}. "
                    f"It's a {matched_service['duration']}-minute appointment. "
                    f"{matched_service['description']}"
                )
                return ToolResult(
                    success=True,
                    data={"service": matched_service, "available": True},
                    message=message,
                )
            else:
                return ToolResult(
                    success=True,
                    data={"available": False},
                    message="I'm not sure about that specific service. We offer consultations, follow-ups, and assessments. Would any of those work for you?",
                )

        except Exception as e:
            logger.exception(f"Error checking service: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to check service: {e}",
            )


def register_knowledge_tools() -> None:
    """Register all knowledge base tools."""
    register_tool(SearchKnowledgeTool())
    register_tool(GetBusinessInfoTool())
    register_tool(CheckServiceAvailabilityTool())

    logger.info("Knowledge base tools registered")
