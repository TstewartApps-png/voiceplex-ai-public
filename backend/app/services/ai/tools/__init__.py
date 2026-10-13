"""
Claude tools for voice agent capabilities.

Tools for calendar, email, call control that Claude
can invoke during voice conversations.
"""

import logging

from app.services.ai.tools.base import (
    BaseTool,
    ToolCategory,
    ToolParameter,
    ToolDefinition,
    ToolResult,
    ToolContext,
    ToolRegistry,
    get_tool_registry,
    register_tool,
)
from app.services.ai.tools.calendar import register_calendar_tools
from app.services.ai.tools.email import register_email_tools
from app.services.ai.tools.call_control import register_call_control_tools
from app.services.ai.tools.knowledge import register_knowledge_tools

logger = logging.getLogger(__name__)

__all__ = [
    # Base classes
    "BaseTool",
    "ToolCategory",
    "ToolParameter",
    "ToolDefinition",
    "ToolResult",
    "ToolContext",
    "ToolRegistry",
    "get_tool_registry",
    "register_tool",
    # Registration
    "register_all_tools",
]


_tools_registered = False


def register_all_tools() -> None:
    """
    Register all available tools.

    Should be called once during application startup.
    """
    global _tools_registered

    if _tools_registered:
        logger.debug("Tools already registered, skipping")
        return

    logger.info("Registering all tools...")

    register_calendar_tools()
    register_email_tools()
    register_call_control_tools()
    register_knowledge_tools()

    registry = get_tool_registry()
    logger.info(f"Total tools registered: {len(registry.get_all())}")

    _tools_registered = True
