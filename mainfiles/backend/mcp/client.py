"""Minimal MCP (Model Context Protocol) JSON-RPC 2.0 client.

Supports two transports:
  - stdio: spawns a local subprocess and speaks newline-delimited JSON-RPC.
  - SSE/HTTP: POSTs JSON-RPC payloads to an HTTP endpoint via httpx.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from asyncio.subprocess import Process
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "sangam"
CLIENT_VERSION = "1.1"


class MCPError(Exception):
    """Raised for MCP protocol errors and transport failures."""

    def __init__(self, message: str, code: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


@dataclass
class MCPTool:
    """A tool advertised by an MCP server."""

    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)


@dataclass
class MCPToolResult:
    """Result of an MCP tools/call."""

    content: list = field(default_factory=list)  # list of {"type": "text", "text": ...} dicts
    is_error: bool = False

    @property
    def text(self) -> str:
        """Join all text content blocks into a single string."""
        parts = []
        for block in self.content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)


class MCPClient:
    """Minimal async MCP client (stdio or HTTP/SSE transport)."""

    def __init__(  # noqa: PLR0913,PLR0917 - signature is part of the MCP client contract
        self,
        command: list[str] | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ):
        if (command is None) == (url is None):
            raise ValueError("Exactly one of 'command' or 'url' is required")
        self.command = command
        self.args = args
        self.url = url
        self.env = env
        self.timeout = timeout
        self.headers = headers or {}
        self._proc: Process | None = None
        self._http: Any = None
        self._reader_task: asyncio.Task | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------ connect
    async def connect(self) -> None:
        """Perform the MCP handshake. Idempotent."""
        if self._connected:
            return
        if self.command is not None:
            await self._connect_stdio()
        else:
            await self._connect_http()
        init_result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        )
        logger.info(
            "MCP connected (server: %s)",
            (init_result.get("serverInfo") or {}).get("name", "unknown"),
        )
        await self._notify("notifications/initialized", {})
        self._connected = True

    async def _connect_stdio(self) -> None:
        argv = [self.command[0], *(self.args if self.args is not None else self.command[1:])]
        env = dict(os.environ)
        if self.env:
            env.update(self.env)
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._pump_stdio())

    async def _connect_http(self) -> None:
        try:
            import httpx  # noqa: PLC0415 - optional dependency, imported only for HTTP transport
        except ImportError as e:
            raise MCPError("httpx is required for the HTTP/SSE MCP transport") from e
        self._http = httpx.AsyncClient(timeout=self.timeout, headers=self.headers)

    # ------------------------------------------------------------------ close
    async def close(self) -> None:
        """Shut down the transport. Idempotent."""
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        if self._proc is not None:
            proc, self._proc = self._proc, None
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (TimeoutError, ProcessLookupError):
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            except Exception:
                logger.debug("Error while terminating MCP subprocess", exc_info=True)
        if self._http is not None:
            http, self._http = self._http, None
            try:
                await http.aclose()
            except Exception:
                logger.debug("Error while closing MCP HTTP client", exc_info=True)
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        self._connected = False

    # ------------------------------------------------------------------ stdio pump
    async def _pump_stdio(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                line = line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Ignoring non-JSON line from MCP server: %r", line[:200])
                    continue
                self._dispatch(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MCP stdio reader failed")
        finally:
            # Fail any in-flight requests: the server is gone.
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(MCPError("MCP server connection closed"))
            self._pending.clear()

    def _dispatch(self, message: dict) -> None:
        msg_id = message.get("id")
        if msg_id is None:
            return  # notification / unsolicited event; ignore
        future = self._pending.pop(msg_id, None)
        if future is None or future.done():
            return
        if "error" in message:
            err = message["error"] or {}
            future.set_exception(
                MCPError(
                    str(err.get("message", "MCP error")),
                    code=err.get("code"),
                    data=err.get("data"),
                )
            )
        else:
            future.set_result(message.get("result"))

    # ------------------------------------------------------------------ rpc
    async def _request(self, method: str, params: dict | None = None) -> Any:
        self._next_id += 1
        request_id = self._next_id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._send(payload)
            return await asyncio.wait_for(future, timeout=self.timeout)
        except TimeoutError as e:
            self._pending.pop(request_id, None)
            raise MCPError(
                f"MCP request '{method}' timed out after {self.timeout}s", code=-32000
            ) from e
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str, params: dict | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        await self._send(payload)

    async def _send(self, payload: dict) -> None:
        raw = (json.dumps(payload) + "\n").encode("utf-8")
        if self._proc is not None:
            if self._proc.stdin is None:
                raise MCPError("MCP subprocess stdin is closed")
            self._proc.stdin.write(raw)
            await self._proc.stdin.drain()
        elif self._http is not None:
            response = await self._http.post(self.url, json=payload)
            try:
                response.raise_for_status()
            except Exception as e:
                raise MCPError(f"MCP HTTP transport error: {e}") from e
            try:
                message = response.json()
            except ValueError as e:
                raise MCPError(f"MCP HTTP transport returned invalid JSON: {e}") from e
            self._dispatch(message)
        else:
            raise MCPError("MCP client is not connected")

    # ------------------------------------------------------------------ api
    async def list_tools(self) -> list[MCPTool]:
        """Return the tools advertised by the server (tools/list)."""
        result = await self._request("tools/list", {}) or {}
        tools = []
        for entry in result.get("tools", []) or []:
            tools.append(
                MCPTool(
                    name=entry.get("name", ""),
                    description=entry.get("description", "") or "",
                    input_schema=entry.get("inputSchema") or {},
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: dict | None = None) -> MCPToolResult:
        """Invoke a server tool (tools/call)."""
        result = (
            await self._request("tools/call", {"name": name, "arguments": arguments or {}}) or {}
        )
        return MCPToolResult(
            content=result.get("content") or [],
            is_error=bool(result.get("isError", False)),
        )

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()
