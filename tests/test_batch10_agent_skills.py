"""Batch 10 (Agent Runtime + Skills) tests.

Covers: pi steering/abort + tool-call dependency planning + turn
contract + structured compaction/branch resume; async approval tray
(exactly-once decisions); per-run sandbox default + verify gate;
subagent-per-task graph + hive drain/escalation + ask/gate nodes +
worktree handoff + propose-from-eval; supervised external drivers;
severity-tier review schema + persona roster (incl. coordinator);
skill frontmatter contract (allowed_tools/bootstrap/last_reviewed),
bootstrap approval gating, scripts manifest, reverse-skill drafts,
trigger-accuracy + blind A/B + failing-baseline gates, new packs;
and the runtime/skill API endpoints (live TestClient flow, Batch 9
pattern). No live model, no live network, no Docker claim.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.agent_runtime.approval import AsyncApprovalChannel  # noqa: E402
from backend.agent_runtime.drivers import LocalCommandDriver, detect_runtime  # noqa: E402
from backend.agent_runtime.loop import (  # noqa: E402
    BranchStore,
    RunAborted,
    SteeringQueue,
    TurnContract,
    compact,
    independent_calls,
    plan_tool_calls,
)
from backend.agent_runtime.orchestration import (  # noqa: E402
    AskNode,
    GateNode,
    TaskGraph,
    drain_inbox,
    escalate_critical_only,
    four_stop_rule,
    handoff_to_worktree,
    propose_from_eval,
)
from backend.agent_runtime.sandbox import (  # noqa: E402
    detect_test_command,
    run_verify_gate,
)
from backend.skills.bootstrap import (  # noqa: E402
    declared_scripts,
    resolve_bootstrap_body,
    validate_bootstrap_command,
)
from backend.skills.creator import (  # noqa: E402
    evaluate_blind,
    publish_skill,
    trigger_eval,
)
from backend.skills.reverse import (  # noqa: E402
    propose_skill_from_transcript,
    propose_skills_from_runs,
)
from backend.skills.verify import run_skill_checks  # noqa: E402
from backend.teams.review_schema import parse_review_checklist, review_report  # noqa: E402


def _skill_md(tmp_path, name="demo-skill", extra="", body="Do the thing.\n"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\n"
        f"id: {name}\n"
        "name: Demo Skill\n"
        "category: engineering\n"
        "invocation: both\n"
        "description: Demo skill for batch ten tests.\n"
        f"{extra}"
        "---\n\n" + body, encoding="utf-8")
    return d


# ------------------------------------------------------------- loop (pi)
def test_steering_queue_drain_and_abort():
    q = SteeringQueue()
    q.steer("also check the tests")
    q.steer("and keep it small")
    assert q.drain() == ["also check the tests", "and keep it small"]
    assert q.drain() == []
    with pytest.raises(ValueError):
        q.steer("   ")
    q.abort("user stopped it")
    assert q.aborted and q.abort_reason == "user stopped it"
    with pytest.raises(RunAborted):
        q.check_abort()


def test_plan_tool_calls_parallel_by_default_and_sequential_on_reads():
    groups = plan_tool_calls([
        {"id": "a", "name": "read_file"},
        {"id": "b", "name": "list_files"},
    ])
    assert len(groups) == 1  # parallel by default
    groups = plan_tool_calls([
        {"id": "a", "name": "read_file"},
        {"id": "b", "name": "edit_file", "reads": ["a"]},
        {"id": "c", "name": "run_bash", "reads": ["b"]},
    ])
    assert [[c.id for c in g] for g in groups] == [["a"], ["b"], ["c"]]


def test_plan_tool_calls_rejects_unknown_dep_duplicate_and_cycle():
    with pytest.raises(ValueError, match="unknown call"):
        plan_tool_calls([{"id": "a", "name": "x", "reads": ["ghost"]}])
    with pytest.raises(ValueError, match="duplicate"):
        plan_tool_calls([{"id": "a", "name": "x"}, {"id": "a", "name": "y"}])
    with pytest.raises(ValueError, match="cycle"):
        plan_tool_calls([{"id": "a", "name": "x", "reads": ["b"]},
                         {"id": "b", "name": "y", "reads": ["a"]}])


def test_independent_calls_excludes_blocked_and_dependents():
    calls = [{"id": "a", "name": "write_file"},
             {"id": "b", "name": "read_file", "reads": ["a"]},
             {"id": "c", "name": "list_files"}]
    free = independent_calls(calls, {"a"})
    assert [c.id for c in free] == ["c"]  # b reads blocked a, so it waits too


def test_turn_contract_freeze_and_no_substitution():
    contract = TurnContract(required=["read_file"], offered=["read_file", "list_files"],
                            executable=["read_file", "list_files", "web_search"])
    assert contract.check("read_file")[0] == "ok"
    status, detail = contract.check("web_search")
    assert status == "denied"
    # Required-but-unavailable: stop and say so, never substitute.
    # (Freeze rejects offered-not-executable at construction, so build
    # a valid contract first and narrow it to exercise check() semantics.)
    contract2 = TurnContract(required=["code_map"], offered=["code_map"],
                             executable=["code_map"])
    contract2.executable = ["read_file"]
    status, detail = contract2.check("code_map")
    assert status == "unavailable" and "substitute" in detail
    with pytest.raises(ValueError, match="required not subset"):
        TurnContract(required=["x"], offered=["y"], executable=["y"])


def test_compact_summary_and_branch_resume():
    summary = compact([{"role": "user", "content": "Fix the parser bug"},
                       {"role": "assistant", "content": "Fixed it, tests pass"}],
                      read_files=["b.py", "a.py", "a.py"], modified_files=["a.py"])
    assert "Fix the parser bug" in summary.summary
    assert summary.read_files == ["a.py", "b.py"]
    assert summary.modified_files == ["a.py"]
    store = BranchStore()
    store.save(summary)
    child = store.resume(summary.branch_id,
                         new_messages=[{"role": "user", "content": "Also handle empty input"}],
                         modified_files=["c.py"])
    assert child.parent_branch_id == summary.branch_id
    assert "c.py" in child.modified_files and "a.py" in child.modified_files
    assert "Resumed from branch" in child.summary
    with pytest.raises(ValueError, match="unknown branch"):
        store.resume("br-nope")


# ------------------------------------------------------- async approval
def test_async_approval_channel_exactly_once_and_sources():
    channel = AsyncApprovalChannel()
    item = channel.defer("run-1", "run_bash", args={"cmd": "rm -rf /"}, call_id="call-9")
    assert item.status == "pending"
    assert channel.pending("run-1")[0].id == item.id
    assert channel.decide(item.id, True, source="paired-device")["ok"] is True
    again = channel.decide(item.id, False, source="chat")
    assert again["ok"] is False and "already" in again["error"]
    bad = channel.decide("def-nope", True)
    assert bad["ok"] is False
    item2 = channel.defer("run-1", "write_file")
    assert channel.decide(item2.id, True, source="carrier-pigeon")["ok"] is False


# ------------------------------------------------------------- sandbox
def test_detect_test_command_pytest_makefile_and_none(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.pytest]\n', encoding="utf-8")
    assert detect_test_command(tmp_path)["command"] == ["python", "-m", "pytest", "-q"]
    other = tmp_path / "mk"
    other.mkdir()
    (other / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    assert detect_test_command(other)["command"] == ["make", "test"]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert detect_test_command(empty)["command"] is None


def test_verify_gate_pass_and_honest_no_command(tmp_path):
    ok = run_verify_gate(tmp_path, command=[sys.executable, "-c", "print('gate-ok')"],
                         docker_present=False)
    assert ok["passed"] is True and "gate-ok" in ok["stdout_tail"]
    assert ok["isolation"] == "workspace-fallback" and ok["warning"]
    empty = tmp_path / "empty"
    empty.mkdir()
    missing = run_verify_gate(empty, docker_present=False)
    assert missing["passed"] is False and missing["command"] is None


# --------------------------------------------------------- orchestration
def test_task_graph_frontier_order_review_and_branch_review():
    graph = TaskGraph([
        {"id": "research", "title": "Research"},
        {"id": "draft", "title": "Draft", "depends_on": ["research"]},
        {"id": "review", "title": "Review", "depends_on": ["draft"]},
    ])
    assert [t.id for t in graph.frontier()] == ["research"]
    assert graph.execution_order() == ["research", "draft", "review"]
    graph.mark("research", "done")
    assert [t.id for t in graph.frontier()] == ["draft"]
    graph.mark("draft", "review")
    graph.review_task("draft", {"verdict": "request-changes", "note": "missing test"})
    assert graph.tasks["draft"].status == "pending"  # fresh context on retry
    graph.review_task("draft", {"verdict": "approve"})
    graph.mark("research", "done")
    graph.mark("review", "done")
    review = graph.branch_review()
    assert review["complete"] is True
    with pytest.raises(ValueError, match="unknown task"):
        TaskGraph([{"id": "a", "title": "A", "depends_on": ["ghost"]}])
    with pytest.raises(ValueError, match="cycle"):
        TaskGraph([{"id": "a", "title": "A", "depends_on": ["b"]},
                   {"id": "b", "title": "B", "depends_on": ["a"]}])


def test_four_stop_rule_only_four_stop():
    assert four_stop_rule("security-sensitive")["stop"] is True
    assert four_stop_rule("unclear wording")["stop"] is False


def test_hive_drain_and_critical_only_escalation():
    drained = drain_inbox([{"id": "m1"}, {"id": "m2"}, {"no": "id"}])
    assert drained["drained"] == ["m1", "m2"] and drained["finished"] is False
    assert drain_inbox([{"id": "m1"}])["finished"] is True
    out = escalate_critical_only([
        {"title": "status update", "body": "done"},
        {"title": "Delete production data?", "body": "confirm scope"},
        {"title": "Spend approval", "body": "budget $500"},
    ])
    assert len(out["handled"]) == 1 and len(out["escalated"]) == 2


def test_ask_and_gate_nodes():
    ask = AskNode(id="ask-1", question="Which model?")
    assert ask.to_dict()["answered"] is False
    assert ask.answer_question("the cheap one")["answered"] is True
    gate = GateNode(id="gate-1", rule="human approves the plan")
    assert gate.open is False
    gate.decide("pass", decided_by="human")
    assert gate.open is True
    with pytest.raises(ValueError):
        GateNode(id="g", rule="r").decide("maybe")


def test_propose_from_eval_never_applies():
    proposal = propose_from_eval({"score": 0.5}, {"score": 0.8},
                                 {"model": "new-model"})
    assert proposal["applied"] is False and proposal["recommendation"] == "adopt"
    assert abs(proposal["delta"] - 0.3) < 1e-9
    reject = propose_from_eval({"passed": 4, "cases": 5}, {"passed": 3, "cases": 5}, {})
    assert reject["recommendation"].startswith("reject")


def test_handoff_to_worktree_fresh_context(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t",
                    "-c", "user.email=t@t", "commit", "-qm", "init"], check=True)
    out = handoff_to_worktree(repo, tmp_path / "wts", "run-1")
    assert out["fresh_context_required"] is True
    assert Path(out["worktree"]).is_dir()
    assert (Path(out["worktree"]) / "README.md").is_file()


# --------------------------------------------------------------- drivers
def test_driver_detect_and_lifecycle():
    missing = detect_runtime("definitely-not-a-real-binary-xyz")
    assert missing["available"] is False
    driver = LocalCommandDriver(name="echo-driver")
    started = driver.start([sys.executable, "-c", "print('driver-hi')"])
    assert started["ok"] is True
    assert driver.health()["state"] in ("running", "completed")
    tail = driver.log_tail()
    assert "driver-hi" in tail or "still running" in tail
    killed = driver.kill()
    assert killed["ok"] is True


# --------------------------------------------------------- review schema
def test_review_schema_parses_tiers_and_blocks():
    text = ("🔴 blocker: SQL injection in login — fix with parameters\n"
            "🟡 suggestion: rename helper — clearer name\n"
            "💭 nit: trailing whitespace\n"
            "Some untiered prose that must not count.\n"
            "must: second blocker line\n")
    findings = parse_review_checklist(text)
    assert [f.severity for f in findings] == ["blocker", "suggestion", "nit", "blocker"]
    report = review_report(findings)
    assert report["verdict"] == "blocked" and report["counts"]["blocker"] == 2
    assert review_report(parse_review_checklist("💭 nit: polish"))["verdict"] == "pass"


def test_persona_roster_valid_and_coordinator_present():
    from backend.persona_registry import load_personas, validate_roster
    report = validate_roster()
    assert report["errors"] == [], report["errors"]
    personas = load_personas()
    assert "coordinator" in personas
    assert personas["coordinator"].method == "coordinate"


# ------------------------------------------------------------ skill system
def test_registry_parses_batch10_frontmatter(tmp_path):
    d = _skill_md(tmp_path, extra=(
        "allowed_tools: [read_file, list_files]\n"
        "compatibility: sangam>=1.0\n"
        "bootstrap_command: python scripts/guide.py\n"
        "last_reviewed: 2026-10-26\n"))
    from backend.skills.registry import SkillRegistry
    reg = SkillRegistry(skills_root=tmp_path)
    skill = reg.get("demo-skill")
    assert skill is not None
    assert skill.allowed_tools == ["read_file", "list_files"]
    assert skill.compatibility == "sangam>=1.0"
    assert skill.bootstrap_command == "python scripts/guide.py"
    assert skill.last_reviewed == "2026-10-26"


def test_bootstrap_validation_and_approval_gate(tmp_path):
    ok, _ = validate_bootstrap_command("python scripts/guide.py")
    assert ok is True
    bad, reason = validate_bootstrap_command("python guide.py; rm -rf /")
    assert bad is False and ";" in reason
    skill_dir = tmp_path / "boot"
    skill_dir.mkdir()
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "guide.py").write_text("print('BOOTSTRAP BODY')\n", encoding="utf-8")
    cmd = f"{sys.executable} scripts/guide.py"
    assert resolve_bootstrap_body(skill_dir, cmd)["status"] == "approval_needed"
    denied = resolve_bootstrap_body(skill_dir, cmd, approval={"decision": False})
    assert denied["status"] == "denied"
    got = resolve_bootstrap_body(skill_dir, cmd, approval={"decision": True})
    assert got["status"] == "ok" and "BOOTSTRAP BODY" in got["body"]
    (scripts / "evil.py").write_text("print('os.system')\n", encoding="utf-8")
    rejected = resolve_bootstrap_body(
        skill_dir, f"{sys.executable} scripts/evil.py", approval={"decision": True})
    assert rejected["status"] == "rejected"


def test_scripts_manifest_declared_and_missing(tmp_path):
    d = tmp_path / "man"
    (d / "scripts").mkdir(parents=True)
    (d / "scripts" / "draw.py").write_text("print(1)\n", encoding="utf-8")
    (d / "scripts.json").write_text('{"scripts": ["draw.py", "gone.py"]}',
                                    encoding="utf-8")
    entries = declared_scripts(d)
    assert entries[0] == {"name": "draw.py", "declared": True, "exists": True}
    assert entries[1]["exists"] is False
    (d / "scripts.json").unlink()
    assert declared_scripts(d) == [{"name": "draw.py", "declared": False,
                                    "exists": True}]


def test_reverse_skill_draft_and_runs_clustering():
    transcript = [
        {"role": "user", "content": "Please review the auth module for security issues"},
        {"role": "assistant", "content": "Here is the review."},
        {"role": "user", "content": "Please review the auth module again after the fix"},
    ]
    draft = propose_skill_from_transcript(transcript)
    assert draft["status"].startswith("draft")
    assert any("review" in t for t in draft["triggers"])
    assert draft["evidence"]["user_turns"] == 2
    with pytest.raises(ValueError):
        propose_skill_from_transcript([])
    drafts = propose_skills_from_runs([
        {"id": "r1", "title": "Weekly database backup report"},
        {"id": "r2", "title": "Weekly database backup check"},
        {"id": "r3", "title": "Unrelated poem"},
    ])
    assert drafts and drafts[0]["evidence"]["runs"] == 2
    assert propose_skills_from_runs([{"id": "r1", "title": "Solo run"}]) == []


def test_trigger_eval_and_blind_gate_and_baseline_gate(tmp_path):
    d = _skill_md(tmp_path, name="bugfixer", extra=(
        'description: Bug fixing procedure for broken code paths.\n'
        'triggers: ["fix the bug"]\n'))
    # NOTE: _skill_md writes a fixed description line first; the extra
    # description key duplicates it — YAML keeps the last, which is the
    # intended one for this eval.
    report = trigger_eval(d, ["please fix the bug in auth"],
                          ["write a poem about autumn"])
    assert report["positive_fired"] == 1 and report["negative_fired"] == 0
    assert report["passed"] is True
    blind = evaluate_blind(
        d, [{"prompt": "p", "expected_substrings": ["done-marker"]}],
        runner_with=lambda prompt, sd: "all good done-marker",
        runner_without=lambda prompt, sd: "nothing here")
    assert blind["passed"] is True and blind["with_passed"] == 1
    equal = evaluate_blind(
        d, [{"prompt": "p", "expected_substrings": ["done-marker"]}],
        runner_with=lambda prompt, sd: "done-marker",
        runner_without=lambda prompt, sd: "done-marker")
    assert equal["passed"] is False  # no improvement, no publish
    missing = evaluate_blind(d, [{"prompt": "p", "expected_substrings": ["x"]}])
    assert missing["passed"] is False
    with pytest.raises(ValueError, match="baseline"):
        publish_skill(d, {"publishable": True}, require_failing_baseline=True,
                      baseline_report={"total": 2, "without_passed": 2})
    with pytest.raises(ValueError, match="not passed"):
        publish_skill(d, {"publishable": False})


def test_verify_batch10_checks(tmp_path):
    bad_tools = _skill_md(tmp_path, name="badtools",
                          extra="allowed_tools: not-a-list\n")
    checks = {c["check"]: c for c in run_skill_checks(bad_tools)["checks"]}
    assert checks["allowed-tools"]["status"] == "failed"
    bad_boot = _skill_md(tmp_path, name="badboot",
                         extra="bootstrap_command: 'echo hi | tee x'\n")
    checks = {c["check"]: c for c in run_skill_checks(bad_boot)["checks"]}
    assert checks["bootstrap-command"]["status"] == "failed"
    wordy = _skill_md(tmp_path, name="wordy",
                      extra="description: '" + "word " * 120 + "'\n")
    checks = {c["check"]: c for c in run_skill_checks(wordy)["checks"]}
    assert checks["description-words"]["status"] == "warning"
    assert run_skill_checks(wordy)["failed"] == 0  # warning is not a failure


def test_new_packs_and_skills_pass_checks():
    from backend.skills.packs import list_packs
    packs = {p.name: p for p in list_packs()}
    assert "taste-quality" in packs and packs["taste-quality"].skills == [
        "design-taste", "review-checklist"]
    assert "coding-guidelines" in packs["engineering"].skills
    packs_root = Path(__file__).resolve().parents[1] / "mainfiles" / "backend" / "skills" / "packs"
    for skill_dir in [
            packs_root / "engineering" / "skills" / "coding-guidelines",
            packs_root / "taste-quality" / "skills" / "design-taste",
            packs_root / "taste-quality" / "skills" / "review-checklist"]:
        report = run_skill_checks(skill_dir)
        assert report["failed"] == 0, (skill_dir, report["checks"])


# ------------------------------------------------------------------- API
import backend.api_routes.agent_runtime_routes  # noqa: E402,F401
import backend.api_routes.skills_v2_routes  # noqa: E402,F401
from backend.config import settings  # noqa: E402
from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    os.environ["CHROMA_DB_PATH"] = str(tmp_path / "chroma")
    import backend.rag as rag_mod
    importlib.reload(rag_mod)
    rag_mod._client = None
    rag_mod._collection = None
    from backend import memory as memory_mod
    memory_mod.reset_memory_for_testing()
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b10.db")
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
    creds = {"username": "b10_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def test_api_runtime_plan_contract_compact_and_resume(client):
    h = _auth_headers(client)
    r = client.post("/api/agent/runtime/plan", json={"tool_calls": [
        {"id": "a", "name": "read_file"},
        {"id": "b", "name": "edit_file", "reads": ["a"]}]}, headers=h)
    assert r.status_code == 200
    assert [[c["id"] for c in g] for g in r.json()["groups"]] == [["a"], ["b"]]
    r = client.post("/api/agent/runtime/contract", json={
        "required": ["read_file"], "offered": ["read_file"],
        "executable": ["read_file"]}, headers=h)
    assert r.status_code == 200
    r = client.post("/api/agent/runtime/contract", json={
        "required": ["x"], "offered": ["y"], "executable": ["y"]}, headers=h)
    assert r.status_code == 422
    r = client.post("/api/agent/runtime/compact", json={
        "messages": [{"role": "user", "content": "Do thing"}],
        "read_files": ["a.py"], "modified_files": []}, headers=h)
    assert r.status_code == 200
    branch_id = r.json()["branch_id"]
    r = client.post(f"/api/agent/runtime/branches/{branch_id}/resume",
                    json={"messages": [{"role": "user", "content": "More"}]},
                    headers=h)
    assert r.status_code == 200
    assert r.json()["parent_branch_id"] == branch_id
    r = client.post("/api/agent/runtime/branches/br-nope/resume",
                    json={"messages": []}, headers=h)
    assert r.status_code == 404


def test_api_steering_tray_flow_hive_drivers_and_eval(client):
    h = _auth_headers(client)
    r = client.post("/api/agent/runtime/runs/run-9/steer",
                    json={"message": "also run tests"}, headers=h)
    assert r.status_code == 200 and r.json()["queued"] == 1
    r = client.post("/api/agent/runtime/approvals/defer",
                    json={"run_id": "run-9", "tool": "run_bash",
                          "args": {"cmd": "pytest"}}, headers=h)
    assert r.status_code == 200
    approval_id = r.json()["id"]
    r = client.get("/api/agent/runtime/approvals/tray", headers=h)
    assert any(t["id"] == approval_id and t["status"] == "pending"
               for t in r.json()["tray"])
    r = client.post(f"/api/agent/runtime/approvals/{approval_id}/decide",
                    json={"approved": True, "source": "paired-device"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = client.post(f"/api/agent/runtime/approvals/{approval_id}/decide",
                    json={"approved": False}, headers=h)
    assert r.status_code == 422  # exactly-once
    r = client.post("/api/agent/runtime/flow", json={"tasks": [
        {"id": "a", "title": "A"}, {"id": "b", "title": "B", "depends_on": ["a"]}]},
        headers=h)
    assert r.status_code == 200
    assert r.json()["execution_order"] == ["a", "b"]
    r = client.post("/api/agent/runtime/hive/drain", json={"inbox": [
        {"id": "m1"}, {"title": "Delete production data?"}]}, headers=h)
    assert r.status_code == 200 and r.json()["drained"] == ["m1"]
    assert len(r.json()["escalated_critical"]) == 1
    r = client.get("/api/agent/runtime/drivers", headers=h)
    assert r.status_code == 200 and r.json()["drivers"]
    r = client.post("/api/agent/runtime/eval/propose", json={
        "eval_before": {"score": 0.4}, "eval_after": {"score": 0.9},
        "change": {"prompt": "shorter"}}, headers=h)
    assert r.json()["applied"] is False


def test_api_sandbox_previews_and_skill_drafts(client, tmp_path):
    h = _auth_headers(client)
    ws = tmp_path / "ws"
    ws.mkdir()
    r = client.post("/api/agent/runtime/sandbox",
                    json={"workspace": str(ws), "run_id": "r1"}, headers=h)
    assert r.status_code == 200 and r.json()["executed"] is False
    r = client.post("/api/agent/runtime/sandbox/verify",
                    json={"workspace": str(ws)}, headers=h)
    assert r.status_code == 200 and r.json()["executed"] is False
    r = client.post("/api/skills/propose-from-transcript", json={"transcript": [
        {"role": "user", "content": "Review the auth module for security"},
        {"role": "user", "content": "Review the auth module again"}]}, headers=h)
    assert r.status_code == 200 and r.json()["status"].startswith("draft")
    r = client.post("/api/skills/drafts/save", json={
        "name": "b10-draft", "description": "Draft from batch ten tests",
        "body": "Do the reviewed thing, then verify."}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["checks"]["failed"] == 0
    draft_dir = Path(r.json()["saved"]).parent
    assert draft_dir.is_dir()
    shutil.rmtree(draft_dir)  # drafts are test artefacts, not repo content
    r = client.get("/api/skills/packs", headers=h)
    assert r.status_code == 200
    assert any(p["name"] == "taste-quality" for p in r.json())
