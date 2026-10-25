"""A4 agent runtime tests: planner, state machine, budget, circuit,
approval gate (extends, never forks, the existing policy), executor,
and the API (tasks, approvals, audit, notifications, scheduler tick,
workflow approval nodes, 3-node LLM->condition->tool flow, pentest
graph, restart-safe resume). TestClient-based, port-free, no LLM calls
(the LLM node is stubbed at the provider boundary; the tool node is
stubbed at the builtin handler boundary).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.agent_runtime import budgets, circuit, planner, state_machine
from backend.agent_runtime.approvals import decide_for_step, normalize_policy
from backend.agent_runtime.executor import ExecutorConfig, execute_plan
from backend.agent_runtime.budgets import BudgetMeter
from backend.agent_runtime.circuit import CircuitBreaker


# ---------------------------------------------------------------- planner
def test_planner_topo_cycle_unknown_duplicate():
    steps = [{"name": "a", "kind": "echo"}, {"name": "b", "kind": "echo", "depends_on": ["a"]}]
    assert planner.validate_plan(steps) == ["a", "b"]
    with pytest.raises(planner.PlanError):
        planner.validate_plan([{"name": "a", "kind": "echo"},
                               {"name": "a", "kind": "echo"}])
    with pytest.raises(planner.PlanError):
        planner.validate_plan([{"name": "a", "kind": "echo", "depends_on": ["ghost"]}])
    with pytest.raises(planner.PlanError):
        planner.validate_plan([{"name": "a", "kind": "echo", "depends_on": ["b"]},
                               {"name": "b", "kind": "echo", "depends_on": ["a"]}])
    with pytest.raises(planner.PlanError):
        planner.validate_plan([{"name": "a", "kind": "nope"}])
    with pytest.raises(planner.PlanError):
        planner.validate_plan([{"name": "a", "kind": "tool"}])


def test_state_machine_terminal_is_final():
    assert state_machine.transition("pending", "running", state_machine.TASK_TRANSITIONS) == "running"
    with pytest.raises(state_machine.StateError):
        state_machine.transition("completed", "running", state_machine.TASK_TRANSITIONS)
    with pytest.raises(state_machine.StateError):
        state_machine.transition("cancelled", "pending", state_machine.TASK_TRANSITIONS)


def test_budget_meter_unknown_never_estimated_and_enforced():
    meter = BudgetMeter(token_budget=10)
    assert meter.add(None, None) is False
    assert meter.usage_known is False and meter.exceeded() is False
    assert meter.add(6, None) is False
    assert meter.add(5, None) is True  # 11 > 10
    assert meter.gauge()["token_pct"] == 110.0


def test_approval_blacklist_beats_automatic_and_deny_policy():
    decision, _ = decide_for_step("run_bash", {"command": "rm -rf /"},
                                  task_policy="automatic")
    assert decision == "deny"
    decision, _ = decide_for_step("run_bash", {"command": "echo hi"},
                                  task_policy="deny")
    assert decision == "deny"
    decision, _ = decide_for_step("run_bash", {"command": "echo hi"},
                                  task_policy="always")
    assert decision == "ask"
    decision, _ = decide_for_step("web_search", {"query": "x"},
                                  task_policy="always")
    assert decision == "allow"  # not sensitive: always only gates sensitive tools
    assert normalize_policy("always_ask") == "always"
    with pytest.raises(ValueError):
        normalize_policy("sometimes")


# ---------------------------------------------------------------- executor
def _echo_runner(calls):
    async def runner(step, ctx):
        calls.append(step["name"])
        return {"output": (step.get("args") or {}).get("text", ""),
                "tokens": (step.get("args") or {}).get("tokens"),
                "cost_usd": None}
    return runner


def test_executor_sensitive_step_never_runs_unapproved():
    calls = []
    steps = [{"name": "danger", "kind": "tool", "tool": "run_bash",
              "args": {"command": "echo hi"}, "status": "pending"},
             {"name": "after", "kind": "echo", "args": {"text": "x"},
              "depends_on": ["danger"], "status": "pending"}]
    out, summary, _events, needs = asyncio.run(execute_plan(
        steps, _echo_runner(calls),
        ExecutorConfig(approval_policy="always")))
    assert calls == []  # the runner was never called for the gated step
    assert needs == ["danger"]
    assert out[0]["status"] == "waiting_approval"
    assert summary["stopped_reason"] == "waiting_approval"
    assert out[1]["status"] == "pending"  # run paused; later steps untouched


def test_executor_deny_policy_skips_but_independent_steps_run():
    calls = []
    steps = [{"name": "danger", "kind": "tool", "tool": "run_bash",
              "args": {"command": "echo hi"}, "status": "pending"},
             {"name": "free", "kind": "echo", "args": {"text": "ok"}, "status": "pending"}]
    out, summary, _events, _needs = asyncio.run(execute_plan(
        steps, _echo_runner(calls),
        ExecutorConfig(approval_policy="deny")))
    assert calls == ["free"]
    assert out[0]["status"] == "skipped" and out[1]["status"] == "completed"
    assert summary["skipped"] == 1


def test_executor_once_policy_second_call_runs_after_approval():
    calls = []
    steps = [{"name": "first", "kind": "tool", "tool": "run_bash",
              "args": {"command": "echo one"}, "status": "pending"},
             {"name": "second", "kind": "tool", "tool": "run_bash",
              "args": {"command": "echo two"}, "status": "pending"}]
    out, summary, _events, needs = asyncio.run(execute_plan(
        steps, _echo_runner(calls),
        ExecutorConfig(approval_policy="once")))
    assert needs == ["first"] and calls == []
    # Simulate the decide endpoint: approval recorded + tool allowlisted.
    out, summary, _events, _needs = asyncio.run(execute_plan(
        out, _echo_runner(calls),
        ExecutorConfig(approval_policy="once",
                       approved_tools=["run_bash"],
                       approval_decisions={"first": "approved"})))
    assert calls == ["first", "second"]
    assert summary["completed"] == 2


def test_executor_budget_stops_run_and_resume_skips_completed():
    calls = []
    steps = [{"name": f"s{i}", "kind": "echo",
              "args": {"text": f"out{i}", "tokens": 8}, "status": "pending"}
             for i in range(3)]
    out, summary, _events, _needs = asyncio.run(execute_plan(
        steps, _echo_runner(calls),
        ExecutorConfig(budget=BudgetMeter(token_budget=10))))
    assert calls == ["s0", "s1"]  # 8 + 8 = 16 > 10: stops after s1
    assert summary["stopped_reason"] == "budget_exceeded"
    assert out[2]["status"] == "pending"
    # Resume with a raised budget: completed steps are NOT re-run.
    out, summary, _events, _needs = asyncio.run(execute_plan(
        out, _echo_runner(calls),
        ExecutorConfig(budget=BudgetMeter(token_budget=100, tokens_used=16))))
    assert calls == ["s0", "s1", "s2"] and summary["completed"] == 3


def test_executor_circuit_error_storm_and_no_progress():
    async def failing(step, ctx):
        raise RuntimeError("boom")

    steps = [{"name": f"s{i}", "kind": "echo", "status": "pending"} for i in range(4)]
    out, summary, _events, _needs = asyncio.run(execute_plan(
        steps, failing,
        ExecutorConfig(circuit=CircuitBreaker(max_consecutive_errors=2))))
    assert summary["stopped_reason"] == "circuit_tripped"
    assert out[2]["status"] == "pending" and out[3]["status"] == "pending"

    calls = []
    steps = [{"name": f"e{i}", "kind": "echo", "args": {"text": ""},
              "status": "pending"} for i in range(4)]
    out, summary, _events, _needs = asyncio.run(execute_plan(
        steps, _echo_runner(calls),
        ExecutorConfig(circuit=CircuitBreaker(max_no_progress=3))))
    assert calls == ["e0", "e1", "e2"]
    assert summary["stopped_reason"] == "circuit_tripped"


def test_executor_dependency_failure_skips_dependents():
    calls = []

    async def runner(step, ctx):
        calls.append(step["name"])
        if step["name"] == "bad":
            raise RuntimeError("bad step")
        return {"output": "ok", "tokens": None, "cost_usd": None}

    steps = [{"name": "bad", "kind": "echo", "status": "pending"},
             {"name": "child", "kind": "echo", "depends_on": ["bad"], "status": "pending"},
             {"name": "free", "kind": "echo", "status": "pending"}]
    out, summary, _events, _needs = asyncio.run(execute_plan(steps, runner, ExecutorConfig()))
    assert out[0]["status"] == "failed" and out[1]["status"] == "skipped"
    assert out[2]["status"] == "completed" and summary["failed"] == 1


# ---------------------------------------------------------------- API
def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite+aiosqlite:" + "/" * 3 + str(tmp_path) + "/a4.db")
    reset_engine_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client, username="a4_user"):
    creds = {"username": username, "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def _task(client, h, **over):
    payload = {"title": "A4 demo", "steps": [
        {"name": "say", "kind": "echo", "args": {"text": "hello"}},
        {"name": "shout", "kind": "transform", "args": {"op": "upper"},
         "depends_on": ["say"]},
    ]}
    payload.update(over)
    r = client.post("/api/agent-tasks", json=payload, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_api_create_run_audit_notification_runs_mirror(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    task = _task(client, h)
    r = client.post(f"/api/agent-tasks/{task['id']}/run", json={}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["summary"]["completed"] == 2
    assert body["steps"][1]["result"] == "HELLO"
    assert body["budget"]["usage_known"] is False  # unknown, never estimated
    audit = client.get(f"/api/agent-tasks/{task['id']}/audit", headers=h).json()["audit"]
    assert any(a["action"] == "step.completed" for a in audit)
    assert any(a["action"] == "task.created" for a in audit)
    notes = client.get("/api/agent-notifications", headers=h).json()["notifications"]
    assert any(n["kind"] == "completed" and n["task_id"] == task["id"] for n in notes)
    runs = client.get("/api/runs?kind=agent-task", headers=h).json()["runs"]
    assert any(task["id"] in r["title"] for r in runs)


def test_api_approval_gate_blocks_until_decided(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    task = _task(client, h, approval_policy="always", steps=[
        {"name": "shell", "kind": "tool", "tool": "run_bash", "args": {"command": "echo hi"}},
        {"name": "after", "kind": "echo", "args": {"text": "done"}, "depends_on": ["shell"]},
    ])
    r = client.post(f"/api/agent-tasks/{task['id']}/run", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "waiting_approval"
    assert r.json()["steps"][0]["status"] == "waiting_approval"
    assert r.json()["steps"][0]["result"] is None  # never executed
    assert r.json()["steps"][1]["status"] == "pending"
    approvals = client.get("/api/agent-approvals", headers=h).json()["approvals"]
    assert len(approvals) == 1 and approvals[0]["task_id"] == task["id"]
    # Running again while undecided is refused, not silently executed.
    assert client.post(f"/api/agent-tasks/{task['id']}/run", json={}, headers=h).status_code == 409
    # Deny with reason: the denied step skips, and its dependent skips
    # too (it cannot run on output that was never produced). The run
    # itself finishes cleanly — nothing failed, nothing executed.
    d = client.post(f"/api/agent-tasks/{task['id']}/approvals/{approvals[0]['id']}/decide",
                    json={"approved": False, "reason": "too risky"}, headers=h)
    assert d.status_code == 200, d.text
    r = client.post(f"/api/agent-tasks/{task['id']}/run", json={}, headers=h)
    assert r.json()["status"] == "completed", r.text
    assert r.json()["summary"]["skipped"] == 2 and r.json()["summary"]["completed"] == 0
    audit = client.get(f"/api/agent-tasks/{task['id']}/audit", headers=h).json()["audit"]
    assert any(a["action"] == "approval.denied" and "too risky" in a["detail"] for a in audit)


def test_api_record_usage_enforces_budget(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    task = _task(client, h, token_budget=10)
    r = client.post(f"/api/agent-tasks/{task['id']}/record-usage",
                    json={"tokens": 20}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed" and r.json()["budget_exceeded"] is True
    notes = client.get("/api/agent-notifications?unread_only=true", headers=h).json()["notifications"]
    assert any(n["kind"] == "budget_exceeded" for n in notes)


def test_api_circuit_trips_on_no_progress(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    task = _task(client, h, steps=[
        {"name": f"e{i}", "kind": "echo", "args": {"text": ""}} for i in range(5)])
    r = client.post(f"/api/agent-tasks/{task['id']}/run", json={}, headers=h)
    assert r.json()["status"] == "failed" and r.json()["circuit_tripped"] is True
    statuses = [s["status"] for s in r.json()["steps"]]
    assert statuses[3] == "pending" and statuses[4] == "pending"


def test_api_plan_validation_rejected(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    bad = {"title": "bad", "steps": [
        {"name": "a", "kind": "echo", "depends_on": ["b"]},
        {"name": "b", "kind": "echo", "depends_on": ["a"]}]}
    assert client.post("/api/agent-tasks", json=bad, headers=h).status_code == 422


def test_api_restart_resume_and_approval_survive(tmp_path, monkeypatch):
    """Simulate an app restart: a NEW app instance against the SAME DB
    file recovers the waiting task + pending approval, and a run after
    the decision resumes from the pending steps (completed steps intact)."""
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    task = _task(client, h, steps=[
        {"name": "gate", "kind": "approval", "args": {"note": "ok to proceed?"}},
        {"name": "after", "kind": "echo", "args": {"text": "resumed"}, "depends_on": ["gate"]},
    ])
    r = client.post(f"/api/agent-tasks/{task['id']}/run", json={}, headers=h)
    assert r.json()["status"] == "waiting_approval"

    # --- restart: fresh app, same DB file, no table drop ---
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite+aiosqlite:" + "/" * 3 + str(tmp_path) + "/a4.db")
    reset_engine_for_testing()

    async def _create_all_again():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all_again())
    client2 = TestClient(create_app())
    h2 = _auth(client2)
    got = client2.get(f"/api/agent-tasks/{task['id']}", headers=h2)
    assert got.status_code == 200, got.text
    assert got.json()["status"] == "waiting_approval"
    approvals = client2.get("/api/agent-approvals", headers=h2).json()["approvals"]
    assert len(approvals) == 1
    d = client2.post(f"/api/agent-tasks/{task['id']}/approvals/{approvals[0]['id']}/decide",
                     json={"approved": True, "reason": ""}, headers=h2)
    assert d.status_code == 200, d.text
    r = client2.post(f"/api/agent-tasks/{task['id']}/run", json={}, headers=h2)
    assert r.json()["status"] == "completed", r.text
    assert r.json()["steps"][0]["status"] == "completed"
    assert r.json()["steps"][1]["result"] == "resumed"


def test_api_workflow_approval_node_and_3node_flow(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)

    # Human-approval node: missing -> waiting_approval (downstream skipped);
    # approved -> succeeds; denied -> failed dead letter.
    wf = {"name": "gated", "definition": {"nodes": [
        {"id": "intro", "type": "text", "config": {"template": "start"}},
        {"id": "gate", "type": "approval", "config": {"note": "ship it?"}},
        {"id": "outro", "type": "text", "config": {"template": "done"}},
    ], "edges": [{"from": "intro", "to": "gate"}, {"from": "gate", "to": "outro"}]},
        "trigger": "manual"}
    r = client.post("/api/workflows", json=wf, headers=h)
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    run = client.post(f"/api/workflows/{wid}/run", json={"input": {}}, headers=h).json()
    assert run["status"] == "waiting_approval"
    assert run["node_results"]["outro"]["status"] == "skipped"
    run = client.post(f"/api/workflows/{wid}/run",
                      json={"input": {"__approvals": {"gate": "approved"}}}, headers=h).json()
    assert run["status"] == "succeeded" and run["output"]["outro"] == "done"
    run = client.post(f"/api/workflows/{wid}/run",
                      json={"input": {"__approvals": {"gate": "denied"}}}, headers=h).json()
    assert run["status"] == "failed" and "approval_denied" in (run["error"] or "")

    # 3-node flow: LLM -> condition -> tool (LLM + tool stubbed at boundaries).
    async def fake_stream(*args, **kwargs):
        yield "yes please"

    wf3 = {"name": "llm-condition-tool", "definition": {"nodes": [
        {"id": "say", "type": "llm", "config": {"prompt": "Say yes"}},
        {"id": "check", "type": "condition",
         "config": {"left": "{{nodes.say}}", "right": "yes", "op": "contains"}},
        {"id": "fetch", "type": "tool", "config": {"tool": "web_search", "args": {"query": "test"}},
         "run_if": "{{nodes.check.branch}}"},
    ], "edges": [{"from": "say", "to": "check"}, {"from": "check", "to": "fetch"}]},
        "trigger": "manual"}
    r = client.post("/api/workflows", json=wf3, headers=h)
    assert r.status_code == 201, r.text
    wid3 = r.json()["id"]
    with patch("backend.llm.stream_completion", fake_stream), \
         patch("backend.llm.default_model_id", AsyncMock(return_value="test-model")), \
         patch("backend.tools.builtin.web_search_handler",
               AsyncMock(return_value=[{"title": "result"}])):
        run = client.post(f"/api/workflows/{wid3}/run", json={"input": {}}, headers=h).json()
    assert run["status"] == "succeeded", run
    assert run["output"]["say"] == "yes please"
    assert run["output"]["check"]["branch"] == "true"
    assert run["output"]["fetch"] == [{"title": "result"}]

    # Same 3-node flow wired through a runtime task step (workflow kind).
    task = _task(client, h, steps=[
        {"name": "flow", "kind": "workflow", "args": {"workflow_id": wid3}}])
    with patch("backend.llm.stream_completion", fake_stream), \
         patch("backend.llm.default_model_id", AsyncMock(return_value="test-model")), \
         patch("backend.tools.builtin.web_search_handler",
               AsyncMock(return_value=[{"title": "result"}])):
        r = client.post(f"/api/agent-tasks/{task['id']}/run", json={}, headers=h)
    assert r.json()["status"] == "completed", r.text
    assert r.json()["steps"][0]["result"]["fetch"] == [{"title": "result"}]


def test_api_security_graph_and_scope(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    # Out-of-scope target is refused before anything fires.
    r = client.post("/api/agent-tasks/security-graph",
                    json={"target": "https://other.example", "scope": ""}, headers=h)
    assert r.status_code == 403, r.text
    a = client.post("/api/security/allowlist", json={"host_pattern": "example.com"}, headers=h)
    assert a.status_code == 201, a.text
    stub_fetchers = {"headers": lambda url: {"server": "test"},
                     "text": lambda url: "robots",
                     "dns": lambda host: ["93.184.216.34"]}
    with patch("backend.security_guardrails.RECON_FETCHERS", stub_fetchers):
        r = client.post("/api/agent-tasks/security-graph",
                        json={"target": "https://example.com", "scope": ""}, headers=h)
        assert r.status_code == 201, r.text
        task = r.json()
        assert [s["name"] for s in task["steps"]] == [
            "recon", "vuln-hunter", "validator", "reporter"]
        sec_id = task["security_run_id"]
        r = client.post(f"/api/agent-tasks/{task['id']}/run", json={}, headers=h)
        assert r.json()["status"] == "completed", r.text
        assert all(s["status"] == "completed" for s in r.json()["steps"])
        sec = client.get(f"/api/security/runs/{sec_id}", headers=h).json()
        assert sec["phase"] == "reporter"


def test_api_scheduler_tick_tasks_workflows_webhook_event(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    task = _task(client, h, trigger="hourly", next_run="2020-01-01T00:00:00Z")
    wf = {"name": "due wf", "definition": {"nodes": [
        {"id": "a", "type": "text", "config": {"template": "hi"}},
        {"id": "b", "type": "transform", "config": {"op": "upper"}},
    ], "edges": [{"from": "a", "to": "b"}]}, "trigger": "hourly"}
    r = client.post("/api/workflows", json=wf, headers=h)
    assert r.status_code == 201, r.text
    wid = r.json()["id"]

    async def _set_wf_due():
        from backend.database import AsyncSessionLocal
        from backend.models import Workflow

        async with AsyncSessionLocal() as db:
            row = await db.get(Workflow, wid)
            from datetime import UTC, datetime
            row.next_run = datetime(2020, 1, 1, tzinfo=UTC)
            await db.commit()

    asyncio.run(_set_wf_due())
    tick = client.post("/api/agent-tasks/scheduler/tick", headers=h).json()
    assert any(t["id"] == task["id"] and t["status"] == "completed"
               for t in tick["agent_tasks"]), tick
    assert any(w["id"] == wid and w["status"] == "succeeded"
               for w in tick["workflows"]), tick

    # Webhook trigger: wrong token -> 404 (no leak); right token runs.
    # A fresh client (no auth cookies): the main client's session cookie
    # would trigger CSRF middleware, which external webhook callers
    # never have (same pattern as the workflow webhook test).
    from backend.main import create_app
    from fastapi.testclient import TestClient as _TC

    hook = _task(client, h, title="hook task", trigger="webhook")
    assert hook["webhook_token"]
    webhook_client = _TC(create_app())
    assert webhook_client.post(
        "/api/agent-tasks/" + hook["id"] + "/webhook?token=wrong", json={}).status_code == 404
    r = webhook_client.post(
        "/api/agent-tasks/" + hook["id"] + "/webhook?token=" + hook["webhook_token"], json={})
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text

    # Event trigger: wrong event refused; matching event runs.
    evt = _task(client, h, title="event task", trigger="event",
                config={"event": "inbox"})
    assert client.post(f"/api/agent-tasks/{evt['id']}/event",
                       json={"event": "other"}, headers=h).status_code == 422
    r = client.post(f"/api/agent-tasks/{evt['id']}/event",
                    json={"event": "inbox"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
