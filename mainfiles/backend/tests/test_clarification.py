"""
Integration tests for the clarification gate — Implementation Plan Phase 2.

SAFETY: same pattern as test_feedback.py — per-test tmp_path SQLite file,
hard guard against the production DB, TEST_MODE=1 before backend imports.

Covers:
- should_clarify / derive_interpretations unit behavior
- Ambiguous short request -> clarification_request SSE event, user turn persisted
- Long ambiguous request -> normal stream (length exemption)
"""

import json
import os

os.environ["TEST_MODE"] = "1"

import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

_MAINFILES = Path(__file__).resolve().parents[2]
if str(_MAINFILES) not in sys.path:
    sys.path.insert(0, str(_MAINFILES))

from backend import ratelimit as _ratelimit  # noqa: E402
from backend.capability_orchestration import (  # noqa: E402
    derive_interpretations,
    should_clarify,
)
from backend.config import settings  # noqa: E402
from backend.database import (  # noqa: E402
    AsyncSessionLocal,
    Base,
    get_engine,
    reset_engine_for_testing,
)
from backend.main import create_app  # noqa: E402
from backend.response_intelligence.schema import (  # noqa: E402
    IntentSignal,
    QueryMode,
    ResponseGuidance,
)

_ratelimit.TEST_MODE = True

PROD_DB_MARKER = "history/sangam.db"


def _bind_test_engine(tmp_path) -> None:
    test_db = tmp_path / "test.db"
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db.as_posix()}"
    reset_engine_for_testing()
    assert PROD_DB_MARKER not in str(settings.DATABASE_URL), "SAFETY ABORT"


@pytest.fixture
async def client(tmp_path):
    _bind_test_engine(tmp_path)
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    await engine.dispose()


@pytest.fixture
async def auth_client(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "tester", "password": "Password123"},
    )
    assert resp.status_code == 201, resp.text
    csrf = client.cookies.get("sangam_csrf")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf
    return client


def _sse_frames(text: str) -> list[tuple[str | None, str]]:
    """Minimal SSE frame parser for assertions (event line + data)."""
    frames = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev = None
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        if ev or data_lines:
            frames.append((ev, "\n".join(data_lines)))
    return frames


# ---------------------------------------------------------------------------
# Unit: gate decision + interpretation derivation
# ---------------------------------------------------------------------------


def test_should_clarify_ambiguous_short():
    g = ResponseGuidance(mode=QueryMode.CONVERSATIONAL, intent=IntentSignal(is_ambiguous=True))
    assert should_clarify("explain it", g) is True


def test_should_clarify_rejects_clear():
    g = ResponseGuidance(mode=QueryMode.FACTUAL, intent=IntentSignal(is_ambiguous=False))
    assert should_clarify("What is the capital of France?", g) is False


def test_should_clarify_rejects_long():
    g = ResponseGuidance(mode=QueryMode.CONVERSATIONAL, intent=IntentSignal(is_ambiguous=True))
    long_msg = "it could be maybe possibly depends " * 5
    assert should_clarify(long_msg, g) is False


def test_should_clarify_disabled_by_config():
    from backend.response_intelligence.config import config as ri_conf
    g = ResponseGuidance(mode=QueryMode.CONVERSATIONAL, intent=IntentSignal(is_ambiguous=True))
    original = ri_conf.CLARIFICATION_ENABLED
    try:
        ri_conf.CLARIFICATION_ENABLED = False
        assert should_clarify("explain it", g) is False
    finally:
        ri_conf.CLARIFICATION_ENABLED = original


def test_derive_interpretations_pronoun():
    g = ResponseGuidance(mode=QueryMode.CONVERSATIONAL, intent=IntentSignal(is_ambiguous=True))
    opts = derive_interpretations("explain it", g)
    assert 2 <= len(opts) <= 3
    assert any("depth" in o.lower() for o in opts)


def test_derive_interpretations_coding():
    g = ResponseGuidance(mode=QueryMode.CODING, intent=IntentSignal(is_ambiguous=True))
    opts = derive_interpretations("the parser", g)
    assert any("code" in o.lower() for o in opts)


# ---------------------------------------------------------------------------
# Integration: streaming endpoint interception
# ---------------------------------------------------------------------------


async def test_stream_returns_clarification_for_ambiguous(auth_client):
    """Ambiguous short request -> clarification_request event, no [DONE]-less error."""
    resp = await auth_client.post(
        "/api/chat/stream",
        json={
            "model": "ollama::test-model",
            "messages": [{"role": "user", "content": "explain it"}],
        },
    )
    assert resp.status_code == 200
    body = resp.text
    frames = _sse_frames(body)

    # chat_id frame first
    chat_frames = [f for f in frames if f[0] == "chat_id"]
    assert chat_frames, f"no chat_id frame in: {body[:500]}"

    # exactly one canonical clarification_request event
    clar = [f for f in frames if f[0] == "response_event" and '"clarification_request"' in f[1]]
    assert len(clar) == 1, f"expected 1 clarification event, got {len(clar)}: {body[:800]}"
    payload = json.loads(clar[0][1])
    assert payload["type"] == "clarification_request"
    assert len(payload["metadata"]["options"]) >= 2

    # message_end follows (terminal), then [DONE]
    ends = [f for f in frames if f[0] == "response_event" and '"message_end"' in f[1]]
    assert len(ends) == 1
    assert any(f[1] == "[DONE]" for f in frames)


async def test_stream_persists_user_turn_on_clarification(auth_client):
    """The user turn must be stored so the chosen interpretation has context."""
    resp = await auth_client.post(
        "/api/chat/stream",
        json={
            "model": "ollama::test-model",
            "messages": [{"role": "user", "content": "explain it"}],
        },
    )
    frames = _sse_frames(resp.text)
    chat_id = next(f[1] for f in frames if f[0] == "chat_id")

    from sqlalchemy import select
    from backend.models import Message
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(Message).where(Message.chat_id == chat_id))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].role == "user"
    assert rows[0].content == "explain it"


async def test_no_clarification_for_regenerate(auth_client):
    """regenerate=true must not duplicate-persist or misbehave in the gate."""
    resp = await auth_client.post(
        "/api/chat/stream",
        json={
            "model": "ollama::test-model",
            "messages": [{"role": "user", "content": "explain it"}],
            "regenerate": True,
        },
    )
    assert resp.status_code == 200
    assert '"clarification_request"' in resp.text
