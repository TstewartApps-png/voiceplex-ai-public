"""
Claude API client for voice agent intelligence.

Claude API (Haiku 4.5) provides intelligent reasoning and tool execution.
Uses Haiku as default for low latency in voice conversations.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator

import anthropic
from anthropic import AsyncAnthropic, APIError, RateLimitError, APITimeoutError

from app.config import get_settings

logger = logging.getLogger(__name__)


class MessageRole(str, Enum):
    """Message role in conversation."""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    """Conversation message."""

    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tool_use: list[dict] | None = None
    tool_results: list[dict] | None = None


@dataclass
class ToolCall:
    """Tool call requested by Claude."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ClaudeResponse:
    """Response from Claude API."""

    content: str
    tool_calls: list[ToolCall]
    stop_reason: str
    input_tokens: int
    output_tokens: int
    model: str


class ClaudeClientError(Exception):
    """Base exception for Claude client errors."""

    def __init__(self, message: str, code: str = "CLAUDE_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class ClaudeRateLimitError(ClaudeClientError):
    """Rate limit exceeded."""

    def __init__(self, retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after}s" if retry_after else "Rate limit exceeded",
            "RATE_LIMIT",
        )


class ClaudeTimeoutError(ClaudeClientError):
    """API timeout."""

    def __init__(self):
        super().__init__("Claude API request timed out", "TIMEOUT")


