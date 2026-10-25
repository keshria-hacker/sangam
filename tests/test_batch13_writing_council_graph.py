"""Batch 13 (Writing / Quality / Council / Code-Graph / Model-Fit) tests.

Pure-function tests for the new depth plus route tests for the new
quality / routing endpoints. No model, no network, no fake numbers:
every figure asserted here is computed by the code under test from
the inputs given.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.code_graph import build_graph  # noqa: E402
from backend.code_graph_queries import (  # noqa: E402
    evidence_block,
    explain_change,
    find_code,
    find_orphans,
    impact_analysis,
    layering_check,
)
from backend.council_mode import (  # noqa: E402
    deliberate,
    lock_domain_seat,
    restate_gate,
    select_panel,
)
from backend.model_fit import (  # noqa: E402
    USE_CASE_WEIGHTS,
    estimate_speed_tok_s,
    recommend,
    weighted_score,
)
from backend.providers.fallback_chain import (  # noqa: E402
    FallbackChain,
    choose_provider,
)
from backend.response_quality import (  # noqa: E402
    detect_structure,
    natural_rewrite,
    pre_send_check,
    readability_report,
    restate_state,
    run_eval,
)
from backend.response_quality.humanizer import HONEST_NOTE  # noqa: E402
from backend.teams import debate as debate_mod  # noqa: E402
from backend.teams.definitions import COUNCIL_LENSES  # noqa: E402

# ------------------------------------------------------------- client (Batch 7 pattern)
from backend.config import settings  # noqa: E402
from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.ratelimit_redis import reset_rate_limit_store_for_testing  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b13.db")
    reset_engine_for_testing()
    reset_rate_limit_store_for_testing()

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
    creds = {"username": "b13_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


# ------------------------------------------------------- 1. structural detect
def test_structure_detects_named_patterns_detect_only():
    text = (
        "It's not a tool, it's a mindset.\n"
        "Here's the thing: experts say it works.\n"
        "## **Bold heading**\n"
        "A line — with — many — em dashes — here.\n"
        "In summary, this is the end.\n"
    )
    hits = detect_structure(text)
    patterns = {h["pattern"] for h in hits}
    assert "binary-contrast" in patterns
    assert "colon-reveal" in patterns
    assert "weasel-attribution" in patterns
    assert "formatting-slop-bold-heading" in patterns
    assert "em-dash-cluster" in patterns
    assert "recap-ending" in patterns
    for h in hits:
        assert h["quote"] and h["fix"]  # name + quote + few-word fix, never a rewrite
    # Detect-only: the input text is unchanged by detection.
    assert "It's not a tool" in text


def test_structure_robotic_rhythm_and_readability():
    text = "We ship fast. We test well. We document clearly. Then we rest."
    hits = detect_structure(text)
    assert any(h["pattern"] == "robotic-rhythm" for h in hits)
    rep = readability_report(text)
    assert rep["words"] == 12 and rep["sentences"] == 4
    assert rep["long_sentences"] == 0
    assert "easy to scan" in rep["note"]


# ------------------------------------------------------- 2. eval + humanizer
def test_eval_catches_lost_numbers_and_passes_clean_edit():
    bad = run_eval("Revenue grew 37% in Q2.", "Revenue grew a lot in Q2.", [])
    assert not bad["ok"]
    assert any(c["check"] == "numbers_preserved" and not c["passed"] for c in bad["checks"])
    good = run_eval("Revenue grew 37% in Q2.", "Revenue grew 37% in Q2.",
                    [])
    assert good["ok"]


def test_humanizer_is_readability_not_evasion():
    text = ("Let's delve into the rich tapestry of this topic, which is a "
            "game-changer for everyone involved in the process of building "
            "software systems that handle user requests and responses.")
    rewritten, changes = natural_rewrite(text)
    assert "delve" not in rewritten.lower()
    assert "tapestry" not in rewritten.lower()
    assert changes
    assert "does not evade AI detectors" in HONEST_NOTE
    assert "conceal authorship" in HONEST_NOTE
    # No detector-bypass guarantee anywhere in the note.
    assert "bypass" not in HONEST_NOTE.lower()
    assert "guarantee" not in HONEST_NOTE.lower()


def test_humanizer_splits_overlong_sentence():
    long_sent = ("This is a very long sentence that keeps going and going "
                 "and it covers many ideas and it never seems to stop at all "
                 "and it adds clause after clause after clause after clause "
                 "and it finally ends here, and then it adds one more idea.")
    rewritten, changes = natural_rewrite(long_sent)
    assert any(c["pattern"] == "long-sentence-split" for c in changes)
    assert rewritten.count(".") >= 2


# ------------------------------------------------------- 3. ADHD pre-send
def test_adhd_pre_send_check_and_restatement():
    good = "Do this first: open the file.\nStep 2 of 3 is done.\nNext step: run the tests."
    check = pre_send_check(good)
    assert check["first_line_is_action"] is True
    assert check["last_line_is_next_step"] is True
    assert check["ok"] is True
    bad = "Some background context here.\nBy the way, another thought.\nThanks for reading."
    check2 = pre_send_check(bad)
    assert check2["ok"] is False
    assert check2["tangent_count"] == 1
    state = restate_state(9, 3, "run the tests")
    assert state["step"] == 3 and state["total"] == 3  # clamped, never rejected
    assert state["text"] == "Step 3 of 3 — next: run the tests"


# ------------------------------------------------------- 4. council panels
def test_council_panel_profiles_and_domain_lock():
    lenses = list(COUNCIL_LENSES)
    panel, name = select_panel(lenses, profile="execution-lean")
    assert name == "execution-lean"
    assert [lens.id for lens in panel] == ["builder", "pragmatist"]
    panel2, _ = select_panel(lenses, members=["skeptic", "builder"])
    assert [lens.id for lens in panel2] == ["skeptic", "builder"]
    with pytest.raises(ValueError):
        select_panel(lenses, profile="nope")
    with pytest.raises(ValueError):
        select_panel(lenses, members=["skeptic"])
    assert lock_domain_seat("What is the security risk here?", lenses) == "skeptic"
    assert lock_domain_seat("How much will this cost?", lenses) == "pragmatist"
    assert lock_domain_seat("Hello there, general question?", lenses) is None


def test_restate_gate_coverage():
    gate = restate_gate("Should we ship the new search feature this week?",
                        "Whether to ship the new search feature this week.")
    assert gate["ok"] is True
    gate2 = restate_gate("Should we ship the new search feature this week?",
                         "Something about dinner plans.")
    assert gate2["ok"] is False
    assert gate2["missing"]


@pytest.mark.asyncio
async def test_deliberate_enforcement_reprompts_dissent_once():
    calls = {"n": 0}

    async def fake(messages):
        system, user = messages[0]["content"], messages[1]["content"]
        lens = "skeptic" if "Skeptic" in system else ("builder" if "Builder" in system else "pragmatist")
        calls["n"] += 1
        if "Chairman" in system:
            return "Chairman synthesis: split, dissent preserved."
        if "named no disagreement" in user:
            return "I disagree with Member B because its claim is unproven; it strengthened my view."
        if "final position" in user:
            stance = {"skeptic": "delay", "builder": "ship", "pragmatist": "ship"}[lens]
            conf = {"skeptic": "high", "builder": "med", "pragmatist": "low"}[lens]
            deal = "yes" if lens == "skeptic" else "no"
            return f"Final.\nSTANCE: {stance} | CONFIDENCE: {conf} | DEALBREAKER: {deal}"
        if "Anonymized" in user:
            # Only builder dissents on first pass (1 < 2 quota), so
            # skeptic AND pragmatist are re-prompted exactly once.
            if lens == "builder":
                return "I disagree with Member A because its claim is unproven; it strengthened my view."
            return "I agree with everyone; all points are sound."
        return "Blind analysis."

    result = await deliberate("Ship?", list(COUNCIL_LENSES), fake, chairman=True)
    assert any(e["trigger"] == "dissent_quota" and e["member"] == "skeptic"
               for e in result.session["enforcement_calls"])
    assert result.chairman_synthesis.startswith("Chairman synthesis")
    assert result.verdict.startswith("Chairman's synthesis:")
    assert result.tally.consensus is False
    assert "skeptic" in result.tally.dealbreakers  # minority report survives


@pytest.mark.asyncio
async def test_deliberate_missing_stance_reprompt_then_abstain():
    seen = {}

    async def fake(messages):
        system, user = messages[0]["content"], messages[1]["content"]
        lens = "skeptic" if "Skeptic" in system else ("builder" if "Builder" in system else "pragmatist")
        if "final position" in user or "no STANCE line" in user:
            key = (lens, "stance")
            seen[key] = seen.get(key, 0) + 1
            if lens == "builder" and seen[key] == 1:
                return "I think ship, but no stance line here."
            stance = {"skeptic": "delay", "builder": "ship", "pragmatist": "ship"}[lens]
            return f"Final.\nSTANCE: {stance} | CONFIDENCE: med | DEALBREAKER: no"
        if "Anonymized" in user:
            return "I disagree with Member A because X; it strengthened my view by Y."
        return "Blind."

    result = await deliberate("Ship?", list(COUNCIL_LENSES), fake)
    assert any(e["trigger"] == "missing_stance" and e["member"] == "builder"
               for e in result.session["enforcement_calls"])
    assert result.tally.totals.get("ship", 0) > 0


# ------------------------------------------------------- 5. debate ledger
def test_debate_ledger_scenarios_and_closing_report():
    transcript = [
        {"round": 1, "persona": "alice", "content": "I disagree with bob: the cost is too high."},
        {"round": 1, "persona": "bob", "content": "The cost is fine."},
        {"round": 2, "persona": "alice", "content": "Still opposed: the cost is too high."},
    ]
    ledger = debate_mod.position_ledger(transcript)
    assert ledger["alice"]["rounds_spoken"] == 2
    assert ledger["alice"]["latest"].startswith("Still opposed")
    branches = debate_mod.scenario_branches("Ship?", ["budget doubles", "deadline slips"])
    assert len(branches) == 2 and "budget doubles" in branches[0]["topic"]
    with pytest.raises(ValueError):
        debate_mod.scenario_branches("Ship?", ["a", "b", "c", "d"])
    report = debate_mod.closing_report("Ship?", "Split on cost.", transcript)
    assert len(report["disagreements"]) == 1
    assert "alice" in report["what_would_change_it"]


# ------------------------------------------------------- 6. code graph
def _tree(tmp_path):
    (tmp_path / "a.py").write_text(
        "def alpha():\n    beta()\n\n\ndef beta():\n    gamma()\n\n\n"
        "def gamma():\n    pass\n\n\n"
        "def _helper():\n    pass\n\n\n"
        "class Base:\n    pass\n\n\n"
        "class Child(Base):\n    def unused_method(self):\n        pass\n")
    (tmp_path / "test_a.py").write_text("def helper():\n    pass\n")
    (tmp_path / "x.py").write_text("def helper():\n    return 1\n")
    return build_graph(tmp_path)


def test_graph_bm25_test_derank_and_extends(tmp_path):
    g = _tree(tmp_path)
    extends = [e for e in g["edges"] if e["type"] == "extends"]
    assert any(e["from"] == "a.py#Child" and e["to"] == "a.py#Base" for e in extends)
    res = find_code(g, "helper")
    names = [r["symbol"] for r in res["results"]]
    assert names and names[0] == "x.py#helper"  # prod outranks test file (0.35x)
    assert "evidence" in res
    assert res["evidence"]["sources"]
    assert "dropped_ambiguous_calls" in res["evidence"]["limitations"]


def test_graph_impact_orphans_explain_change(tmp_path):
    g = _tree(tmp_path)
    imp = impact_analysis(g, "gamma")
    assert set(imp["callers_transitive"]) == {"a.py#beta", "a.py#alpha"}
    assert imp["files_touched"] == ["a.py"]
    assert "call site" in imp["risk_note"]
    orph = find_orphans(g)
    symbols = {o["symbol"] for o in orph["orphans"]}
    assert "a.py#_helper" in symbols  # private, no caller
    assert "a.py#Child.unused_method" in symbols  # method, no caller
    assert "a.py#alpha" not in symbols  # exported top-level is not an orphan
    diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
            "@@ -1,2 +1,2 @@\n-def alpha():\n+def alpha():\n+    beta()\n")
    expl = explain_change(g, diff)
    assert expl["files"] == ["a.py"]
    assert "a.py#beta" in expl["mentioned_symbols"]
    assert "a.py#beta" in expl["impacts"]


def test_graph_layering_check(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "domain").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def serve():\n    logic()\n")
    (tmp_path / "domain" / "logic.py").write_text("def logic():\n    serve()\n")
    g = build_graph(tmp_path)
    out = layering_check(g, ["app/", "domain/"])
    # domain/logic.py calling app/svc.py is upward (lower -> higher).
    assert out["violation_count"] >= 1
    assert any(v["caller_file"] == "domain/logic.py" for v in out["violations"])
    assert layering_check(g, [])["error"]


# ------------------------------------------------------- 7. model fit + routing
def test_weighted_score_weights_shown_and_use_case_matters():
    fit = {"quality_class": "good", "speed_class": "slow",
           "fits": True, "est_memory_gb": 5.0, "bottleneck": "none"}
    entry = {"context": 131072}
    chat = weighted_score(entry, fit, USE_CASE_WEIGHTS["chat"], 8192)
    reasoning = weighted_score(entry, fit, USE_CASE_WEIGHTS["reasoning"], 8192)
    assert chat["weights"]["quality"] == 0.45
    assert reasoning["weights"]["quality"] == 0.55
    # Same model, different weights -> different scores (quality-heavy wins for reasoning).
    assert reasoning["weighted_score"] > chat["weighted_score"]
    est = estimate_speed_tok_s(7.62, "Q4_K")
    assert est["source"] == "estimated" and est["tok_per_s"] > 0


def test_recommend_measured_overrides_estimate():
    hw = {"ram_gb": 16.0, "vram_gb": None}
    rows = recommend(hw, use_case="chat", benchmarks={"llama-3.2-1b": 80.0})
    row = next(r for r in rows if r["id"] == "llama-3.2-1b")
    assert row["speed_source"] == "measured" and row["measured_tok_s"] == 80.0
    assert "weights" in row and "weighted_score" in row
    rows2 = recommend(hw, use_case="chat", benchmarks={"llama-3.2-1b": 99999.0})
    row2 = next(r for r in rows2 if r["id"] == "llama-3.2-1b")
    assert row2["speed_source"] == "estimated"
    assert "plausibility cap" in row2["speed_note"]


def test_routing_strategies_and_pinning():
    states = {
        "a": {"circuit": "closed", "quota": {"remaining": 10, "limit": 100}},
        "b": {"circuit": "closed", "quota": {"remaining": 90, "limit": 100}},
        "c": {"circuit": "open", "quota": {"remaining": 100, "limit": 100}},
    }
    pid, reasons = choose_provider(["a", "b", "c"], "priority", states)
    assert pid == "a"
    pid, _ = choose_provider(["a", "b"], "headroom", states)
    assert pid == "b"
    pid, _ = choose_provider(["a", "b"], "quota-weighted", states)
    assert pid == "b"  # 0.90 fraction beats 0.10
    pid, _ = choose_provider(["a", "b"], "cost-optimized", states,
                             costs={"a": 5.0, "b": 1.0})
    assert pid == "b"
    pid, reasons = choose_provider(["a", "b"], "fail-closed", states,
                                   billable={"a", "b"})
    assert pid is None and reasons["available"] is False
    rr = {"index": 0}
    first, _ = choose_provider(["a", "b"], "round-robin", states, round_robin_state=rr)
    second, _ = choose_provider(["a", "b"], "round-robin", states, round_robin_state=rr)
    assert (first, second) == ("a", "b")
    with pytest.raises(ValueError):
        choose_provider(["a"], "nope", states)
    chain = FallbackChain()
    chain.configure(["a", "b"])
    with pytest.raises(ValueError):
        chain.pin_session("s1", "zzz")
    chain.pin_session("s1", "b")
    assert chain.pinned_provider("s1") == "b"
    pid, reasons = chain.choose("priority", session_id="s1")
    assert pid == "b" and reasons["pinned"] is True


# ------------------------------------------------------- 8. routes
def test_quality_routes_check_humanize_report(client):
    h = _auth_headers(client)
    text = "It's not a tool, it's a mindset. The the repeated word is here."
    r = client.post("/api/quality/check", json={"text": text}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["findings"] and data["findings"][0]["severity"] == "must-fix"
    assert data["footer"]["not_checked"] and data["footer"]["risks"]
    assert all("if_skipped" in f for f in data["findings"])
    r = client.post("/api/quality/humanize", json={"text": "Let's delve into this."}, headers=h)
    assert r.status_code == 200, r.text
    assert "does not evade AI detectors" in r.json()["note"]
    r = client.post("/api/quality/report", json={"text": text}, headers=h)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["readability"]["words"] > 0
    assert rep["adhd_pre_send_check"]["issues"] is not None
    r = client.post("/api/quality/preview",
                    json={"text": text, "mode": "edit", "structure": True}, headers=h)
    assert r.status_code == 200, r.text
    assert "structure" in r.json() and "eval" in r.json()


def test_models_route_endpoint(client):
    h = _auth_headers(client)
    r = client.post("/api/models/route", json={"strategy": "priority"}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["strategy"] == "priority" and "reasons" in data
    r = client.post("/api/models/route", json={"strategy": "fail-closed",
                                               "billable": ["ollama", "openai", "anthropic",
                                                            "gemini", "groq", "together",
                                                            "openrouter", "deepseek", "mistral",
                                                            "nvidia", "omniroute"]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["provider"] is None  # fail-closed never bills
    r = client.post("/api/models/route", json={"strategy": "nope"}, headers=h)
    assert r.status_code == 422
    r = client.post("/api/models/recommend", json={"use_case": "chat"}, headers=h)
    assert r.status_code == 200, r.text
    recs = r.json()["recommendations"]
    assert recs and all("weighted_score" in rec and "weights" in rec for rec in recs)


def test_debate_scenario_and_report_routes(client):
    h = _auth_headers(client)
    r = client.post("/api/teams/debate/scenarios",
                    json={"topic": "Ship?", "variables": ["budget doubles"]}, headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()["branches"]) == 1
    r = client.post("/api/teams/debate/scenarios",
                    json={"topic": "Ship?", "variables": ["a", "b", "c", "d"]}, headers=h)
    assert r.status_code == 422
    r = client.get("/api/teams/debate/jobs/nope/report", headers=h)
    assert r.status_code == 404


def test_code_graph_new_routes(client, tmp_path):
    # Route-level graph endpoints run against the workspace root, so
    # only assert shape, not workspace content.
    h = _auth_headers(client)
    r = client.get("/api/code-graph/orphans", headers=h)
    assert r.status_code == 200, r.text
    assert "orphans" in r.json() and "evidence" in r.json()
    r = client.post("/api/code-graph/explain-change",
                    json={"diff": "diff --git a/x.py b/x.py\n+++ b/x.py\n+foo()\n"}, headers=h)
    assert r.status_code == 200, r.text
    assert "files" in r.json() and "limitations" in r.json()
    r = client.get("/api/code-graph/impact", params={"symbol": "definitely-not-a-symbol"}, headers=h)
    assert r.status_code == 200, r.text
    assert "error" in r.json()
