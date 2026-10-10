"""Public surface of the backend.mcp package (F3: MCP client)."""

from __future__ import annotations

from .bridge import (
    MCPServerConfig,
    config_from_dict,
    register_mcp_server,
    setup_mcp_servers,
    shutdown_mcp_servers,
    unregister_mcp_server,
)
from .client import MCPClient, MCPError, MCPTool, MCPToolResult

__all__ = [
    "MCPClient",
    "MCPError",
    "MCPTool",
    "MCPToolResult",
    "MCPServerConfig",
    "config_from_dict",
    "register_mcp_server",
    "unregister_mcp_server",
    "setup_mcp_servers",
    "shutdown_mcp_servers",
]