class ClaudeClient:
    """
    Async client for Claude API.

    Designed for voice agent use cases with:
    - Low latency (Haiku model by default)
    - Streaming support
    - Tool calling
    - Automatic retries
    - Rate limit handling
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int | None = None,
    ):
        """
        Initialize Claude client.

        Args:
            api_key: Anthropic API key (uses env if not provided)
            model: Model to use (default: claude-haiku-4-20250514)
            max_tokens: Max response tokens
            temperature: Response temperature
            timeout: Request timeout in seconds
        """
        settings = get_settings()

        self._api_key = api_key or settings.anthropic_api_key
        self._model = model or settings.claude_model
        self._fallback_model = settings.claude_model_fallback
        self._max_tokens = max_tokens or settings.claude_max_tokens
        self._temperature = temperature or settings.claude_temperature
        self._timeout = timeout or settings.claude_timeout_seconds

        if not self._api_key:
            logger.warning("Anthropic API key not configured")
            self._client = None
        else:
            self._client = AsyncAnthropic(
                api_key=self._api_key,
                timeout=self._timeout,
            )

        # Rate limiting state
        self._last_request_time: float = 0
        self._min_request_interval: float = 0.1  # 100ms between requests

    @property
    def is_configured(self) -> bool:
        """Check if client is configured."""
        return self._client is not None

    async def create_message(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        use_fallback: bool = False,
    ) -> ClaudeResponse:
        """
        Create a message using Claude API.

        Args:
            messages: Conversation messages
            system: System prompt
            tools: Tool definitions for tool use
            max_tokens: Override max tokens
            temperature: Override temperature
            use_fallback: Use fallback model (Sonnet) for complex tasks

        Returns:
            ClaudeResponse with content and tool calls

        Raises:
            ClaudeClientError: On API errors
        """
        if not self._client:
            raise ClaudeClientError("Claude client not configured", "NOT_CONFIGURED")

        # Rate limiting
        await self._rate_limit()

        model = self._fallback_model if use_fallback else self._model

        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens or self._max_tokens,
                "temperature": temperature or self._temperature,
            }

            if system:
                kwargs["system"] = system

            if tools:
                kwargs["tools"] = tools

            logger.debug(f"Calling Claude API ({model}) with {len(messages)} messages")

            response = await self._client.messages.create(**kwargs)

            # Parse response
            content = ""
            tool_calls = []

            for block in response.content:
                if block.type == "text":
                    content = block.text
                elif block.type == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.id,
                        name=block.name,
                        input=block.input,
                    ))

            logger.debug(
                f"Claude response: {len(content)} chars, "
                f"{len(tool_calls)} tool calls, "
                f"stop_reason={response.stop_reason}"
            )

            return ClaudeResponse(
                content=content,
                tool_calls=tool_calls,
                stop_reason=response.stop_reason,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=model,
            )

        except RateLimitError as e:
            retry_after = getattr(e, "retry_after", None)
            logger.warning(f"Claude rate limit exceeded: {e}")
            raise ClaudeRateLimitError(retry_after)

        except APITimeoutError:
            logger.error("Claude API timeout")
            raise ClaudeTimeoutError()

        except APIError as e:
            logger.error(f"Claude API error: {e}")
            raise ClaudeClientError(str(e), "API_ERROR")

        except Exception as e:
            logger.exception(f"Unexpected Claude error: {e}")
            raise ClaudeClientError(str(e), "UNEXPECTED_ERROR")

    async def create_message_stream(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Create a streaming message for lower latency.

        Yields text chunks as they arrive.

        Args:
            messages: Conversation messages
            system: System prompt
            tools: Tool definitions
            max_tokens: Override max tokens
            temperature: Override temperature

        Yields:
            Text chunks from response
        """
        if not self._client:
            raise ClaudeClientError("Claude client not configured", "NOT_CONFIGURED")

        await self._rate_limit()

        try:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "max_tokens": max_tokens or self._max_tokens,
                "temperature": temperature or self._temperature,
            }

            if system:
                kwargs["system"] = system

            if tools:
                kwargs["tools"] = tools

            logger.debug(f"Starting Claude stream with {len(messages)} messages")

            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text

        except RateLimitError as e:
            retry_after = getattr(e, "retry_after", None)
            raise ClaudeRateLimitError(retry_after)

        except APITimeoutError:
            raise ClaudeTimeoutError()

        except APIError as e:
            raise ClaudeClientError(str(e), "API_ERROR")

    async def create_with_tool_results(
        self,
        messages: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ClaudeResponse:
        """
        Continue conversation after tool execution.

        Args:
            messages: Original messages including assistant's tool use
            tool_results: Results from tool executions
            system: System prompt
            tools: Tool definitions

        Returns:
            ClaudeResponse with final answer
        """
        # Add tool results to messages
        messages_with_results = messages.copy()
        messages_with_results.append({
            "role": "user",
            "content": tool_results,
        })

        return await self.create_message(
            messages=messages_with_results,
            system=system,
            tools=tools,
        )

    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        import time

        now = time.time()
        elapsed = now - self._last_request_time

        if elapsed < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - elapsed)

        self._last_request_time = time.time()


def format_tool_result(
    tool_use_id: str,
    result: Any,
    is_error: bool = False,
) -> dict[str, Any]:
    """
    Format a tool result for Claude.

    Args:
        tool_use_id: ID of the tool use block
        result: Tool execution result
        is_error: Whether the result is an error

    Returns:
        Formatted tool result block
    """
    content = str(result) if not isinstance(result, str) else result

    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def format_messages_for_claude(
    conversation_history: list[Message],
) -> list[dict[str, Any]]:
    """
    Format conversation history for Claude API.

    Args:
        conversation_history: List of Message objects

    Returns:
        List of message dicts for Claude API
    """
    messages = []

    for msg in conversation_history:
        message: dict[str, Any] = {
            "role": msg.role.value,
            "content": msg.content,
        }

        # Add tool use if present
        if msg.tool_use:
            message["content"] = msg.tool_use

        # Tool results are added separately
        if msg.tool_results:
            message["content"] = msg.tool_results

        messages.append(message)

    return messages


# Global client instance
_claude_client: ClaudeClient | None = None


def get_claude_client() -> ClaudeClient:
    """Get the global Claude client instance."""
    global _claude_client
    if _claude_client is None:
        _claude_client = ClaudeClient()
    return _claude_client
