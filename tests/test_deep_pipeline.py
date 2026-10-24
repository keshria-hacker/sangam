"""Wave-1 deep-pipeline tests: spec-kit chain, real per-task agent runs
(mocked agent runner + test runner at the pipeline_agents seam — the
run itself is exercised through the real route/ledger code, never a
synthesis), TDD halting, two-stage review over a real diff package,
5-round fix loop, and chain finish gating.

Pattern follows test_batch5_skills.py: fresh SQLite DB per test,
TestClient, no Playwright, no servers.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.api_routes.engineering_routes  # noqa: E402,F401 — registers tables
import backend.api_routes.spec_routes  # noqa: E402,F401
from backend.config import settings  # noqa: E402
from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.spec_chain import (  # noqa: E402
    apply_clarifications,
    analyze_coverage,
    render_plan,
    render_spec,
    render_tasks,
    validate_plan,
    validate_tasks,
)
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    os.environ["CHROMA_DB_PATH"] = str(tmp_path / "chroma")
    import backend.rag as rag_mod
    importlib.reload(rag_mod)
    rag_mod._client = None
    rag_mod._collection = None
    from backend import memory as memory_mod
    memory_mod.reset_memory_for_testing()
    monkeypatch.setattr(settings, "DATABASE_URL",
                        f"sqlite+aiosqlite:///{tmp_path}/deep-pipe.db")
    reset_engine_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


@pytest.fixture
def client(tmp_path, monkeypatch):
    return _api_client(tmp_path, monkeypatch)


def _auth_headers(client):
    creds = {"username": "deep_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post(
        "/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


# ---------------------------------------------------------------- fixtures
SPEC = render_spec(
    "Login + export",
    "Users need to log in and export their data.",
    [{"title": "Log in", "priority": "P0",
      "given": "a registered user", "when": "they submit credentials",
      "then": "a session is created"},
     {"title": "Export data", "priority": "P1",
      "given": "a logged-in user", "when": "they request an export",
      "then": "[NEEDS CLARIFICATION] export is delivered"}],
    ["User can log in with email + password",
     "Export supports [NEEDS CLARIFICATION: export format] format"])

PLAN = render_plan(
    "Research resolves export format: CSV (clarified). No other open markers.",
    "User(id, email, password_hash); Export(id, user_id, format)",
    "POST /api/export -> CSV file download",
    "1. Register 2. Log in 3. GET /api/export -> CSV")

TASKS = render_tasks([
    {"title": "Implement login", "files": ["src/auth.py"],
     "parallel": False, "covers": ["FR-001"]},
    {"title": "Implement export", "files": ["src/export.py"],
     "parallel": True, "covers": ["FR-002"]},
])

TASKS_SEQ = render_tasks([
    {"title": "Implement login", "files": ["src/auth.py"],
     "parallel": False, "covers": ["FR-001"]},
    {"title": "Implement export", "files": ["src/export.py"],
     "parallel": False, "covers": ["FR-002"]},
])


def _pipe(client, h):
    r = client.post("/api/engineering", json={"title": "Pipe", "goal": "Build X"},
                    headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _chain(client, h, pid, stage, artifact="", **kw):
    body = {"stage": stage, "artifact": artifact}
    body.update(kw)
    return client.post(f"/api/engineering/{pid}/chain/advance", json=body,
                       headers=h)


def _chain_to_tasks(client, h, pid, tasks=TASKS):
    assert _chain(client, h, pid, "constitution",
                  "# Constitution\n- Principle: tests before code").status_code == 200
    assert _chain(client, h, pid, "spec", SPEC).status_code == 200
    r = _chain(client, h, pid, "clarify", "",
               clarifications=[{"question": "[NEEDS CLARIFICATION: export format]",
                                "answer": "CSV"}])
    assert r.status_code == 200, r.text
    assert _chain(client, h, pid, "plan", PLAN).status_code == 200
    r = _chain(client, h, pid, "tasks", tasks)
    assert r.status_code == 200, r.text


def _fake_agent(monkeypatch, diff_for=("src/auth.py", "src/export.py")):
    import backend.pipeline_agents as pagents
    from backend.pipeline_agents import TaskAgentResult

    async def fake_run(task_id, brief, model_id, db, files=None,
                       fresh_context=False):
        diff = ""
        for f in (files or []):
            diff += f"--- a/{f}\n+++ b/{f}\n+new code for {task_id}\n"
        return TaskAgentResult(task_id=task_id, diff=diff, answer="done")
    monkeypatch.setattr(pagents, "run_task_agent", fake_run)
    return pagents


def _run_task(client, h, pid, task_id, test_command="pytest tests/test_x.py -q"):
    return client.post(f"/api/engineering/{pid}/chain/tasks/{task_id}/run",
                       json={"test_command": test_command, "model": "test-model"},
                       headers=h)


# ---------------------------------------------------------------- pure chain
def test_spec_requires_stories_frs_and_gwt():
    from backend.spec_chain import validate_spec
    validate_spec(SPEC)
    with pytest.raises(ValueError):
        validate_spec("# No stories\n- FR-001: x\n")
    with pytest.raises(ValueError):
        validate_spec("### Story S1 (priority: P0)\nTitle\n- Given a\n- When b\n")


def test_clarify_capped_at_five_and_written_back():
    from backend.spec_chain import spec_markers
    assert "[NEEDS CLARIFICATION: export format]" in spec_markers(SPEC)
    updated = apply_clarifications(
        SPEC, [{"question": "[NEEDS CLARIFICATION: export format]",
                "answer": "CSV"}])
    assert "CSV" in updated
    assert "[NEEDS CLARIFICATION: export format]" not in updated
    with pytest.raises(ValueError):
        apply_clarifications(SPEC, [{"question": f"q{i}", "answer": "a"}
                                    for i in range(6)])


def test_plan_must_resolve_markers_and_stop_before_code():
    with pytest.raises(ValueError):
        validate_plan(render_plan("vague research", "m", "c", "q"), SPEC)
    with pytest.raises(ValueError):
        validate_plan(PLAN + "\n--- a/x\n+++ b/x\n", SPEC)


def test_tasks_parallel_only_when_parallel_safe():
    validate_tasks(TASKS)
    bad = render_tasks([
        {"title": "A", "files": ["src/same.py"], "parallel": True},
        {"title": "B", "files": ["src/same.py"], "parallel": True}])
    with pytest.raises(ValueError):
        validate_tasks(bad)
    with pytest.raises(ValueError):
        validate_tasks("- [ ] T2 first, no T1\n  — files: src/a.py")


def test_analyze_and_converge_gap_tasks():
    from backend.spec_chain import uncovered_frs, validate_converge
    one_task = render_tasks([
        {"title": "Implement login", "files": ["src/auth.py"],
         "parallel": False, "covers": ["FR-001"]}])
    analysis = analyze_coverage(SPEC, one_task)
    assert uncovered_frs(analysis) == ["FR-002"]
    with pytest.raises(ValueError):
        validate_converge(analysis, "- [ ] T1 unrelated — files: src/z.py")
    validate_converge(analysis, render_tasks([
        {"title": "Add export", "files": ["src/export.py"],
         "parallel": False, "covers": ["FR-002"]}]))


def test_whole_spec_dispatch_is_retired():
    from backend.spec_chain import spec_to_agent_task
    with pytest.raises(NotImplementedError):
        spec_to_agent_task(SPEC)


def test_diff_builder_is_a_real_unified_diff():
    from backend.pipeline_agents import build_diff_from_snapshots
    diff = build_diff_from_snapshots(
        {"src/a.py": "x = 1\n"}, {"src/a.py": "x = 2\n"})
    assert "--- a/src/a.py" in diff and "-x = 1" in diff and "+x = 2" in diff
    assert build_diff_from_snapshots({"src/a.py": "same\n"},
                                     {"src/a.py": "same\n"}) == ""


def test_run_tests_requires_a_command():
    from backend.pipeline_agents import run_tests
    passed, out = run_tests("")
    assert passed is False and "no test command" in out


def test_spec_wizard_file_is_gone():
    assert not (_ROOT / "mainfiles" / "backend" / "spec_wizard.py").exists()


def test_spec_endpoints_use_chain_spec(client):
    h = _auth_headers(client)
    r = client.post("/api/spec/build",
                    json={"title": "T", "problem": "P", "goals": ["Log in"],
                          "constraints": [], "plan": [], "tasks": []},
                    headers=h)
    assert r.status_code == 200, r.text
    assert "Story S1" in r.json()["spec"] and "FR-001" in r.json()["spec"]
    r = client.post("/api/spec/to-task",
                    json={"title": "T", "problem": "P", "goals": ["Log in"],
                          "constraints": [], "plan": [],
                          "tasks": ["Implement login"]},
                    headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()["task_briefs"]) == 1
    assert "Implement task T1" in r.json()["task_briefs"][0]


# ---------------------------------------------------------------- chain routes
def test_chain_order_and_stage_validation(client):
    h = _auth_headers(client)
    pid = _pipe(client, h)
    r = _chain(client, h, pid, "plan", PLAN)
    assert r.status_code == 422, r.text
    r = _chain(client, h, pid, "constitution", "no principles here")
    assert r.status_code == 422, r.text
    assert _chain(client, h, pid, "constitution",
                  "# Constitution\n- Principle: tests first").status_code == 200
    r = _chain(client, h, pid, "spec", "# Empty")
    assert r.status_code == 422, r.text
    r = _chain(client, h, pid, "clarify", "")
    assert r.status_code == 422, r.text  # clarifications required, not free text


def test_tdd_halt_and_sequential_halt(client, monkeypatch):
    h = _auth_headers(client)
    pid = _pipe(client, h)
    _chain_to_tasks(client, h, pid, tasks=TASKS_SEQ)
    pagents = _fake_agent(monkeypatch)
    monkeypatch.setattr(pagents, "run_tests", lambda cmd, timeout=300: (False, "FAILED"))
    # Sequential task T2 cannot run before T1 passes.
    r = _run_task(client, h, pid, "T2")
    assert r.status_code == 422, r.text
    r = _run_task(client, h, pid, "T1")
    assert r.status_code == 200, r.text
    assert r.json()["test_passed"] is False
    # Failing implement stage halts the chain instead of proceeding.
    r = _chain(client, h, pid, "implement", "summary")
    assert r.status_code == 422, r.text


def test_chain_full_path_review_package_and_finish_gate(client, monkeypatch):
    h = _auth_headers(client)
    pid = _pipe(client, h)
    _chain_to_tasks(client, h, pid)
    pagents = _fake_agent(monkeypatch)
    monkeypatch.setattr(pagents, "run_tests", lambda cmd, timeout=300: (True, "ok"))
    for tid in ("T1", "T2"):
        r = _run_task(client, h, pid, tid)
        assert r.status_code == 200, r.text
        assert r.json()["test_passed"] is True
        assert "+++ b/src/" in r.json()["diff"]
    assert _chain(client, h, pid, "implement", "both tasks green").status_code == 200
    chain = client.get(f"/api/engineering/{pid}/chain", headers=h).json()
    spec_text = next(s["artifact"] for s in chain["stages"] if s["stage"] == "spec")
    tasks_text = next(s["artifact"] for s in chain["stages"] if s["stage"] == "tasks")
    analysis = analyze_coverage(spec_text, tasks_text)
    assert _chain(client, h, pid, "analyze", analysis).status_code == 200
    converge = render_tasks([{"title": "No gaps", "files": ["src/noop.py"],
                              "parallel": False}])
    assert _chain(client, h, pid, "converge", converge).status_code == 200
    # Finish before any review -> 422.
    r = client.post(f"/api/engineering/{pid}/chain/finish", json={}, headers=h)
    assert r.status_code == 422, r.text
    r = client.post(f"/api/engineering/{pid}/chain/review-package", json={},
                    headers=h)
    assert r.status_code == 200, r.text
    pkg_id = r.json()["id"]
    assert r.json()["base_ref"] and r.json()["head_ref"]
    assert "+++ b/src/auth.py" in r.json()["diff"]
    # Pasted text alone (no package id) must NOT satisfy a review.
    r = client.post(f"/api/engineering/{pid}/chain/review/spec",
                    json={"verdict": "pass", "artifact": "looks good",
                          "review_package_id": pkg_id}, headers=h)
    assert r.status_code == 422, r.text
    for axis in ("spec", "quality"):
        r = client.post(f"/api/engineering/{pid}/chain/review/{axis}",
                        json={"verdict": "pass",
                              "artifact": f"pass for package {pkg_id}",
                              "review_package_id": pkg_id}, headers=h)
        assert r.status_code == 200, r.text
    r = client.post(f"/api/engineering/{pid}/chain/finish", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["finished"] is True
    assert r.json()["review_package_id"] == pkg_id


def test_review_package_requires_nonempty_diff(client, monkeypatch):
    h = _auth_headers(client)
    pid = _pipe(client, h)
    _chain_to_tasks(client, h, pid)
    r = client.post(f"/api/engineering/{pid}/chain/review-package", json={},
                    headers=h)
    assert r.status_code == 422, r.text  # no task runs -> no diff


def test_fix_loop_cap_and_fresh_context_rounds(client, monkeypatch):
    h = _auth_headers(client)
    pid = _pipe(client, h)
    _chain_to_tasks(client, h, pid)
    pagents = _fake_agent(monkeypatch)
    monkeypatch.setattr(pagents, "run_tests", lambda cmd, timeout=300: (False, "FAILED"))
    r = _run_task(client, h, pid, "T1")
    assert r.status_code == 200
    monkeypatch.setattr(pagents, "run_tests", lambda cmd, timeout=300: (True, "ok"))
    r = client.post(f"/api/engineering/{pid}/chain/review-package", json={},
                    headers=h)
    assert r.status_code == 200, r.text
    pkg_id = r.json()["id"]
    r = client.post(f"/api/engineering/{pid}/chain/review/spec",
                    json={"verdict": "fail",
                          "artifact": f"fails spec, package {pkg_id}",
                          "review_package_id": pkg_id}, headers=h)
    assert r.status_code == 200, r.text
    fresh_flags = []
    for round_no in range(1, 6):
        r = client.post(f"/api/engineering/{pid}/chain/review/spec/fix",
                        json={"task_id": "T1", "test_command": "pytest -q",
                              "model": "test-model"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["fix_round"] == round_no
        fresh_flags.append(r.json()["fresh_context"])
    assert fresh_flags == [False, False, False, True, True]
    r = client.post(f"/api/engineering/{pid}/chain/review/spec/fix",
                    json={"task_id": "T1", "test_command": "pytest -q",
                          "model": "test-model"}, headers=h)
    assert r.status_code == 422, r.text  # 5-round cap


def test_legacy_subagent_runs_real_per_task_agents(client, monkeypatch):
    import backend.llm as llm_mod
    import backend.pipeline_agents as pagents
    from backend.pipeline_agents import TaskAgentResult

    h = _auth_headers(client)
    pid = _pipe(client, h)
    _chain_to_tasks(client, h, pid)

    async def fake_default(db):
        return "test-model"
    monkeypatch.setattr(llm_mod, "default_model_id", fake_default)

    async def fake_run(task_id, brief, model_id, db, files=None,
                       fresh_context=False):
        return TaskAgentResult(task_id=task_id,
                               diff=f"--- a/{(files or ['x'])[0]}\n"
                                    f"+++ b/{(files or ['x'])[0]}\n+code",
                               answer="done")
    monkeypatch.setattr(pagents, "run_task_agent", fake_run)
    for stage in ("grill", "brainstorm", "design", "plan"):
        r = client.post(f"/api/engineering/{pid}/advance",
                        json={"stage": stage, "artifact": f"{stage} artifact"},
                        headers=h)
        assert r.status_code == 200, r.text
    r = client.post(f"/api/engineering/{pid}/advance",
                    json={"stage": "subagent", "artifact": ""}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "agent"
    assert "Task T1" in r.json()["artifact"]
    assert "+++ b/src/auth.py" in r.json()["artifact"]


def test_legacy_pipeline_still_enforces_order(client):
    h = _auth_headers(client)
    pid = _pipe(client, h)
    r = client.post(f"/api/engineering/{pid}/advance",
                    json={"stage": "design", "artifact": "x"}, headers=h)
    assert r.status_code == 422
    r = client.post(f"/api/engineering/{pid}/advance",
                    json={"stage": "grill", "artifact": "grill"}, headers=h)
    assert r.status_code == 200, r.text
