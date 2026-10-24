"""Deep-read Wave 1 — AGENT CORE (hooks, guards, cost) tests.

Covers: pi-style hook layer, strict tool-arg parsing, risk-tier policy
(blacklist beats automatic), real cost meter, loop detection, Stop hook,
durable approvals (timeout != denial), and the doctor endpoint module
mounted on a throwaway app (it is intentionally unregistered in api.py).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


# --- strict argument parsing ---------------------------------------------

def test_parse_tool_arguments_valid():
    import backend.code_agent as ca
    assert ca.parse_tool_arguments('{"path": "a.py"}') == {"path": "a.py"}
    assert ca.parse_tool_arguments("") == {}


def test_parse_tool_arguments_unparseable_raises_never_empty_dict():
    import backend.code_agent as ca
    with pytest.raises(ca.ToolArgumentsError):
        ca.parse_tool_arguments('{"path": "/etc/pa')
    with pytest.raises(ca.ToolArgumentsError):
        ca.parse_tool_arguments('[1, 2]')
    with pytest.raises(ca.ToolArgumentsError):
        ca.parse_tool_arguments(None)


# --- risk-tier policy ------------------------------------------------------

def test_blacklist_denies_even_under_automatic():
    from backend.permission_policy import DEFAULT_POLICY
    d = DEFAULT_POLICY.evaluate("run_bash", {"command": "rm -rf /"},
                                approval_policy="automatic",
                                require_approval=[])
    assert d.decision == "deny"
    assert d.rule_id and "rm-root" in d.rule_id
    assert d.recovery_hint


def test_blacklist_scoped_rm_allowed_and_config_denied():
    from backend.permission_policy import DEFAULT_POLICY
    ok = DEFAULT_POLICY.evaluate("run_bash", {"command": "rm -rf ./build"},
                                 approval_policy="automatic",
                                 require_approval=[])
    assert ok.decision == "allow"
    denied = DEFAULT_POLICY.evaluate(
        "edit_file", {"path": "proj/.eslintrc.json", "old_text": "a",
                      "new_text": "b"})
    assert denied.decision == "deny"
    assert denied.rule_id and denied.rule_id.startswith("config-deny/")
    # pyproject.toml is the deliberate ECC exception: NOT protected.
    allowed = DEFAULT_POLICY.evaluate(
        "edit_file", {"path": "pyproject.toml", "old_text": "a",
                      "new_text": "b"})
    assert allowed.decision != "deny"


def test_policy_tiers_whitelist_and_defaults():
    from backend.permission_policy import RiskPolicy, RiskRule
    policy = RiskPolicy(whitelist=[RiskRule(
        rule_id="allow/list", tool="list_files",
        arg_patterns={"path": r"^\.$"})])
    assert policy.evaluate("list_files", {"path": "."}).decision == "allow"
    assert policy.evaluate("write_file", {"path": "a.txt"}).decision == "ask"
    assert policy.evaluate("read_file", {"path": "a.txt"}).decision == "allow"
    assert policy.evaluate("read_file", {"path": "a.txt"},
                           approval_policy="always_ask").decision == "ask"
    assert policy.evaluate("write_file", {"path": "a.txt"},
                           approval_policy="automatic",
                           require_approval=[]).decision == "allow"


# --- hook layer ------------------------------------------------------------

def test_guard_hooks_block_before_execution():
    import backend.hooks as hooks
    registry = hooks.default_guard_registry()
    decision = asyncio.run(registry.run_before(
        "write_file", {"path": ".eslintrc.json", "content": "{}"}))
    assert decision.block and "config-deny" in decision.reason
    decision = asyncio.run(registry.run_before(
        "run_bash", {"command": "rm -rf ~"}))
    assert decision.block and "destructive-bash" in decision.reason
    decision = asyncio.run(registry.run_before(
        "read_file", {"path": ".eslintrc.json"}))
    assert not decision.block


def test_after_hook_redacts_secrets():
    import backend.hooks as hooks
    registry = hooks.HookRegistry(after=[hooks.redact_sensitive_hook])
    result = hooks.HookedResult(
        content="key is sk-abcdefghijklmnopqrstuvwx and ok",
        data={"api_key": "secret-value", "path": "a.txt"})
    out = asyncio.run(registry.run_after("read_file", {}, result))
    assert "sk-abcdefghijklmnopqrstuvwx" not in out.content
    assert out.data["api_key"] == "***"
    assert out.data["path"] == "a.txt"


def test_executor_before_hook_blocks_and_handler_never_runs():
    from backend.hooks import default_guard_registry
    from backend.tools.executor import ToolExecutor
    from backend.tools.registry import ToolRegistry
    from backend.tools.schemas import ToolCall, ToolDefinition

    calls = []

    async def counting_handler(path: str, content: str):
        calls.append(path)
        return {"ok": True}

    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="write_file", description="write",
        parameters={"type": "object",
                    "properties": {"path": {"type": "string"},
                                   "content": {"type": "string"}},
                    "required": ["path", "content"]},
        handler=counting_handler))
    executor = ToolExecutor(tool_registry=reg, hooks=default_guard_registry())
    result = asyncio.run(executor.execute(ToolCall(
        id="c1", name="write_file",
        arguments={"path": ".prettierrc.json", "content": "{}"})))
    assert result.is_error
    assert calls == []


def test_executor_after_hook_rewrites_every_result():
    from backend.hooks import HookedResult, HookRegistry
    from backend.tools.executor import ToolExecutor
    from backend.tools.registry import ToolRegistry
    from backend.tools.schemas import ToolCall, ToolDefinition

    def rewrite(name, args, result, ctx):
        return HookedResult(content=result.content + " [checked]",
                            data=result.data, is_error=result.is_error,
                            error=result.error)

    async def handler(path: str):
        return {"path": path}

    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="read_file", description="read",
        parameters={"type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]},
        handler=handler))
    executor = ToolExecutor(tool_registry=reg,
                            hooks=HookRegistry(after=[rewrite]))
    result = asyncio.run(executor.execute(ToolCall(
        id="c1", name="read_file", arguments={"path": "a.txt"})))
    assert result.content.endswith("[checked]")


def test_executor_same_file_mutations_serialized():
    from backend.tools.executor import ToolExecutor
    from backend.tools.registry import ToolRegistry
    from backend.tools.schemas import ToolCall, ToolDefinition

    async def handler(path: str, content: str):
        await asyncio.sleep(0)
        return {"ok": True, "content": content}

    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="write_file", description="write",
        parameters={"type": "object",
                    "properties": {"path": {"type": "string"},
                                   "content": {"type": "string"}},
                    "required": ["path", "content"]},
        handler=handler))
    executor = ToolExecutor(tool_registry=reg)
    results = asyncio.run(executor.execute_multiple([
        ToolCall(id="1", name="write_file",
                 arguments={"path": "same.txt", "content": "one"}),
        ToolCall(id="2", name="write_file",
                 arguments={"path": "same.txt", "content": "two"}),
    ]))
    assert all(not r.is_error for r in results)
    assert "same.txt" in executor._mutation_locks


# --- cost meter --------------------------------------------------------------

def test_extract_usage_real_and_unknown():
    import backend.code_agent as ca

    class _Usage:
        prompt_tokens = 10
        completion_tokens = 5
        total_tokens = 15

    assert ca.extract_usage(SimpleNamespace(usage=_Usage())) == {
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert ca.extract_usage({"usage": {"prompt_tokens": 3,
                                       "completion_tokens": 2,
                                       "total_tokens": 5}})["total_tokens"] == 5
    assert ca.extract_usage(SimpleNamespace(usage=None)) is None
    assert ca.extract_usage(SimpleNamespace()) is None


def test_cost_meter_never_fabricates():
    import backend.code_agent as ca
    meter = ca.CostMeter()
    assert meter.add(None) is False
    assert meter.unknown_responses == 1
    assert meter.cost_usd is None
    assert meter.budget_exceeded(1.0) is None  # unenforceable, not zero
    meter.add({"prompt_tokens": 100, "completion_tokens": 100,
               "total_tokens": 200})
    priced = ca.CostMeter(price_per_1k_usd=10.0)
    priced.add({"prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 200})
    assert priced.cost_usd == 2.0
    assert priced.budget_exceeded(1.0) is True
    assert priced.budget_exceeded(5.0) is False


# --- loop detector + stop hook ----------------------------------------------

def test_loop_detector_five_identical_then_reset():
    from backend.hooks import LoopDetector
    detector = LoopDetector()
    for _ in range(4):
        assert detector.record("read_file", {"path": "a"}) is False
    assert detector.record("read_file", {"path": "a"}) is True
    assert detector.record("read_file", {"path": "b"}) is False
    assert detector.streak == 1


def test_stop_checks_report_only(tmp_path):
    from backend.hooks import format_stop_report, run_stop_checks
    good = tmp_path / "good.py"
    good.write_text("x = 1\n")
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n")
    txt = tmp_path / "notes.txt"
    txt.write_text("hi\n")
    checks = run_stop_checks([str(good), str(bad), str(txt)])
    by_file = {c.file: c for c in checks}
    assert by_file[str(good)].status == "ok"
    assert by_file[str(bad)].status == "fail"
    assert by_file[str(txt)].status == "skipped"
    report = format_stop_report(checks)
    assert "report-only" in report
    assert "auto-fixed" in report


# --- durable approvals -------------------------------------------------------

def _test_engine():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from backend.database import Base
    import backend.models  # noqa: F401 — register tables
    import backend.hooks  # noqa: F401 — register AgentApproval
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_durable_approvals_timeout_distinct_from_denial():
    import backend.hooks as hooks
    engine, factory = _test_engine()
    async with engine.begin() as conn:
        await conn.run_sync(hooks.Base.metadata.create_all)
    async with factory() as db:
        assert await hooks.record_approval_row(
            db, "appr-1", "write_file", {"path": "a.txt"})
        assert await hooks.transition_approval_row(
            db, "appr-1", "timeout", "timed out (not a refusal)")
        row = await db.get(hooks.AgentApproval, "appr-1")
        assert row.status == "timeout"
        assert "not a refusal" in (row.reason or "")
        assert await hooks.record_approval_row(
            db, "appr-2", "run_bash", {"command": "ls"})
        assert await hooks.transition_approval_row(
            db, "appr-2", "denied", "denied by user")
        row2 = await db.get(hooks.AgentApproval, "appr-2")
        assert row2.status == "denied"
        assert row2.status != row.status


def test_resolve_approval_in_memory_compat_keeps_reason():
    import backend.code_agent as ca
    gate = ca.create_approval_gate("appr-x")
    assert ca.resolve_approval("appr-x", False, reason="too risky") is True
    assert gate["decision"] is False
    assert gate["reason"] == "too risky"
    assert ca.resolve_approval("appr-x", True) is False  # already popped


# --- agent loop integration (mocked LLM) --------------------------------------

class _Choice:
    def __init__(self, message, finish_reason=None):
        self.message = message
        self.finish_reason = finish_reason


class _Resp:
    def __init__(self, message, finish_reason=None, usage=None):
        self.choices = [_Choice(message, finish_reason)]
        self.usage = usage


class _Msg(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def _tool_call(name, args, call_id="1"):
    return {"id": call_id, "function": {"name": name,
                                        "arguments": json.dumps(args)}}


@pytest.mark.asyncio
async def test_run_agent_unparseable_args_never_execute(monkeypatch):
    import backend.code_agent as ca
    executed = []

    async def fake_llm(model_id, messages, tools, db):
        if len(messages) <= 2:
            return _Resp(_Msg({"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "read_file",
                                         "arguments": '{"path": "/etc/pa'}}]}))
        return _Resp(_Msg({"content": "done", "tool_calls": []}))
    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)

    async def fake_tool(name, args):
        executed.append(name)
        return {"ok": True}
    monkeypatch.setattr(ca, "_execute_tool", fake_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts",
                        lambda task, limit=4: [])
    steps = [s async for s in ca.run_agent(
        "hi", "m", db=None, tool_names=["read_file"], max_iterations=3)]
    assert executed == []
    assert any("NOT executed" in s.content for s in steps)
    assert not any(s.kind == "tool_call" for s in steps)


@pytest.mark.asyncio
async def test_run_agent_truncated_output_fails_all_calls(monkeypatch):
    import backend.code_agent as ca
    executed = []

    async def fake_llm(model_id, messages, tools, db):
        if len(messages) <= 2:
            return _Resp(_Msg({"content": "", "tool_calls": [
                _tool_call("read_file", {"path": "a.txt"})]}),
                finish_reason="length")
        return _Resp(_Msg({"content": "done", "tool_calls": []}))
    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)

    async def fake_tool(name, args):
        executed.append(name)
        return {"ok": True}
    monkeypatch.setattr(ca, "_execute_tool", fake_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts",
                        lambda task, limit=4: [])
    steps = [s async for s in ca.run_agent(
        "hi", "m", db=None, tool_names=["read_file"], max_iterations=3)]
    assert executed == []
    assert any("truncated" in s.content.lower() for s in steps)


@pytest.mark.asyncio
async def test_run_agent_blacklist_denies_under_automatic(monkeypatch):
    import backend.code_agent as ca
    executed = []

    async def fake_llm(model_id, messages, tools, db):
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            return _Resp(_Msg({"content": "", "tool_calls": [
                _tool_call("run_bash", {"command": "rm -rf /"})]}))
        return _Resp(_Msg({"content": "understood", "tool_calls": []}))
    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)

    async def fake_tool(name, args):
        executed.append(name)
        return {"ok": True}
    monkeypatch.setattr(ca, "_execute_tool", fake_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts",
                        lambda task, limit=4: [])
    steps = [s async for s in ca.run_agent(
        "hi", "m", db=None, tool_names=["run_bash"], max_iterations=3,
        approval_policy="automatic", require_approval=[])]
    assert executed == []
    denied = [s for s in steps if "Denied by policy" in s.content]
    assert denied and "destructive-bash" in denied[0].content
    assert not any(s.kind == "approval_needed" for s in steps)


@pytest.mark.asyncio
async def test_run_agent_loop_detection_stops_and_asks(monkeypatch):
    import backend.code_agent as ca
    executed = []

    async def fake_llm(model_id, messages, tools, db):
        return _Resp(_Msg({"content": "", "tool_calls": [
            _tool_call("list_files", {"path": "."})]}))
    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)

    async def fake_tool(name, args):
        executed.append(name)
        return {"ok": True}
    monkeypatch.setattr(ca, "_execute_tool", fake_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts",
                        lambda task, limit=4: [])
    steps = [s async for s in ca.run_agent(
        "hi", "m", db=None, tool_names=["list_files"], max_iterations=10)]
    assert len(executed) == 4  # 5th identical call is stopped, not run
    assert any("Loop detected" in s.content for s in steps)


@pytest.mark.asyncio
async def test_run_agent_approval_timeout_is_not_refusal(monkeypatch):
    import backend.code_agent as ca
    import backend.hooks as hooks
    engine, factory = _test_engine()
    async with engine.begin() as conn:
        await conn.run_sync(hooks.Base.metadata.create_all)

    async def fake_llm(model_id, messages, tools, db):
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            return _Resp(_Msg({"content": "", "tool_calls": [
                _tool_call("write_file", {"path": "a.txt",
                                          "content": "hi"})]}))
        return _Resp(_Msg({"content": "done", "tool_calls": []}))
    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)

    async def fake_tool(name, args):
        raise AssertionError("timed-out call must not execute")
    monkeypatch.setattr(ca, "_execute_tool", fake_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts",
                        lambda task, limit=4: [])
    async with factory() as db:
        steps = [s async for s in ca.run_agent(
            "hi", "m", db=db, tool_names=["write_file"], max_iterations=3,
            approval_timeout=0.05)]
        from sqlalchemy import select
        rows = (await db.execute(select(hooks.AgentApproval))).scalars().all()
    assert any("not a refusal" in s.content for s in steps)
    assert len(rows) == 1 and rows[0].status == "timeout"


@pytest.mark.asyncio
async def test_run_agent_real_usage_not_estimate(monkeypatch):
    import backend.code_agent as ca
    seen: list = []
    snapshots: list = []

    async def fake_llm(model_id, messages, tools, db):
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            return _Resp(_Msg({"content": "", "tool_calls": [
                _tool_call("list_files", {"path": "."})]}),
                usage=SimpleNamespace(prompt_tokens=800,
                                      completion_tokens=200,
                                      total_tokens=1000))
        return _Resp(_Msg({"content": "done", "tool_calls": []}),
                     usage=SimpleNamespace(prompt_tokens=40,
                                           completion_tokens=10,
                                           total_tokens=50))
    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)

    async def fake_tool(name, args):
        return {"ok": True}
    monkeypatch.setattr(ca, "_execute_tool", fake_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts",
                        lambda task, limit=4: [])
    steps = [s async for s in ca.run_agent(
        "hi", "m", db=None, tool_names=["list_files"], max_iterations=3,
        on_usage=seen.append, on_usage_detail=snapshots.append)]
    assert seen[-1] == 1050  # 1000 + 50 real tokens, not len(text)//4
    assert snapshots[-1]["total_tokens"] == 1050
    assert snapshots[-1]["usage_known"] is True
    assert snapshots[-1]["cost_known"] is False  # no price configured
    assert any(s.kind == "answer" for s in steps)


# --- doctor endpoint (mounted on a throwaway app) ------------------------------

def test_doctor_endpoint_reports_sections_with_fix_hints():
    import backend.hooks  # noqa: F401 — ensure tables registered
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from backend.database import get_db
    from backend.doctor import router as doctor_router
    from backend.models import Automation, ProviderKey

    engine, factory = _test_engine()

    async def _seed():
        async with engine.begin() as conn:
            from backend.database import Base
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            db.add(ProviderKey(provider_id="openai",
                               api_key_encrypted=b"dummy-bytes"))
            db.add(Automation(id="auto-1", user_id="u1", name="daily",
                              trigger="daily", action="chat"))
            await db.commit()
    asyncio.run(_seed())

    async def _override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(doctor_router, prefix="/api")
    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    resp = client.get("/api/system/doctor")
    assert resp.status_code == 200
    body = resp.json()
    names = {c["name"] for c in body["checks"]}
    assert {"providers", "keys", "packs", "workspace", "mcp_servers",
            "automations"} <= names
    keys = next(c for c in body["checks"] if c["name"] == "keys")
    assert keys["status"] == "ok"
    assert "dummy-bytes" not in resp.text  # no secret material leaks
    # Unhealthy checks must carry a fix hint.
    for check in body["checks"]:
        if check["status"] in ("warn", "error"):
            assert check.get("fix_hint"), check
