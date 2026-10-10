"""Bridge between MCP servers and Sangam's tool system.

Discovers tools from configured MCP servers and registers them as
``ToolDefinition`` entries (``mcp_<server>_<tool>``) in the global tool
registry, so the existing ``ToolExecutor`` can dispatch them via a handler
closure that calls through to the MCP client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.tools.registry import registry
from backend.tools.schemas import ToolDefinition

from .client import MCPClient, MCPTool

logger = logging.getLogger(__name__)

_clients: dict[str, MCPClient] = {}
_registered_tools: dict[str, list[str]] = {}  # server name -> tool definition names


@dataclass
class MCPServerConfig:
    """Configuration for one MCP server."""

    name: str
    command: list[str] | None = None
    args: list[str] | None = None
    url: str | None = None
    env: dict[str, str] | None = field(default=None)
    enabled: bool = True


def config_from_dict(d: dict) -> MCPServerConfig:
    """Build an MCPServerConfig from a plain dict (e.g. loaded from YAML/JSON)."""
    return MCPServerConfig(
        name=d["name"],
        command=d.get("command"),
        args=d.get("args"),
        url=d.get("url"),
        env=d.get("env"),
        enabled=d.get("enabled", True),
    )


def mcp_tool_to_definition(server_name: str, tool: MCPTool, client: MCPClient) -> ToolDefinition:
    """Convert an MCPTool into a ToolDefinition wired to ``client.call_tool``.

    The tool is renamed ``mcp_<server>_<tool>`` and its MCP ``inputSchema``
    is mapped into the JSON-schema ``parameters`` format used by
    ``backend.tools.schemas.ToolDefinition``. The executor dispatches through
    ``definition.handler`` (see ``backend.tools.executor.ToolExecutor``), which
    is an async closure calling ``client.call_tool``.
    """
    name = f"mcp_{server_name}_{tool.name}"
    schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": schema.get("properties", {}),
    }
    if "required" in schema:
        parameters["required"] = schema["required"]

    async def _handler(**arguments: Any) -> Any:
        result = await client.call_tool(tool.name, arguments)
        if result.is_error:
            return {"error": result.text or "MCP tool reported an error"}
        return result.text

    return ToolDefinition(
        name=name,
        description=tool.description or f"MCP tool '{tool.name}' from server '{server_name}'",
        parameters=parameters,
        handler=_handler,
        capabilities=["mcp"],
        safety_level="caution",
        read_only=False,
        category="general",
    )


async def register_mcp_server(cfg: MCPServerConfig) -> int:
    """Connect to an MCP server and register its tools. Returns tool count."""
    if not cfg.enabled:
        logger.info("MCP server '%s' is disabled; skipping", cfg.name)
        return 0
    if cfg.name in _clients:
        await unregister_mcp_server(cfg.name)
    client = MCPClient(
        command=cfg.command,
        args=cfg.args,
        url=cfg.url,
        env=cfg.env,
    )
    await client.connect()
    tools = await client.list_tools()
    _clients[cfg.name] = client
    names: list[str] = []
    for tool in tools:
        definition = mcp_tool_to_definition(cfg.name, tool, client)
        registry.register(definition)
        names.append(definition.name)
    _registered_tools[cfg.name] = names
    _register_extension_manifest(cfg.name, names)
    logger.info("Registered %d tool(s) from MCP server '%s'", len(names), cfg.name)
    return len(names)


async def unregister_mcp_server(name: str) -> None:
    """Remove a server's tools from the registry and close its client."""
    for tool_name in _registered_tools.pop(name, []):
        registry.unregister(tool_name)
    client = _clients.pop(name, None)
    if client is not None:
        await client.close()
    logger.info("Unregistered MCP server '%s'", name)


async def setup_mcp_servers(configs: list[dict]) -> dict[str, int]:
    """Register tools from a list of MCP server config dicts.

    Returns ``{server_name: tool_count}``. A failing server is logged and
    skipped — this function never raises.
    """
    results: dict[str, int] = {}
    for cfg_dict in configs:
        name = cfg_dict.get("name", "unknown") if isinstance(cfg_dict, dict) else "unknown"
        try:
            results[name] = await register_mcp_server(config_from_dict(cfg_dict))
        except Exception as e:
            logger.warning("Failed to set up MCP server '%s': %s", name, e)
            results[name] = 0
    return results


async def shutdown_mcp_servers() -> None:
    """Close all MCP clients and unregister their tools."""
    for name in list(_clients.keys()):
        try:
            await unregister_mcp_server(name)
        except Exception:
            logger.exception("Error while shutting down MCP server '%s'", name)
    _clients.clear()
    _registered_tools.clear()


def _register_extension_manifest(server_name: str, tool_names: list[str]) -> None:
    """Best-effort registration of an extension manifest (F1 may not exist yet)."""
    try:
        from backend import extensions  # noqa: PLC0415 - F1 extension system may not exist yet
    except ImportError:
        logger.debug("backend.extensions not available; skipping MCP extension manifest")
        return
    try:
        register_fn = getattr(extensions, "register_extension", None) or getattr(
            extensions, "register", None
        )
        if register_fn is None:
            logger.debug("backend.extensions has no register function; skipping")
            return
        kind_enum = getattr(extensions, "ExtensionKind", None)
        kind = getattr(kind_enum, "MCP_SERVER", "MCP_SERVER") if kind_enum else "MCP_SERVER"
        register_fn(name=f"mcp:{server_name}", kind=kind, tools=list(tool_names))
    except Exception:
        logger.debug("Failed to register MCP extension manifest", exc_info=True)
