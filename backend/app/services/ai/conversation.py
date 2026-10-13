"""
Conversation Manager for multi-turn voice dialogues.

Manages conversation state, message history, context injection,
and coordinates between the Call Orchestrator and Claude API.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.models.agent import AgentResponse, AgentType
from app.services.ai.claude_client import (
    ClaudeClient,
    ClaudeResponse,
    ToolCall,
    get_claude_client,
    format_tool_result,
)
from app.services.ai.tools import (
    ToolContext,
    ToolResult,
    get_tool_registry,
    register_all_tools,
)

logger = logging.getLogger(__name__)


class ConversationRole(str, Enum):
    """Role in conversation."""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ConversationMessage:
    """A message in the conversation history."""

    role: ConversationRole
    content: str | list[dict[str, Any]]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_tool_result: bool = False


@dataclass
class ConversationContext:
    """Context for the current conversation."""

    session_id: str
    call_id: str
    agent: AgentResponse
    company_id: str
    user_id: str
    caller_phone: str | None = None
    caller_name: str | None = None
    collected_info: dict[str, Any] = field(default_factory=dict)


class ConversationManager:
    """
    Manages multi-turn conversations with Claude.

    Handles:
    - Message history with sliding window
    - System prompt generation
    - Tool selection based on agent capabilities
    - Tool execution and result handling
    - Response generation for voice
    """

    # Maximum messages to keep in history (to stay under token limits)
    MAX_HISTORY_MESSAGES = 20

    # Maximum tokens for Haiku context
    MAX_CONTEXT_TOKENS = 8000

    def __init__(
        self,
        context: ConversationContext,
        claude_client: ClaudeClient | None = None,
    ):
        """
        Initialize conversation manager.

        Args:
            context: Conversation context with agent and caller info
            claude_client: Optional custom Claude client
        """
        self.context = context
        self.claude_client = claude_client or get_claude_client()

        self._messages: list[ConversationMessage] = []
        self._system_prompt: str | None = None
        self._tools_schema: list[dict[str, Any]] | None = None

        # Ensure tools are registered
        register_all_tools()

    @property
    def message_count(self) -> int:
        """Get number of messages in history."""
        return len(self._messages)

    @property
    def system_prompt(self) -> str:
        """Get the system prompt for this conversation."""
        if self._system_prompt is None:
            self._system_prompt = self._build_system_prompt()
        return self._system_prompt

    @property
    def tools_schema(self) -> list[dict[str, Any]]:
        """Get the tools schema based on agent capabilities."""
        if self._tools_schema is None:
            self._tools_schema = self._build_tools_schema()
        return self._tools_schema

    def add_user_message(self, content: str) -> None:
        """
        Add a user (caller) message to history.

        Args:
            content: Message content
        """
        self._messages.append(ConversationMessage(
            role=ConversationRole.USER,
            content=content,
        ))
        self._trim_history()

    def add_assistant_message(self, content: str | list[dict]) -> None:
        """
        Add an assistant message to history.

        Args:
            content: Message content (string or tool use blocks)
        """
        self._messages.append(ConversationMessage(
            role=ConversationRole.ASSISTANT,
            content=content,
        ))
        self._trim_history()

    def add_tool_result(self, tool_results: list[dict]) -> None:
        """
        Add tool execution results to history.

        Args:
            tool_results: List of tool result blocks
        """
        self._messages.append(ConversationMessage(
            role=ConversationRole.USER,
            content=tool_results,
            is_tool_result=True,
        ))

    async def process_user_input(self, user_text: str) -> str:
        """
        Process user input and generate a response.

        This is the main entry point for handling caller speech.

        Args:
            user_text: Transcribed caller speech

        Returns:
            Response text for TTS
        """
        logger.info(f"Processing user input: {user_text[:100]}...")

        # Add user message to history
        self.add_user_message(user_text)

        # Get Claude response
        response = await self._get_claude_response()

        # Handle tool calls if any
        if response.tool_calls:
            return await self._handle_tool_calls(response)

        # Return text response
        return response.content

    async def _get_claude_response(self) -> ClaudeResponse:
        """
        Get response from Claude API.

        Returns:
            ClaudeResponse with content and optional tool calls
        """
        messages = self._format_messages_for_api()

        response = await self.claude_client.create_message(
            messages=messages,
            system=self.system_prompt,
            tools=self.tools_schema if self.tools_schema else None,
        )

        # Store assistant response in history
        if response.tool_calls:
            # Store as tool use blocks for proper continuation
            tool_use_blocks = [
                {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                }
                for tc in response.tool_calls
            ]
            self.add_assistant_message(tool_use_blocks)
        elif response.content:
            self.add_assistant_message(response.content)

        logger.debug(
            f"Claude response: {len(response.content)} chars, "
            f"{len(response.tool_calls)} tool calls"
        )

        return response

    async def _handle_tool_calls(self, response: ClaudeResponse) -> str:
        """
        Execute tool calls and get final response.

        Args:
            response: Claude response with tool calls

        Returns:
            Final response text after tool execution
        """
        logger.info(f"Handling {len(response.tool_calls)} tool calls")

        tool_results = []
        tool_context = self._build_tool_context()
        registry = get_tool_registry()

        for tool_call in response.tool_calls:
            logger.info(f"Executing tool: {tool_call.name}")

            # Execute tool
            result = await registry.execute_tool(
                tool_name=tool_call.name,
                context=tool_context,
                input_data=tool_call.input,
                timeout=10.0,
            )

            # Store collected info if applicable
            if result.success and result.data:
                self._update_collected_info(tool_call.name, result.data)

            # Format result for Claude
            tool_results.append(format_tool_result(
                tool_use_id=tool_call.id,
                result=result.to_string(),
                is_error=not result.success,
            ))

        # Add tool results to history
        self.add_tool_result(tool_results)

        # Get final response from Claude with tool results
        final_response = await self._get_claude_response()

        # If more tool calls, recurse (with depth limit)
        if final_response.tool_calls:
            # Limit recursion depth
            if self._count_recent_tool_calls() > 5:
                logger.warning("Too many consecutive tool calls, stopping")
                return "I apologize, but I'm having trouble completing that request. How else can I help you?"
            return await self._handle_tool_calls(final_response)

        return final_response.content

    def _build_system_prompt(self) -> str:
        """
        Build the system prompt based on agent configuration.

        Voice response guidelines:
        - Keep responses SHORT (1-2 sentences)
        - Use conversational language
        - Avoid lists, use natural speech
        - Handle interruptions gracefully
        """
        agent = self.context.agent
        persona = agent.persona

        # Get agent type-specific instructions
        type_instructions = self._get_agent_type_instructions()

        prompt_parts = [
            f"You are {persona.display_name}, a {persona.role} voice assistant.",
            "",
            "CRITICAL VOICE RESPONSE GUIDELINES:",
            "- Keep ALL responses SHORT: 1-2 sentences maximum",
            "- Use natural, conversational speech patterns",
            "- NEVER use bullet points, numbered lists, or markdown",
            "- NEVER say 'here are some options' or list multiple things",
            "- Be warm, helpful, and professional",
            "- If you need to provide multiple pieces of info, do so conversationally",
            "- Example: Instead of listing, say 'We have appointments on Monday at 9 AM and Tuesday at 2 PM'",
            "",
        ]

        # Add personality traits
        if persona.personality:
            traits = ", ".join(persona.personality)
            prompt_parts.append(f"Your personality: {traits}")
            prompt_parts.append("")

        # Add agent type-specific instructions
        prompt_parts.append(type_instructions)
        prompt_parts.append("")

        # Add custom system prompt if provided
        if persona.system_prompt:
            prompt_parts.append("Additional Instructions:")
            prompt_parts.append(persona.system_prompt)
            prompt_parts.append("")

        # Add current context
        prompt_parts.append("CURRENT CONTEXT:")
        prompt_parts.append(f"- Current time: {datetime.utcnow().strftime('%I:%M %p on %A, %B %d')}")
        if self.context.caller_name:
            prompt_parts.append(f"- Caller name: {self.context.caller_name}")
        if self.context.caller_phone:
            prompt_parts.append(f"- Caller phone: {self.context.caller_phone}")

        # Add collected info
        if self.context.collected_info:
            prompt_parts.append("- Collected information:")
            for key, value in self.context.collected_info.items():
                prompt_parts.append(f"  - {key}: {value}")

        return "\n".join(prompt_parts)

    def _get_agent_type_instructions(self) -> str:
        """Get instructions specific to agent type."""
        agent_type = self.context.agent.type

        instructions = {
            AgentType.RECEPTIONIST: """
