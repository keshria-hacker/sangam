"""Wave-2 deep-read tests: Teams v2 + security execution + council +
hook monitor + phone approval + Orca residue (worktrees).

All LLM-dependent engines run on injected fake completers — no model,
no network, no Docker. The one live-API test patches the sandboxed
runner (like the batch-2 browser test patches its driver).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.council_mode import (  # noqa: E402
    OutcomeLedger,
    build_verdict,
    check_cross_examination,
    anonymize,
    deliberate,
    enforcement_scan,
    parse_stance,
    tally,
    CouncilVote,
)
from backend.hive import Breaker, Hive  # noqa: E402
from backend.hook_monitor import (  # noqa: E402
    ApprovalQueue,
    cap_fields,
    normalize_event_name,
    relay_event,
    relay_stdin_line,
)
from backend.phone_approval import PhoneApprovalStore, request_fingerprint  # noqa: E402
from backend.security_catalog import (  # noqa: E402
    catalog_entry,
    execution_command,
    passive_only_reason,
)
from backend.teams import definitions as team_defs  # noqa: E402
from backend.teams.debate import estimate_debate_cost, run_debate  # noqa: E402
from backend.teams.personas import (  # noqa: E402
    load_personas,
    parse_persona_file,
    suggest_personas,
    validate_personas,
)
from backend.teams.threads import TeamThread, ThreadBounds, run_thread  # noqa: E402
from backend import worktrees  # noqa: E402


# ---------------------------------------------------------------- council

def test_tally_exact_arithmetic_domain_and_confidence():
    votes = [
        CouncilVote(member="skeptic", stance="ship", confidence="high"),
        CouncilVote(member="builder", stance="delay", confidence="med"),
        CouncilVote(member="pragmatist", stance="ship", confidence="low"),
    ]
    # Domain seat = skeptic (1.5 base): ship = 1.5*1.0 + 1.0*0.5 = 2.0;
    # delay = 1.0*0.75 = 0.75; denominator = 1.5+1+1 = 3.5; bar = 2.333.
    result = tally(votes, domain_seat="skeptic")
    assert result.totals["ship"] == pytest.approx(2.0)
    assert result.totals["delay"] == pytest.approx(0.75)
    assert result.denominator == pytest.approx(3.5)
    assert result.consensus is False  # 2.0 < 2/3 * 3.5: a split, not consensus
    assert result.winner == "ship"


def test_tally_abstainer_raises_bar_and_missing_stance_never_inferred():
    votes = [
        CouncilVote(member="skeptic", stance="ship", confidence="high"),
        CouncilVote(member="builder", stance="ship", confidence="high"),
        parse_stance("A long essay with no stance line at all.", "pragmatist"),
    ]
    assert votes[2].stance is None and votes[2].missing_stance is True
    result = tally(votes)
    # Denominator still 3.0 (abstainer counts in full); 2.0 >= 2.0 clears.
    assert result.denominator == pytest.approx(3.0)
    assert result.consensus is True


def test_tally_dealbreaker_survives_even_when_outvoted():
    votes = [
        CouncilVote(member="skeptic", stance="delay", confidence="high", dealbreaker=True),
        CouncilVote(member="builder", stance="ship", confidence="high"),
        CouncilVote(member="pragmatist", stance="ship", confidence="high"),
    ]
    result = tally(votes)
    assert result.consensus is True and result.winner == "ship"
    assert "skeptic" in result.dealbreakers
    verdict = build_verdict("Ship?", result, minority_report="Delay: the data is thin.")
    assert "Minority Report" in verdict and "Delay: the data is thin." in verdict


def test_split_verdict_never_manufactures_consensus():
    votes = [
        CouncilVote(member="skeptic", stance="ship", confidence="high"),
        CouncilVote(member="builder", stance="delay", confidence="high"),
        CouncilVote(member="pragmatist", stance="delay", confidence="low"),
    ]
    result = tally(votes)
    assert result.consensus is False
    verdict = build_verdict("Ship?", result)
    assert "No consensus reached" in verdict
    assert "Verdict: delay" not in verdict


def test_cross_examination_requires_both_parts():
    ok = check_cross_examination(
        "I disagree with Member B because its cost claim is unproven; "
        "it strengthened my view by naming the rollback path.")
    assert ok["ok"] is True
    assert check_cross_examination("I disagree with Member B. Full stop.")["ok"] is False
    assert check_cross_examination("This strengthened my view a lot.")["ok"] is False


def test_anonymize_strips_self_references():
    anon, mapping = anonymize({"skeptic": "As skeptic I doubt this.",
                               "builder": "The skeptic is wrong."})
    # Labels are assigned in sorted-member order: builder=A, skeptic=B.
    assert mapping["builder"] == "Member A" and mapping["skeptic"] == "Member B"
    assert "skeptic" not in anon["Member B"].lower()
    assert "Member B" in anon["Member B"]


def test_enforcement_scan_tags():
    votes = [CouncilVote(member="a", stance="x", confidence="high"),
             CouncilVote(member="b", stance="x", confidence="high"),
             CouncilVote(member="c", stance="x", confidence="high")]
    scan = enforcement_scan({"a": "one"}, {"a": "I disagree with Member B", "b": "agree", "c": "agree"}, votes)
    assert scan["dissent_quota_met"] is False  # only 1 dissenter
    assert scan["agreement_over_70pct"] is True


def test_outcome_ledger_original_is_immutable(tmp_path):
    ledger = OutcomeLedger(tmp_path / "ledger.json")
    entry = ledger.record("Ship in Q1", "owner-1", "2026-12-01", "If churn > 5% by 2026-12-01, reverse.")
    marked = ledger.mark(entry.id, "reversed", "Churn hit 7%.")
    assert marked.status == "reversed"
    assert marked.original_prediction == "Ship in Q1"
    assert marked.prediction == "Ship in Q1"  # marking never rewrites the prediction
    reloaded = OutcomeLedger(tmp_path / "ledger.json")
    assert reloaded.entries[entry.id].status == "reversed"
    with pytest.raises(ValueError):
        ledger.mark(entry.id, "bogus")
    with pytest.raises(ValueError):
        ledger.mark("nope", "confirmed")


async def _council_fake(messages):
    system = messages[0]["content"]
    user = messages[1]["content"]
    lens = "skeptic" if "Skeptic" in system else ("builder" if "Builder" in system else "pragmatist")
    if "final position" in user:
        stance = {"skeptic": "delay", "builder": "ship", "pragmatist": "ship"}[lens]
        conf = {"skeptic": "high", "builder": "med", "pragmatist": "low"}[lens]
        deal = "yes" if lens == "skeptic" else "no"
        return f"Final: {stance}.\nSTANCE: {stance} | CONFIDENCE: {conf} | DEALBREAKER: {deal}"
    if "Anonymized" in user:
        return (f"I disagree with Member B because its claim is unproven; "
                f"it strengthened my view by naming a rollback path. Restated: see blind.")
    return f"Blind analysis from {lens}."


@pytest.mark.asyncio
async def test_deliberate_runs_blind_cross_stance_and_splits():
    result = await deliberate("Ship?", list(team_defs.COUNCIL_LENSES), _council_fake)
    assert set(result.round1) == {"skeptic", "builder", "pragmatist"}
    assert set(result.round2) == {"skeptic", "builder", "pragmatist"}
    assert result.tally.consensus is False  # ship 1.25 vs delay 1.0, bar 2.0
    assert "No consensus reached" in result.verdict
    assert "skeptic" in result.tally.dealbreakers


# -------------------------------------------------------------------- hive

def _hive(tmp_path):
    hive = Hive(tmp_path / "hive")
    hive.create_agent("god", "God orchestrator")
    hive.create_agent("alice", "Worker", identity="# Alice\n")
    hive.create_agent("bob", "Worker")
    return hive


def test_hive_human_resolves_to_god_and_bounce_never_drops(tmp_path):
    hive = _hive(tmp_path)
    hive.send_message("alice", "human", "Question", "Should I proceed?", reply_expected=True)
    hive.send_message("alice", "ghost", "Hello", "Anyone there?")
    summary = hive.route_messages()
    assert summary["delivered"] >= 1 and summary["bounced"] == 1
    god_inbox = [m.subject for m in hive.inbox_messages("god")]
    assert "Question" in god_inbox
    assert any(s.startswith("[bounced]") for s in god_inbox)
    assert not hive.outbox_messages("alice")  # drained


def test_hive_archived_recipient_filed_and_sender_notified(tmp_path):
    hive = _hive(tmp_path)
    hive.archive_agent("bob")
    hive.send_message("alice", "bob", "Task", "Do this", reply_expected=True)
    summary = hive.route_messages()
    assert summary["filed_archived"] == 1 and summary["archived_notified"] == 1
    assert [m.subject for m in hive.inbox_messages("bob")] == ["Task"]
    assert any("archived" in m.subject.lower() for m in hive.inbox_messages("alice"))


def test_hive_broadcast_skips_archived_and_send_only(tmp_path):
    hive = _hive(tmp_path)
    hive.archive_agent("bob")
    hive.send_message("god", "*", "Broadcast", "Hi all", broadcast=True)
    hive.route_messages()
    assert any(m.subject == "Broadcast" for m in hive.inbox_messages("alice"))
    assert not [m for m in hive.inbox_messages("bob") if m.subject == "Broadcast"]


def test_hive_closing_time_ack_protocol(tmp_path):
    hive = _hive(tmp_path)
    hive.closing_time_broadcast()
    assert any(m.subject == "CLOSING TIME" for m in hive.inbox_messages("alice"))
    hive.send_message("alice", "god", "CLOSING-TIME-ACK", "done")
    hive.send_message("bob", "god", "CLOSING-TIME-ACK", "done")
    hive.route_messages()
    status = hive.collect_acks()
    assert status["all_acked"] is True and status["god_complete"] is False
    hive.send_message("god", "god", "COMPLETE", "all done")
    hive.route_messages()
    assert hive.collect_acks()["god_complete"] is True


def test_breaker_one_level_per_beat_and_hard_stop_off_caps(tmp_path):
    breaker = Breaker(hard_stop=False)
    assert breaker.beat(unhealthy=True) == "steering"
    assert breaker.beat(unhealthy=True) == "constrained"
    assert breaker.beat(unhealthy=True) == "constrained"  # capped, never kills
    assert breaker.beat(unhealthy=False) == "steering"  # one level per healthy beat
    hot = Breaker(hard_stop=True)
    for _ in range(3):
        hot.beat(unhealthy=True)
    assert hot.level == "stopped" and hot.stopped is True


# ------------------------------------------------------------------ threads

async def _thread_fake(messages):
    return "member contribution"


@pytest.mark.asyncio
async def test_thread_resumes_from_persisted_entries(tmp_path):
    specs = {s.id: s for s in team_defs.COUNCIL_LENSES}
    thread = TeamThread("t1", tmp_path / "threads" / "t1", "Do X",
                        ["skeptic", "builder"], ThreadBounds(max_rounds=2, max_cost_usd=100))
    out = await run_thread(thread, specs, _thread_fake, "Synthesize.")
    assert out["stop_reason"] == "round_done" and out["rounds_done"] == 1
    resumed = TeamThread("t1", tmp_path / "threads" / "t1", "Do X",
                         ["skeptic", "builder"], ThreadBounds(max_rounds=2, max_cost_usd=100))
    assert resumed.rounds_done == 1 and len(resumed.entries) == len(thread.entries)
    out2 = await run_thread(resumed, specs, _thread_fake, "Synthesize.")
    assert out2["stop_reason"] == "bound:rounds"


def test_thread_bounds_reject_over_cap():
    with pytest.raises(ValueError):
        ThreadBounds(max_members=9).validate()
    with pytest.raises(ValueError):
        TeamThread("t", "/tmp/x", "task", ["a"] * 9)


# ------------------------------------------------------------------- debate

def test_debate_estimate_and_caps():
    est = estimate_debate_cost(3, 2, cost_per_call_usd=0.10)
    assert est.estimated_calls == 7 and est.estimated_cost_usd == pytest.approx(0.70)
    with pytest.raises(ValueError):
        estimate_debate_cost(9, 2)
    with pytest.raises(ValueError):
        estimate_debate_cost(2, 7)


@pytest.mark.asyncio
async def test_debate_transcript_fed_and_hard_stop(tmp_path):
    from backend.teams.personas import Persona
    personas = [Persona(slug="a", name="A", description="d", method="m1", system_prompt="You are A."),
                Persona(slug="b", name="B", description="d", method="m2", system_prompt="You are B.")]
    seen: list[str] = []

    async def fake(messages):
        seen.append(messages[1]["content"])
        return "reply"

    result = await run_debate("Topic?", personas, 2, fake, "Synthesize.")
    assert len(result.transcript) == 4
    assert "Transcript so far" in seen[1]  # later speakers see earlier ones
    assert result.synthesis == "reply" and result.stopped is False
    flag = threading.Event()
    flag.set()
    stopped = await run_debate("Topic?", personas, 2, fake, "Synthesize.", stop_flag=flag)
    assert stopped.stopped is True and stopped.transcript == []


# ------------------------------------------------------------------ personas

def test_persona_file_parse_validate_suggest(tmp_path):
    d = tmp_path / "personas"
    d.mkdir()
    (d / "alpha.md").write_text("---\nname: Alpha\ndescription: cost and risk\nmethod: audit\n---\n# Alpha\n", encoding="utf-8")
    (d / "beta.md").write_text("---\nname: Beta\ndescription: speed first\nmethod: build\n---\n# Beta\n", encoding="utf-8")
    personas = load_personas(d)
    assert validate_personas(personas) == []
    assert parse_persona_file(d / "alpha.md").method == "audit"
    assert suggest_personas("cost risk budget", personas)[0].slug == "alpha"
    (d / "gamma.md").write_text("---\nname: Gamma\ndescription: x\nmethod: audit\n---\n# G\n", encoding="utf-8")
    assert any("duplicate method" in p for p in validate_personas(load_personas(d)))
    (d / "bad.md").write_text("---\nname: Bad\n---\n# Bad\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_personas(d)


# ------------------------------------------------------------- hook monitor

def test_hook_queue_fifo_stale_guard_and_max_pending(tmp_path):
    queue = ApprovalQueue(tmp_path / "q.json")
    first = queue.enqueue("s1", "claude", "Bash", "rm -rf /tmp/x")
    second = queue.enqueue("s1", "claude", "Bash", "ls")
    assert queue.head().id == first.id
    stale = queue.decide(second.id, "allow")
    assert stale["ok"] is False and stale["error"] == "stale"
    assert queue.get(first.id).status == "pending"
    assert queue.decide(first.id, "allow")["ok"] is True
    assert queue.head().id == second.id
    for i in range(5):
        queue.enqueue("s1", "claude", "Bash", f"cmd {i}")
    overflow = queue.enqueue("s1", "claude", "Bash", "one too many")
    assert overflow.status == "fallback"
    reloaded = ApprovalQueue(tmp_path / "q.json")
    assert reloaded.head().id == second.id  # persisted across restart


def test_hook_relay_never_blocks_and_normalizes():
    assert normalize_event_name("BeforeTool") == "PreToolUse"
    assert relay_event({"event": "PermissionRequest", "session_id": "s",
                        "payload": {"tool": "Bash", "command": "ls"}}, None)["decision"] == "no-opinion"
    assert relay_stdin_line("not json", None)["decision"] == "no-opinion"
    queue = ApprovalQueue()
    reply = relay_stdin_line(json.dumps({"event": "PermissionRequest", "session_id": "s",
                                         "payload": {"tool": "Write", "command": "x" * 5000}}), queue)
    assert reply["decision"] == "pending"
    assert len(queue.head().command_preview) == 2000  # capped, not dropped
    assert relay_event({"event": "Stop"}, queue)["decision"] == "no-opinion"
    capped = cap_fields({"diff": "x" * 300000, "note": "y" * 5000})
    assert len(capped["diff"]) == 256 * 1024 and len(capped["note"]) == 2000


# ------------------------------------------------------------ phone approval

def test_phone_token_single_use_exact_match_and_expiry(tmp_path):
    store = PhoneApprovalStore(tmp_path / "tokens.json")
    issued = store.issue("appr-1", "Bash", "ls /tmp", "sess-1")
    raw = issued["token"]
    assert issued["scope"].startswith("one approval")
    assert store.consume(raw, "appr-1", "Bash", "ls /tmp", "allow", "sess-1")["ok"] is True
    assert store.consume(raw, "appr-1", "Bash", "ls /tmp", "allow", "sess-1")["ok"] is False  # used
    issued2 = store.issue("appr-2", "Bash", "ls /tmp", "sess-1")
    # Same token shape, different request: fingerprint mismatch fails.
    assert store.consume(issued2["token"], "appr-2", "Bash", "rm -rf /", "allow", "sess-1")["ok"] is False
    assert store.consume(issued2["token"], "appr-9", "Bash", "ls /tmp", "allow", "sess-1")["ok"] is False
    # Stored file holds hashes only — never the raw token.
    assert raw not in (tmp_path / "tokens.json").read_text(encoding="utf-8")
    # Expired token fails.
    import time as _time
    token = store._tokens[-1]
    token.expires_at = _time.time() - 1
    assert store.consume(issued2["token"], "appr-2", "Bash", "ls /tmp", "allow", "sess-1")["ok"] is False
    assert request_fingerprint("a", "Bash", "x") != request_fingerprint("a", "Bash", "y")


# ----------------------------------------------------------------- worktrees

def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
           "HOME": str(tmp_path)}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "--allow-empty", "-q", "-m", "init"], check=True, env=env)
    return repo


def test_worktree_create_list_run_remove_and_annotate(tmp_path):
    repo = _git_repo(tmp_path)
    wt = worktrees.create_worktree(repo, tmp_path / "wts", "feature-a", branch="feature-a")
    assert wt.branch == "feature-a" and Path(wt.path).is_dir()
    assert any(w.branch == "feature-a" for w in worktrees.list_worktrees(repo))
    ran = worktrees.run_in_worktree(wt.path, ["git", "status", "--short"])
    assert ran["returncode"] == 0
    diff = ("diff --git a/x.py b/x.py\n"
            "--- a/x.py\n+++ b/x.py\n"
            "@@ -1,2 +1,3 @@\n ctx\n-old\n+new1\n+new2\n ctx\n")
    annotated = worktrees.annotate_diff(diff, [
        worktrees.ReviewComment(file="x.py", line=2, comment="look here"),
        worktrees.ReviewComment(file="x.py", line=99, comment="nowhere"),
        worktrees.ReviewComment(file="nope.py", line=1, comment="wrong file"),
    ])
    assert len(annotated["kept"]) == 1 and annotated["kept"][0]["line"] == 2
    assert len(annotated["rejected"]) == 2
    out = worktrees.remove_worktree(repo, tmp_path / "wts", "feature-a")
    assert out["removed"].endswith("feature-a")
    with pytest.raises(worktrees.WorktreeError):
        worktrees.create_worktree(repo, tmp_path / "wts", "../escape")
    with pytest.raises(NotImplementedError):
        worktrees.ssh_remote_execute("host", "ls")
    with pytest.raises(NotImplementedError):
        worktrees.mobile_companion()


# ------------------------------------------------------- security execution

def test_catalog_execution_tiers_and_commands():
    assert catalog_entry("nuclei")["execution_tier"] == "active"
    assert catalog_entry("subfinder")["execution_tier"] == "passive"
    assert catalog_entry("sqlmap")["execution_tier"] == "passive-only"
    assert execution_command("nmap", "https://own.example.com") == [
        "nmap", "-T2", "-sV", "--top-ports", "100", "own.example.com"]
    assert execution_command("nuclei", "own.example.com") == [
        "nuclei", "-u", "https://own.example.com", "-silent", "-jsonl"]
    assert execution_command("sqlmap", "own.example.com") is None
    assert execution_command("ffuf", "own.example.com") is None
    assert "wordlist" in (passive_only_reason("ffuf") or "")
    assert "mutate" in (passive_only_reason("sqlmap") or "")
    assert passive_only_reason("nmap") is None
    assert execution_command("nope", "x.example.com") is None


def test_parse_tool_output_nuclei_and_httpx():
    import backend.api_routes.security_routes as routes
    nuclei_line = json.dumps({
        "templateID": "http/missing-hsts", "matched": "https://own.example.com",
        "info": {"name": "Missing HSTS", "severity": "medium",
                 "classification": {"cvss-score": 5.3}}})
    parsed = routes._parse_tool_output("nuclei", "https://own.example.com", nuclei_line + "\nnot json\n")
    assert len(parsed) == 1 and parsed[0]["severity"] == "medium"
    assert parsed[0]["cvss_score"] == pytest.approx(5.3)
    httpx_line = json.dumps({"url": "https://own.example.com", "status_code": 200, "title": "Hi"})
    parsed2 = routes._parse_tool_output("httpx", "https://own.example.com", httpx_line)
    assert len(parsed2) == 1 and parsed2[0]["severity"] == "info"


def test_security_approve_executes_and_records_passive_only(tmp_path, monkeypatch):
    import backend.api_routes.security_routes as routes
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from backend.security_guardrails import IsolationResult
    from fastapi.testclient import TestClient
    import asyncio

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/deep-sec.db")
    reset_engine_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    client = TestClient(create_app())
    with client:
        creds = {"username": "deep_user", "password": "StrongPass123!"}
        r = client.post("/api/auth/register", json=creds)
        data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
        h = {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}
        assert client.post("/api/security/allowlist",
                           json={"host_pattern": "*.example.com"}, headers=h).status_code == 201
        # Executed tool: httpx (passive, enabled by default), runner patched.
        httpx_line = json.dumps({"url": "https://app.example.com", "status_code": 200, "title": "Hi"})
        monkeypatch.setattr(routes, "run_isolated_command",
                            lambda cmd, ws, **kw: IsolationResult(
                                isolation="workspace-fallback", warning="fallback warning",
                                stdout=httpx_line, stderr="", returncode=0))
        r = client.post("/api/security/runs",
                        json={"target": "https://app.example.com", "tool_class": "scan"}, headers=h)
        run_id = r.json()["id"]
        r = client.post(f"/api/security/runs/{run_id}/approve",
                        json={"tool_name": "httpx"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["result"]["findings_created"] == 1
        assert r.json()["result"]["execution_tier"] == "passive"
        findings = client.get(f"/api/security/runs/{run_id}/findings", headers=h).json()["findings"]
        assert len(findings) == 1 and findings[0]["status"] == "candidate"
        assert findings[0]["validation_verdict"] == ""  # unvalidated until a human validates
        # Passive-only tool: enable sqlmap, approve -> explicit not_executed + audit.
        assert client.post("/api/security/catalog/sqlmap/enable",
                           json={"enabled": True}, headers=h).status_code == 200
        r = client.post("/api/security/runs",
                        json={"target": "https://app.example.com", "tool_class": "scan"}, headers=h)
        run2 = r.json()["id"]
        r = client.post(f"/api/security/runs/{run2}/approve",
                        json={"tool_name": "sqlmap"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["result"]["execution_tier"] == "passive-only"
        assert "not_executed" in r.json()["result"]
        audit = client.get(f"/api/security/runs/{run2}/audit", headers=h).json()["audit"]
        assert "run.tool_passive_only" in [a["action"] for a in audit]
        # Disabled tool: nuclei is disabled by default -> 403, nothing executed.
        r = client.post("/api/security/runs",
                        json={"target": "https://app.example.com", "tool_class": "scan"}, headers=h)
        run3 = r.json()["id"]
        r = client.post(f"/api/security/runs/{run3}/approve",
                        json={"tool_name": "nuclei"}, headers=h)
        assert r.status_code == 403, r.text
