"""A2 — Composer & Response Intelligence (perfect-flow spec §3.2, §4, §9).

Covers, with no provider call and no network:
- the 50-prompt golden set (tests/data/auto_routing_golden.json):
  >=90% intent+mode agreement, >=90% must-include tools, >=80% of
  decisions made by deterministic rules (classifier only on ties);
- the routing matrix: time signals -> search + citations, code block /
  "fix this" -> code mode, diagram -> artifact, deep research ->
  search + crawl, small app -> artifact, "run this task" -> agent +
  approval gate, ambiguous -> exactly one clarification question,
  follow-ups inherit the previous mode without re-stating context;
- explicit composer modes and per-message tool overrides;
- video blocked (skipped this round, never fabricated);
- ADHD / no-slop / Harper passes never corrupting code, identifiers,
  error strings, or protected names; Harper and slop Detect never
  rewrite text;
- POST /intelligence/route + /intelligence/harper over the real app
  (TestClient-style ASGI transport, tmp SQLite, no ports).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.response_intelligence.pipeline import route_message  # noqa: E402
from backend.response_quality import (  # noqa: E402
    adhd_format,
    detect_slop,
    lint_harper,
    remove_slop_with_changes,
)


def _golden() -> dict:
    path = _ROOT / "tests" / "data" / "auto_routing_golden.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _route(item: dict):
    return route_message(
        item["prompt"],
        history=item.get("history") or [],
        file_ids=item.get("file_ids") or [],
        composer_mode=item.get("composer_mode", "auto"),
        tool_overrides=item.get("tool_overrides") or {},
    )


def test_golden_set_has_50_items_covering_every_intent():
    data = _golden()
    assert len(data["items"]) == 50, f"golden set has {len(data['items'])} items, expected 50"
    intents = {i["expected_intent"] for i in data["items"]}
    expected = {
        "direct_answer", "teaching", "code_generate", "code_debug",
        "code_refactor", "research", "file_analysis", "artifact_create",
        "diagram", "image", "video", "voice", "agentic_task",
        "clarification", "follow_up", "meta",
    }
    assert expected <= intents, f"missing intents: {expected - intents}"


def test_golden_agreement_at_least_90_percent():
    items = _golden()["items"]
    misses = []
    for item in items:
        d = _route(item)
        if d.intent != item["expected_intent"] or d.mode != item["expected_mode"]:
            misses.append(
                f"{item['id']}: {item['prompt'][:60]!r} -> {d.intent}/{d.mode}, "
                f"expected {item['expected_intent']}/{item['expected_mode']}"
            )
    score = (len(items) - len(misses)) / len(items)
    assert score >= 0.90, f"golden agreement {score:.0%} < 90%; misses:\n" + "\n".join(misses)


def test_golden_rule_coverage_at_least_80_percent():
    items = _golden()["items"]
    classifier_runs = sum(1 for i in items if _route(i).classifier_used)
    assert classifier_runs / len(items) <= 0.20, (
        f"classifier ran on {classifier_runs}/{len(items)} golden prompts; "
        "rules must cover >=80%"
    )


def test_golden_must_include_tools():
    items = _golden()["items"]
    misses = []
    for item in items:
        d = _route(item)
        for tool in item.get("must_tools") or []:
            if tool not in d.tools:
                misses.append(f"{item['id']}: missing tool {tool} (got {d.tools})")
    assert len(misses) / max(len(items), 1) <= 0.10, "\n".join(misses)


def test_followups_inherit_mode_without_restating_context():
    for item in _golden()["items"]:
        if item["expected_intent"] != "follow_up":
            continue
        d = _route(item)
        assert d.is_follow_up is True
        assert d.restates_context is False, f"{item['id']}: follow-up must not re-state context"
        assert d.continuation_of == item["continuation_of"], (
            f"{item['id']}: continuation_of={d.continuation_of}, expected {item['continuation_of']}"
        )
        assert d.clarification_question is None


def test_ambiguous_gets_exactly_one_clarification_question():
    for prompt in ("help", "it"):
        d = route_message(prompt, history=[])
        assert d.intent == "clarification"
        assert d.clarification_question, "clarification must carry exactly one question"
        assert d.clarification_question.count("?") == 1, d.clarification_question


def test_video_is_blocked_never_fabricated():
    d = route_message("Make a video explaining photosynthesis")
    assert d.intent == "video"
    assert d.blocked is True
    assert d.tools == []
    assert d.blocked_reason and "not available" in d.blocked_reason


def test_agentic_tasks_require_approval():
    d = route_message("Watch for price drops on this laptop and tell me")
    assert d.intent == "agentic_task" and d.mode == "agent"
    assert d.approval_required is True
    assert d.next_step and "Approve" in d.next_step


def test_time_signals_search_with_citations_but_plain_questions_do_not():
    d = route_message("What is the current price of Bitcoin?")
    assert d.needs_search is True and d.needs_citations is True
    assert "web_search" in d.tools
    d2 = route_message("What is the capital of France?")
    assert d2.needs_search is False and d2.tools == []


def test_explicit_composer_mode_wins_over_auto():
    d = route_message("What is the current price of Bitcoin?", composer_mode="answer")
    assert d.mode == "answer" and d.needs_search is False
    d2 = route_message("What is the capital of France?", composer_mode="code")
    assert d2.mode == "code"


def test_tool_overrides_apply_to_one_message_only():
    prompt = "Latest news about the Mars mission"
    d = route_message(prompt, tool_overrides={"web_search": False})
    assert "web_search" not in d.tools
    assert d.needs_search is False
    d2 = route_message(prompt)
    assert "web_search" in d2.tools
    d3 = route_message(prompt, tool_overrides={"bogus_tool": True})
    assert "bogus_tool" not in d3.tools


def test_complexity_and_depth_are_bounded_and_sane():
    d = route_message("Research quantum computing deeply, with sources")
    assert 0.0 <= d.complexity <= 1.0
    assert route_message("Explain like I'm five: what is gravity?").depth == "novice"
    assert route_message("Explain idempotency and race condition handling").depth == "expert"


def test_slop_never_rewrites_code_inline_code_or_protected_names():
    text = (
        "```python\n# delve into tapestry\ndef delve():\n    pass\n```\n"
        "Let us delve into the tapestry of ideas. The function `delve_into` stays. "
        "The Crucial product is great."
    )
    cleaned, _ = remove_slop_with_changes(text, protected=["Crucial"])
    assert "# delve into tapestry" in cleaned
    assert "def delve():" in cleaned
    assert "`delve_into`" in cleaned
    assert "The Crucial product is great." in cleaned
    assert "look at the mix of ideas" in cleaned
    # Detect mode never rewrites and never flags code.
    assert detect_slop("```\ndelve into tapestry\n```") == []
    detections = detect_slop("Let's delve into the tapestry.")
    assert detections and detections[0]["pattern"] == "delve-into"
    assert detections[0]["quote"] == "Let's delve into the tapestry."


def test_harper_suggestions_only_never_rewrites_or_flags_code():
    text = "This is is a test. The `my_func` stays untouched."
    assert lint_harper(text)  # repeated-word "is is" is flagged
    assert all(i["rule"] != "unknown-word" or "my_func" not in i["quote"] for i in lint_harper(text))
    assert lint_harper("```\nThis is is bad\n```\nClean text here.") == []
    # Harper output is suggestions; the input text itself is unchanged.
    assert text == "This is is a test. The `my_func` stays untouched."


def test_adhd_caps_lists_and_preserves_code():
    text = "Do this:\n- one\n- two\n- three\n- four\n- five\n- six\n- seven\n```python\nx = 1\n```"
    out, _ = adhd_format(text)
    assert "+2 more" in out
    assert "```python\nx = 1\n```" in out
    out2, _ = adhd_format("Great question! The answer is 42.")
    assert out2.startswith("The answer is 42.")


# --- App-level: /intelligence/* over ASGI transport, tmp SQLite ----------

def _bind_test_engine(tmp_path) -> None:
    from backend import ratelimit as _ratelimit
    from backend.config import settings
    from backend.database import reset_engine_for_testing

    _ratelimit.TEST_MODE = True
    test_db = tmp_path / "test.db"
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db}"
    reset_engine_for_testing()
    assert "history/sangam.db" not in str(settings.DATABASE_URL), "SAFETY ABORT"


@pytest.fixture
async def app_client(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from backend.database import Base, get_engine
    from backend.main import create_app

    _bind_test_engine(tmp_path)
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/auth/register", json={"username": "a2tester", "password": "Password123"})
        assert resp.status_code == 201, resp.text
        csrf = ac.cookies.get("sangam_csrf")
        if csrf:
            ac.headers["X-CSRF-Token"] = csrf
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_intelligence_route_endpoint(app_client):
    r = await app_client.post("/api/intelligence/route", json={
        "message": "What is the current price of Bitcoin?",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["intent"] == "research" and data["mode"] == "research"
    assert "web_search" in data["tools"]
    r2 = await app_client.post("/api/intelligence/route", json={"message": "Make a video about cats"})
    assert r2.json()["blocked"] is True


@pytest.mark.asyncio
async def test_intelligence_harper_endpoint(app_client):
    r = await app_client.post("/api/intelligence/harper", json={"text": "This is is bad."})
    assert r.status_code == 200, r.text
    assert any(s["rule"] == "repeated-word" for s in r.json()["suggestions"])
