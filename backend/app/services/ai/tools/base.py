"""
Base tool framework for Claude tool use.

Tools for calendar, email, call control that Claude can invoke
during voice conversations.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Type

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    """Categories of tools."""

    CALENDAR = "calendar"
    EMAIL = "email"
    CALL_CONTROL = "call_control"
    KNOWLEDGE = "knowledge"
    UTILITY = "utility"


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""

    name: str
    type: str  # string, integer, boolean, array, object
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None
    items: dict | None = None  # For array types


@dataclass
class ToolDefinition:
    """Complete tool definition for Claude."""

    name: str
    description: str
    parameters: list[ToolParameter]
    category: ToolCategory

    def to_claude_schema(self) -> dict[str, Any]:
        """
        Convert to Claude tool schema format.

        Returns:
            Tool schema dict for Claude API
        """
        properties = {}
        required = []

        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }

            if param.enum:
                prop["enum"] = param.enum

            if param.items:
                prop["items"] = param.items

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


@dataclass
class ToolResult:
    """Result from tool execution."""

    success: bool
    data: Any
    error: str | None = None
    message: str | None = None
    execution_time_ms: float = 0

    def to_string(self) -> str:
        """Convert result to string for Claude."""
        if not self.success:
            return f"Error: {self.error or 'Unknown error'}"

        if self.message:
            return self.message

        if isinstance(self.data, str):
            return self.data

        if isinstance(self.data, dict):
            # Format dict nicely
            parts = []
            for key, value in self.data.items():
                parts.append(f"{key}: {value}")
            return "\n".join(parts)

        return str(self.data)


@dataclass
class ToolContext:
    """Context passed to tool execution."""

    session_id: str
    call_id: str
    agent_id: str
    company_id: str
    user_id: str
    caller_phone: str | None = None
    caller_name: str | None = None
    current_time: datetime = field(default_factory=datetime.utcnow)
    extra: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """
    Abstract base class for all tools.

    Tools are invoked by Claude during voice conversations to perform
    actions like booking appointments, sending emails, or controlling calls.
    """

    def __init__(self):
        """Initialize the tool."""
        self._definition: ToolDefinition | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name (used in Claude API calls)."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for Claude."""
        pass

    @property
    @abstractmethod
    def category(self) -> ToolCategory:
        """Tool category."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> list[ToolParameter]:
        """Tool parameters."""
        pass

    @property
    def definition(self) -> ToolDefinition:
        """Get full tool definition."""
        if self._definition is None:
            self._definition = ToolDefinition(
                name=self.name,
                description=self.description,
                parameters=self.parameters,
                category=self.category,
            )
        return self._definition

    def to_claude_schema(self) -> dict[str, Any]:
        """Get Claude API schema for this tool."""
        return self.definition.to_claude_schema()

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Validate input parameters.

        Args:
            input_data: Input parameters from Claude

        Returns:
            Tuple of (is_valid, error_message)
        """
        for param in self.parameters:
            if param.required and param.name not in input_data:
                return False, f"Missing required parameter: {param.name}"

            if param.name in input_data:
                value = input_data[param.name]

                # Type validation
                if param.type == "string" and not isinstance(value, str):
                    return False, f"Parameter {param.name} must be a string"
                elif param.type == "integer" and not isinstance(value, int):
                    return False, f"Parameter {param.name} must be an integer"
                elif param.type == "boolean" and not isinstance(value, bool):
                    return False, f"Parameter {param.name} must be a boolean"
                elif param.type == "array" and not isinstance(value, list):
                    return False, f"Parameter {param.name} must be an array"

                # Enum validation
                if param.enum and value not in param.enum:
                    return False, f"Parameter {param.name} must be one of: {param.enum}"

        return True, None

    @abstractmethod
    async def execute(
        self,
        context: ToolContext,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Execute the tool.

        Args:
            context: Execution context with session info
            **kwargs: Tool-specific parameters

        Returns:
            ToolResult with execution outcome
        """
        pass

    async def safe_execute(
        self,
        context: ToolContext,
        input_data: dict[str, Any],
        timeout: float = 10.0,
    ) -> ToolResult:
        """
        Execute tool with validation, error handling, and timeout.

        Args:
            context: Execution context
            input_data: Input parameters from Claude
            timeout: Execution timeout in seconds

        Returns:
            ToolResult with outcome
        """
        import asyncio
        import time

        start_time = time.time()

        # Validate input
        is_valid, error = self.validate_input(input_data)
        if not is_valid:
            return ToolResult(
                success=False,
                data=None,
                error=error,
            )

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                self.execute(context, **input_data),
                timeout=timeout,
            )

            result.execution_time_ms = (time.time() - start_time) * 1000
            return result

        except asyncio.TimeoutError:
            logger.error(f"Tool {self.name} timed out after {timeout}s")
            return ToolResult(
                success=False,
                data=None,
                error=f"Tool execution timed out after {timeout} seconds",
                execution_time_ms=(time.time() - start_time) * 1000,
            )

        except Exception as e:
            logger.exception(f"Tool {self.name} execution failed: {e}")
            return ToolResult(
                success=False,
                data=None,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )


class ToolRegistry:
    """
    Registry for managing available tools.

    Tools are registered at startup and made available to Claude
    based on agent capabilities.
    """

    def __init__(self):
        """Initialize empty registry."""
        self._tools: dict[str, BaseTool] = {}
        self._tools_by_category: dict[ToolCategory, list[BaseTool]] = {
            category: [] for category in ToolCategory
        }

    def register(self, tool: BaseTool) -> None:
        """
        Register a tool.

        Args:
            tool: Tool instance to register
        """
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool: {tool.name}")

        self._tools[tool.name] = tool
        self._tools_by_category[tool.category].append(tool)

        logger.debug(f"Registered tool: {tool.name} ({tool.category.value})")

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_by_category(self, category: ToolCategory) -> list[BaseTool]:
        """Get all tools in a category."""
        return self._tools_by_category.get(category, [])

    def get_all(self) -> list[BaseTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_schemas(self, tool_names: list[str] | None = None) -> list[dict[str, Any]]:
        """
        Get Claude API schemas for tools.

        Args:
            tool_names: Specific tools to include (all if None)

        Returns:
            List of tool schemas for Claude API
        """
        if tool_names is None:
            tools = self.get_all()
        else:
            tools = [self._tools[name] for name in tool_names if name in self._tools]

        return [tool.to_claude_schema() for tool in tools]

    def get_schemas_for_capabilities(
        self,
        capabilities: dict[str, bool],
    ) -> list[dict[str, Any]]:
        """
        Get tool schemas based on agent capabilities.

        Args:
            capabilities: Dict of capability_name -> enabled

        Returns:
            List of tool schemas for enabled capabilities
        """
        schemas = []

        # Map capabilities to tool categories
        capability_map = {
            "schedule_appointments": ToolCategory.CALENDAR,
            "send_confirmations": ToolCategory.EMAIL,
            "take_messages": ToolCategory.EMAIL,
            "transfer_calls": ToolCategory.CALL_CONTROL,
        }

        # Always include knowledge and utility tools
        included_categories = {ToolCategory.KNOWLEDGE, ToolCategory.UTILITY}

        for capability, category in capability_map.items():
            if capabilities.get(capability, False):
                included_categories.add(category)

        for category in included_categories:
            for tool in self._tools_by_category[category]:
                schemas.append(tool.to_claude_schema())

        return schemas

    async def execute_tool(
        self,
        tool_name: str,
        context: ToolContext,
        input_data: dict[str, Any],
        timeout: float = 10.0,
    ) -> ToolResult:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool
            context: Execution context
            input_data: Tool input parameters
            timeout: Execution timeout

        Returns:
            ToolResult with outcome
        """
        tool = self.get(tool_name)

        if tool is None:
            logger.error(f"Tool not found: {tool_name}")
            return ToolResult(
                success=False,
                data=None,
                error=f"Tool not found: {tool_name}",
            )

        logger.info(f"Executing tool: {tool_name}")

        result = await tool.safe_execute(context, input_data, timeout)

        logger.info(
            f"Tool {tool_name} completed: success={result.success}, "
            f"time={result.execution_time_ms:.1f}ms"
        )

        return result


# Global registry instance
_tool_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry


def register_tool(tool: BaseTool) -> None:
    """Register a tool in the global registry."""
    get_tool_registry().register(tool)
