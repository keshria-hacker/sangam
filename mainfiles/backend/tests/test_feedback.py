"""
Integration tests for message feedback (thumbs up/down) — Implementation Plan Phase 1.

SAFETY: every test runs against a tmp_path-backed SQLite file, NEVER the
production DB at history/sangam.db. A hard guard aborts the run if the
engine URL points at the production file (this guard exists because a
fixture bug on 2026-09-12 ran drop_all against the live DB).

Covers:
- POST /api/messages/{id}/feedback stores "up"/"down"
- Toggle-off undo (same value twice clears feedback)
- Switching values overwrites
- 404 on unknown message id
- 422 on invalid value (Pydantic Literal)
- feedback fields round-trip through GET /api/chats/{id} (MessageOut)
"""

import os
import sys
from pathlib import Path

# Must be set BEFORE backend modules are imported: ratelimit.py reads it at
# import time. Also forced again via attribute below for import-order safety.
os.environ["TEST_MODE"] = "1"

import pytest
from httpx import ASGITransport, AsyncClient

# Make `backend` importable when pytest runs from mainfiles/backend.
_MAINFILES = Path(__file__).resolve().parents[2]
if str(_MAINFILES) not in sys.path:
    sys.path.insert(0, str(_MAINFILES))

from backend.config import settings  # noqa: E402
from backend.database import (  # noqa: E402
    AsyncSessionLocal,
    Base,
    get_engine,
    reset_engine_for_testing,
)
from backend.main import create_app  # noqa: E402
from backend import ratelimit as _ratelimit  # noqa: E402
from backend.models import Chat, Message  # noqa: E402

# Import-order-proof: force-disable rate limiting regardless of who imported first.
_ratelimit.TEST_MODE = True

PROD_DB_MARKER = "history/sangam.db"


def _bind_test_engine(tmp_path) -> str:
    """Point settings at a per-test SQLite file and reset the engine cache."""
    test_db = tmp_path / "test.db"
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db.as_posix()}"
    reset_engine_for_testing()
    url = str(settings.DATABASE_URL)
    assert PROD_DB_MARKER not in url, (
        f"SAFETY ABORT: engine bound to production DB ({url})"
    )
    return url


@pytest.fixture
async def client(tmp_path):
    """Fresh per-test SQLite file DB + app client."""
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
    """Client logged in as the first registered user (single-user app).

    Also wires the CSRF double-submit header so POST endpoints pass the
    CSRF middleware (mirrors what the real browser client does).
    """
    resp = await client.post(
        "/api/auth/register",
        json={"username": "tester", "password": "Password123"},
    )
    assert resp.status_code == 201, resp.text
    csrf = client.cookies.get("sangam_csrf")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf
    return client


async def _seed_message(feedback: str | None = None) -> str:
    """Insert one chat + assistant message directly; return message id."""
    async with AsyncSessionLocal() as db:
        chat = Chat(title="t", model="m")
        db.add(chat)
        await db.flush()
        msg = Message(
            chat_id=chat.id,
            role="assistant",
            content="hello",
            feedback=feedback,
        )
        db.add(msg)
        await db.commit()
        return msg.id


async def _get_message(message_id: str) -> Message:
    async with AsyncSessionLocal() as db:
        return await db.get(Message, message_id)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_feedback_up_is_stored(auth_client):
    msg_id = await _seed_message()
    resp = await auth_client.post(f"/api/messages/{msg_id}/feedback", json={"value": "up"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["feedback"] == "up"
    stored = await _get_message(msg_id)
    assert stored.feedback == "up"


async def test_feedback_down_is_stored(auth_client):
    msg_id = await _seed_message()
    resp = await auth_client.post(f"/api/messages/{msg_id}/feedback", json={"value": "down"})
    assert resp.status_code == 200
    stored = await _get_message(msg_id)
    assert stored.feedback == "down"


# ---------------------------------------------------------------------------
# Toggle semantics
# ---------------------------------------------------------------------------


async def test_feedback_same_value_twice_clears(auth_client):
    msg_id = await _seed_message()
    for _ in range(2):
        resp = await auth_client.post(f"/api/messages/{msg_id}/feedback", json={"value": "up"})
        assert resp.status_code == 200
    assert resp.json()["feedback"] is None
    stored = await _get_message(msg_id)
    assert stored.feedback is None


async def test_feedback_switch_value_overwrites(auth_client):
    msg_id = await _seed_message()
    await auth_client.post(f"/api/messages/{msg_id}/feedback", json={"value": "up"})
    resp = await auth_client.post(f"/api/messages/{msg_id}/feedback", json={"value": "down"})
    assert resp.status_code == 200
    assert resp.json()["feedback"] == "down"
    stored = await _get_message(msg_id)
    assert stored.feedback == "down"


async def test_feedback_note_is_stored(auth_client):
    msg_id = await _seed_message()
    resp = await auth_client.post(
        f"/api/messages/{msg_id}/feedback",
        json={"value": "down", "note": "wrong answer"},
    )
    assert resp.status_code == 200
    stored = await _get_message(msg_id)
    assert stored.feedback == "down"
    assert stored.feedback_note == "wrong answer"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


async def test_feedback_unknown_message_404(auth_client):
    resp = await auth_client.post("/api/messages/doesnotexist/feedback", json={"value": "up"})
    assert resp.status_code == 404


async def test_feedback_invalid_value_422(auth_client):
    msg_id = await _seed_message()
    resp = await auth_client.post(
        f"/api/messages/{msg_id}/feedback", json={"value": "sideways"}
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Round-trip through MessageOut
# ---------------------------------------------------------------------------


async def test_feedback_visible_in_chat_detail(auth_client):
    msg_id = await _seed_message()
    await auth_client.post(f"/api/messages/{msg_id}/feedback", json={"value": "up"})

    stored = await _get_message(msg_id)
    resp = await auth_client.get(f"/api/chats/{stored.chat_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["messages"], "chat detail should include messages"
    msg_out = next(m for m in detail["messages"] if m["id"] == msg_id)
    assert msg_out["feedback"] == "up"
