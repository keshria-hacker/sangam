"""Tests for the MCP client (F3): JSON-RPC client, bridge, and registry wiring."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from backend.mcp import (
    MCPClient,
    MCPError,
    MCPServerConfig,
    MCPTool,
    MCPToolResult,
    config_from_dict,
    setup_mcp_servers,
    shutdown_mcp_servers,
    unregister_mcp_server,
)
from backend.mcp.bridge import (
    _clients,
    _registered_tools,
    mcp_tool_to_definition,
    register_mcp_server,
)
from backend.tools.executor import ToolExecutor
from backend.tools.registry import registry
from backend.tools.schemas import ToolCall

FAKE_SERVER_SCRIPT = textwrap.dedent(
    """
    import json, sys

    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()

    def main():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            mid = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {}) or {}
            if method == "initialize":
                send({"jsonrpc": "2.0", "id": mid, "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "fake-mcp", "version": "0.1"},
                }})
            elif method == "notifications/initialized":
                pass  # notification: no reply
            elif method == "tools/list":
                send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [{
                    "name": "echo",
                    "description": "Echo some text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                }]}})
            elif method == "tools/call":
                if params.get("name") == "echo":
                    args = params.get("arguments", {}) or {}
                    send({"jsonrpc": "2.0", "id": mid, "result": {"content": [
                        {"type": "text", "text": "echo:" + str(args.get("text", ""))},
                    ]}})
                else:
                    send({"jsonrpc": "2.0", "id": mid, "error": {
                        "code": -32602, "message": "Unknown tool"}})
            else:
                send({"jsonrpc": "2.0", "id": mid, "error": {
                    "code": -32601, "message": "Method not found"}})

    main()
    """
)


@pytest.fixture()
def fake_server_path(tmp_path: Path) -> Path:
    path = tmp_path / "fake_mcp_server.py"
    path.write_text(FAKE_SERVER_SCRIPT, encoding="utf-8")
    return path


def make_client(fake_server_path: Path, **kwargs) -> MCPClient:
    return MCPClient(command=[sys.executable, str(fake_server_path)], **kwargs)


async def test_connect_list_call_close(fake_server_path: Path):
    client = make_client(fake_server_path)
    await client.connect()
    assert client.connected
    # connect() is idempotent
    await client.connect()

    tools = await client.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "echo"
    assert tools[0].description == "Echo some text"
    assert tools[0].input_schema["properties"]["text"]["type"] == "string"

    result = await client.call_tool("echo", {"text": "hello"})
    assert isinstance(result, MCPToolResult)
    assert result.is_error is False
    assert result.text == "echo:hello"

    # close() is idempotent
    await client.close()
    await client.close()
    assert not client.connected


async def test_call_unknown_tool_raises_mcp_error(fake_server_path: Path):
    client = make_client(fake_server_path)
    await client.connect()
    try:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("does-not-exist", {})
        assert exc_info.value.code == -32602
    finally:
        await client.close()


async def test_mcp_error_attributes():
    err = MCPError("boom", code=-32600, data={"x": 1})
    assert err.code == -32600
    assert err.data == {"x": 1}
    assert str(err) == "boom"


def test_mcp_tool_result_text_property():
    result = MCPToolResult(
        content=[
            {"type": "text", "text": "a"},
            {"type": "image", "data": "ignored"},
            {"type": "text", "text": "b"},
        ],
        is_error=True,
    )
    assert result.text == "a\nb"
    assert result.is_error is True


def test_client_requires_exactly_one_transport():
    with pytest.raises(ValueError):
        MCPClient()
    with pytest.raises(ValueError):
        MCPClient(command=["x"], url="http://localhost")


def test_config_from_dict():
    cfg = config_from_dict(
        {
            "name": "srv",
            "command": ["npx", "-y", "some-mcp"],
            "args": ["--flag"],
            "env": {"TOKEN": "abc"},
            "enabled": False,
        }
    )
    assert isinstance(cfg, MCPServerConfig)
    assert cfg.name == "srv"
    assert cfg.command == ["npx", "-y", "some-mcp"]
    assert cfg.args == ["--flag"]
    assert cfg.env == {"TOKEN": "abc"}
    assert cfg.enabled is False

    minimal = config_from_dict({"name": "web", "url": "http://localhost:9000/mcp"})
    assert minimal.url == "http://localhost:9000/mcp"
    assert minimal.enabled is True
    assert minimal.command is None


def test_mcp_tool_to_definition_conversion():
    """Conversion works with no live server: name prefix + schema mapping."""
    tool = MCPTool(
        name="search",
        description="Search the codebase",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    definition = mcp_tool_to_definition("code", tool, client=object())
    assert definition.name == "mcp_code_search"
    assert definition.description == "Search the codebase"
    assert definition.parameters["type"] == "object"
    assert definition.parameters["properties"] == {"query": {"type": "string"}}
    assert definition.parameters["required"] == ["query"]
    assert callable(definition.handler)

    # Fallback description when the MCP tool has none.
    bare = mcp_tool_to_definition("code", MCPTool(name="x"), client=object())
    assert bare.name == "mcp_code_x"
    assert "x" in bare.description and "code" in bare.description


async def test_register_wires_tools_into_executor(fake_server_path: Path):
    """End-to-end: fake server -> registry -> ToolExecutor dispatches handler."""
    cfg = MCPServerConfig(name="fake", command=[sys.executable, str(fake_server_path)])
    count = await register_mcp_server(cfg)
    try:
        assert count == 1
        assert "fake" in _clients
        assert _registered_tools["fake"] == ["mcp_fake_echo"]

        tool_call = ToolCall(id="tc1", name="mcp_fake_echo", arguments={"text": "hi"})
        result = await ToolExecutor().execute(tool_call)
        assert result.is_error is False
        assert result.content == "echo:hi"
    finally:
        await unregister_mcp_server("fake")
    assert registry.get("mcp_fake_echo") is None
    assert "fake" not in _clients


async def test_setup_mcp_servers_never_raises_on_unreachable():
    """A dead server must not raise; it reports 0 tools and leaves no residue."""
    results = await setup_mcp_servers(
        [
            {"name": "dead-server", "command": ["nonexistent-binary-xyz-123"]},
            {"name": "disabled-one", "command": ["whatever"], "enabled": False},
        ]
    )
    assert results == {"dead-server": 0, "disabled-one": 0}
    assert "dead-server" not in _clients
    await shutdown_mcp_servers()


async def test_setup_mcp_servers_empty():
    assert await setup_mcp_servers([]) == {}
    await shutdown_mcp_servers()
