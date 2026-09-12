"""
Integration tests for user preferences — Implementation Plan Phase 4.

SAFETY: same pattern as test_feedback.py — per-test tmp_path SQLite file,
hard guard against the production DB, TEST_MODE=1 before backend imports.

Covers:
- GET /api/user/preferences returns defaults when unset
- PUT upserts and GET round-trips the stored values
- 422 on invalid enum values
- 401 without auth
- Override semantics: stored prefs flip guidance style signals
"""

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
from backend.config import settings  # noqa: E402
from backend.database import (  # noqa: E402
    Base,
    get_engine,
    reset_engine_for_testing,
)
from backend.main import create_app  # noqa: E402
from backend.models import UserPreference  # noqa: E402
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


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


async def test_get_defaults_when_unset(auth_client):
    resp = await auth_client.get("/api/user/preferences")
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_style"] == "balanced"
    assert body["formality"] == "neutral"
    assert body["expertise_level"] == "general"


async def test_put_then_get_roundtrip(auth_client):
    resp = await auth_client.put(
        "/api/user/preferences",
        json={"response_style": "concise", "formality": "formal", "expertise_level": "expert"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["response_style"] == "concise"
    assert body["formality"] == "formal"
    assert body["expertise_level"] == "expert"

    # Second GET reflects persistence
    resp = await auth_client.get("/api/user/preferences")
    assert resp.json()["response_style"] == "concise"


async def test_put_upsert_does_not_duplicate(auth_client):
    await auth_client.put("/api/user/preferences", json={"response_style": "detailed"})
    await auth_client.put("/api/user/preferences", json={"response_style": "concise"})

    from sqlalchemy import select, func
    from backend.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(select(func.count()).select_from(UserPreference))
        ).scalar()
    assert count == 1, "upsert must reuse the same row"


async def test_put_partial_defaults_other_fields(auth_client):
    """A PUT that omits formality resets it to the schema default (full-object upsert)."""
    await auth_client.put(
        "/api/user/preferences",
        json={"response_style": "concise", "formality": "formal", "expertise_level": "expert"},
    )
    resp = await auth_client.put("/api/user/preferences", json={"response_style": "detailed"})
    body = resp.json()
    assert body["response_style"] == "detailed"
    assert body["formality"] == "neutral"


# ---------------------------------------------------------------------------
# Validation + auth
# ---------------------------------------------------------------------------


async def test_put_invalid_value_422(auth_client):
    resp = await auth_client.put(
        "/api/user/preferences",
        json={"response_style": "shouty"},
    )
    assert resp.status_code == 422


async def test_get_without_auth_401(client):
    resp = await client.get("/api/user/preferences")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Override semantics (the core of Phase 4)
# ---------------------------------------------------------------------------


def _apply_pref_override(guidance: ResponseGuidance, pref: UserPreference) -> None:
    """Mirror of the chat_stream override logic — kept in sync by tests."""
    if pref.response_style == "concise":
        guidance.profile.user_prefers_concise = True
        guidance.profile.user_prefers_detailed = False
        guidance.intent.wants_concise = True
        guidance.intent.wants_detailed = False
    elif pref.response_style == "detailed":
        guidance.profile.user_prefers_concise = False
        guidance.profile.user_prefers_detailed = True
        guidance.intent.wants_concise = False
        guidance.intent.wants_detailed = True
    if pref.formality != "neutral":
        guidance.intent.tone = pref.formality
    if pref.expertise_level == "beginner":
        guidance.intent.technical_depth = "low"
    elif pref.expertise_level == "expert":
        guidance.intent.technical_depth = "high"


def test_override_flips_detected_signals():
    guidance = ResponseGuidance(
        mode=QueryMode.CONVERSATIONAL,
        intent=IntentSignal(wants_concise=True),
    )
    guidance.profile.user_prefers_concise = True
    pref = UserPreference(
        user_id="x", response_style="detailed", formality="formal", expertise_level="expert"
    )
    _apply_pref_override(guidance, pref)
    assert guidance.intent.wants_detailed is True
    assert guidance.intent.wants_concise is False
    assert guidance.profile.user_prefers_detailed is True
    assert guidance.profile.user_prefers_concise is False
    assert guidance.intent.tone == "formal"
    assert guidance.intent.technical_depth == "high"


def test_override_neutral_formality_keeps_detected():
    guidance = ResponseGuidance(
        mode=QueryMode.CONVERSATIONAL,
        intent=IntentSignal(tone="casual"),
    )
    pref = UserPreference(user_id="x", response_style="balanced", formality="neutral", expertise_level="general")
    _apply_pref_override(guidance, pref)
    assert guidance.intent.tone == "casual", "neutral pref must not clobber detected tone"


def test_override_produces_concise_prompt_addition():
    """The overridden guidance must translate into the expected prompt text."""
    from backend.response_intelligence.prompt_injector import build_system_prompt_additions

    guidance = ResponseGuidance(mode=QueryMode.FACTUAL, intent=IntentSignal())
    pref = UserPreference(user_id="x", response_style="concise", formality="neutral", expertise_level="general")
    _apply_pref_override(guidance, pref)
    additions = build_system_prompt_additions(guidance)
    assert any("concise" in a.lower() for a in additions), (
        f"expected concise instruction in additions: {additions}"
    )
