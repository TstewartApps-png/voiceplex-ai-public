"""
AI services for VoicePlex voice agents.

Provides Claude API integration and tool execution for
intelligent voice conversations.
"""

from app.services.ai.claude_client import (
    ClaudeClient,
    ClaudeResponse,
    ToolCall,
    ClaudeClientError,
    ClaudeRateLimitError,
    ClaudeTimeoutError,
    get_claude_client,
    format_tool_result,
)
from app.services.ai.conversation import (
    ConversationManager,
    ConversationContext,
    ConversationMessage,
    ConversationRole,
)
from app.services.ai.tools import (
    BaseTool,
    ToolCategory,
    ToolParameter,
    ToolDefinition,
    ToolResult,
    ToolContext,
    ToolRegistry,
    get_tool_registry,
    register_tool,
    register_all_tools,
)

__all__ = [
    # Claude client
    "ClaudeClient",
    "ClaudeResponse",
    "ToolCall",
    "ClaudeClientError",
    "ClaudeRateLimitError",
    "ClaudeTimeoutError",
    "get_claude_client",
    "format_tool_result",
    # Conversation
    "ConversationManager",
    "ConversationContext",
    "ConversationMessage",
    "ConversationRole",
    # Tools
    "BaseTool",
    "ToolCategory",
    "ToolParameter",
    "ToolDefinition",
    "ToolResult",
    "ToolContext",
    "ToolRegistry",
    "get_tool_registry",
    "register_tool",
    "register_all_tools",
]
