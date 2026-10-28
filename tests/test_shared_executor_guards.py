"""Shared chat tool executor must carry the ECC guard hooks.

Regression test for the gap where the agent loop built its own executor
with ``default_guard_registry()`` but the shared ``executor`` used by
the chat provider tool path (``backend.providers``) was constructed with
``hooks=None``. A model-driven tool call on the chat path could therefore
run a destructive shell command or edit a protected linter/formatter
config that the agent loop would have blocked.

The shared executor's real registry is swapped for a stub registry in
each test (and restored afterwards) so no real shell command or file
write ever runs here — the stub handler merely records that it was
called.
"""

import asyncio

import pytest

from backend.tools import executor as shared_executor
from backend.tools.registry import ToolRegistry
from backend.tools.schemas import ToolCall, ToolDefinition


def _stub_registry(tool_name, handler, required):
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name=tool_name, description="stub",
        parameters={"type": "object",
                    "properties": {arg: {"type": "string"}
                                   for arg in required},
                    "required": required},
        handler=handler))
    return reg


@pytest.fixture()
def _swapped_registry():
    shared = shared_executor
    original = shared.registry

    def swap(reg):
        shared.registry = reg

    yield swap
    shared.registry = original


def test_shared_executor_has_guard_hooks():
    assert shared_executor.hooks is not None


def test_shared_executor_blocks_destructive_bash(_swapped_registry):
    calls = []

    async def stub(command: str):
        calls.append(command)
        return {"ok": True}

    _swapped_registry(_stub_registry("run_bash", stub, ["command"]))
    result = asyncio.run(shared_executor.execute(ToolCall(
        id="c1", name="run_bash", arguments={"command": "rm -rf /"})))
    assert result.is_error
    assert "destructive-bash" in (result.error or "")
    assert calls == []


def test_shared_executor_blocks_protected_config_write(_swapped_registry):
    calls = []

    async def stub(path: str, content: str):
        calls.append(path)
        return {"ok": True}

    _swapped_registry(
        _stub_registry("write_file", stub, ["path", "content"]))
    result = asyncio.run(shared_executor.execute(ToolCall(
        id="c1", name="write_file",
        arguments={"path": ".prettierrc.json", "content": "{}"})))
    assert result.is_error
    assert calls == []


def test_shared_executor_still_runs_benign_calls(_swapped_registry):
    calls = []

    async def stub(command: str):
        calls.append(command)
        return {"ok": True}

    _swapped_registry(_stub_registry("run_bash", stub, ["command"]))
    result = asyncio.run(shared_executor.execute(ToolCall(
        id="c1", name="run_bash", arguments={"command": "echo hi"})))
    assert not result.is_error
    assert calls == ["echo hi"]
