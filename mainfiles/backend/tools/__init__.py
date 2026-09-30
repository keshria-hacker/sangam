"""Tools package - Tool execution infrastructure."""
from __future__ import annotations

from .builtin import register_builtin_tools
from .executor import (
    ToolExecutionError,
    ToolExecutor,
    ToolTimeoutError,
    ToolValidationError,
    executor,
)
from .registry import ToolRegistry, registry
from .schemas import (
    ToolCall,
    ToolDefinition,
    ToolResult,
    tool_definition_to_anthropic_tool,
    tool_definition_to_openai_function,
    validate_tool_arguments,
)

__all__ = [
    # Schemas
    "ToolDefinition",
    "ToolCall",
    "ToolResult",
    "validate_tool_arguments",
    "tool_definition_to_openai_function",
    "tool_definition_to_anthropic_tool",
    # Registry
    "ToolRegistry",
    "registry",
    # Executor
    "ToolExecutor",
    "ToolExecutionError",
    "ToolTimeoutError",
    "ToolValidationError",
    "executor",
    # Built-ins
    "register_builtin_tools",
]
