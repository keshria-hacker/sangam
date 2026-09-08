"""Tool registry for managing available tools."""
from __future__ import annotations

import logging
from typing import Any

from backend.tools.schemas import ToolDefinition, tool_definition_to_openai_function

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Central registry for tool definitions."""
    
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._enabled: set[str] = set()
    
    def register(self, definition: ToolDefinition) -> None:
        """Register a tool definition."""
        if definition.name in self._tools:
            logger.warning(f"Tool '{definition.name}' already registered, overwriting")
        self._tools[definition.name] = definition
        self._enabled.add(definition.name)
        logger.info(f"Registered tool: {definition.name}")
    
    def unregister(self, name: str) -> bool:
        """Unregister a tool."""
        if name in self._tools:
            del self._tools[name]
            self._enabled.discard(name)
            logger.info(f"Unregistered tool: {name}")
            return True
        return False
    
    def get(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)
    
    def get_enabled(self) -> list[ToolDefinition]:
        """Get all enabled tool definitions."""
        return [self._tools[name] for name in self._enabled if name in self._tools]
    
    def enable(self, name: str) -> bool:
        """Enable a tool."""
        if name in self._tools:
            self._enabled.add(name)
            return True
        return False
    
    def disable(self, name: str) -> bool:
        """Disable a tool."""
        if name in self._enabled:
            self._enabled.remove(name)
            return True
        return False
    
    def is_enabled(self, name: str) -> bool:
        """Check if a tool is enabled."""
        return name in self._enabled and name in self._tools
    
    def list_all(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())
    
    def to_openai_functions(self) -> list[dict[str, Any]]:
        """Convert enabled tools to OpenAI function format."""
        return [tool_definition_to_openai_function(t) for t in self.get_enabled()]
    
    def clear(self) -> None:
        """Clear all tools."""
        self._tools.clear()
        self._enabled.clear()


# Global registry instance
registry = ToolRegistry()