RECEPTIONIST ROLE:
- Greet callers warmly and professionally
- Determine caller's needs quickly
- Route to appropriate person/department
- Take messages when needed
- Provide basic business information
- Schedule appointments if requested
""",
            AgentType.SCHEDULER: """
APPOINTMENT SCHEDULER ROLE:
- Focus on booking appointments efficiently
- Check availability before offering times
- Collect necessary attendee information
- Confirm all details before booking
- Send confirmation if email is provided
- Handle rescheduling and cancellations
""",
            AgentType.REMINDER: """
APPOINTMENT REMINDER ROLE:
- Remind caller of upcoming appointment
- Confirm if they plan to attend
- Offer to reschedule if needed
- Collect any updated information
- Keep call brief and focused
""",
            AgentType.QUALIFIER: """
LEAD QUALIFIER ROLE:
- Ask qualifying questions naturally
- Understand caller's needs and budget
- Collect contact information
- Determine fit for services
- Set appropriate next steps
- Be consultative, not pushy
""",
        }

        return instructions.get(agent_type, "")

    def _build_tools_schema(self) -> list[dict[str, Any]]:
        """Build tools schema based on agent capabilities."""
        capabilities = self.context.agent.capabilities

        registry = get_tool_registry()
        return registry.get_schemas_for_capabilities(capabilities.model_dump())

    def _build_tool_context(self) -> ToolContext:
        """Build context for tool execution."""
        return ToolContext(
            session_id=self.context.session_id,
            call_id=self.context.call_id,
            agent_id=self.context.agent.id,
            company_id=self.context.company_id,
            user_id=self.context.user_id,
            caller_phone=self.context.caller_phone,
            caller_name=self.context.caller_name,
            current_time=datetime.utcnow(),
            extra=self.context.collected_info,
        )

    def _format_messages_for_api(self) -> list[dict[str, Any]]:
        """Format message history for Claude API."""
        messages = []

        for msg in self._messages:
            messages.append({
                "role": msg.role.value,
                "content": msg.content,
            })

        return messages

    def _trim_history(self) -> None:
        """Trim message history to stay under limits."""
        while len(self._messages) > self.MAX_HISTORY_MESSAGES:
            # Remove oldest non-system messages, keeping pairs
            self._messages.pop(0)
            if self._messages and self._messages[0].role == ConversationRole.ASSISTANT:
                self._messages.pop(0)

    def _count_recent_tool_calls(self) -> int:
        """Count tool calls in recent messages."""
        count = 0
        for msg in reversed(self._messages[-10:]):
            if isinstance(msg.content, list):
                count += sum(1 for item in msg.content if isinstance(item, dict) and item.get("type") == "tool_use")
        return count

    def _update_collected_info(self, tool_name: str, data: dict) -> None:
        """Update collected information from tool results."""
        if tool_name == "collect_information":
            field_name = data.get("field_name")
            value = data.get("value")
            if field_name and value:
                self.context.collected_info[field_name] = value

        elif tool_name == "book_appointment":
            self.context.collected_info["appointment_booked"] = True
            if "attendee" in data:
                for key, value in data["attendee"].items():
                    if value:
                        self.context.collected_info[f"attendee_{key}"] = value

        elif tool_name == "take_message":
            self.context.collected_info["message_taken"] = True

    def get_conversation_summary(self) -> str:
        """
        Generate a brief summary of the conversation.

        Used for call records.
        """
        if not self._messages:
            return "No conversation recorded."

        # Get key points from conversation
        user_messages = [
            msg.content for msg in self._messages
            if msg.role == ConversationRole.USER and isinstance(msg.content, str)
        ]

        assistant_messages = [
            msg.content for msg in self._messages
            if msg.role == ConversationRole.ASSISTANT and isinstance(msg.content, str)
        ]

        summary_parts = []

        if user_messages:
            summary_parts.append(f"Caller mentioned: {user_messages[0][:100]}")

        if self.context.collected_info:
            info_summary = ", ".join(
                f"{k}: {v}" for k, v in list(self.context.collected_info.items())[:5]
            )
            summary_parts.append(f"Collected: {info_summary}")

        if assistant_messages:
            summary_parts.append(f"Agent response: {assistant_messages[-1][:100]}")

        return " | ".join(summary_parts) if summary_parts else "Brief conversation."
