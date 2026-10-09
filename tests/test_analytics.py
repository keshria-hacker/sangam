"""Analytics tests: opt-in recording, aggregates, API gating."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.analytics import events as ae  # noqa: E402
from backend.analytics import (  # noqa: E402
    get_stats,
    optional_user_id,
    record_event,
    register_analytics_extension,
)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "FEATURE_ANALYTICS", True)
    yield


async def _db_session(tmp_path):
    """A real async SQLite session factory against a temp DB with all tables."""
    import backend.models  # noqa: F401 — registers tables on Base.metadata
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from sqlalchemy.ext.asyncio import async_sessionmaker

    settings.DATABASE_URL = f"sqlite+aiosqlite:///{tmp_path}/analytics.db"
    reset_engine_for_testing()

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _make_user(db, username: str) -> str:
    from backend.models import User

    user = User(username=username, password_salt="s", password_hash="h")
    db.add(user)
    await db.flush()
    return user.id


@pytest.mark.asyncio
async def test_record_event_stores(tmp_path):
    maker = await _db_session(tmp_path)
    async with maker() as db:
        uid = await _make_user(db, "analytics_u1")
        assert await record_event(db, uid, ae.MESSAGE_SENT, {"model": "m1"}) is True
        assert await record_event(db, uid, ae.TEAM_RUN, {"team_id": "research"}) is True

        from sqlalchemy import func, select

        from backend.models import AnalyticsEvent

        count = await db.scalar(select(func.count()).select_from(AnalyticsEvent))
        assert count == 2


@pytest.mark.asyncio
async def test_record_event_noop_when_flag_off(tmp_path, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "FEATURE_ANALYTICS", False)
    maker = await _db_session(tmp_path)
    async with maker() as db:
        assert await record_event(db, "user1", ae.MESSAGE_SENT, {}) is False


@pytest.mark.asyncio
async def test_record_event_no_user_noop(tmp_path):
    maker = await _db_session(tmp_path)
    async with maker() as db:
        assert await record_event(db, None, ae.MESSAGE_SENT, {}) is False


@pytest.mark.asyncio
async def test_get_stats_aggregates(tmp_path):
    maker = await _db_session(tmp_path)
    async with maker() as db:
        uid = await _make_user(db, "analytics_u2")
        other = await _make_user(db, "analytics_u3")
        for _ in range(3):
            await record_event(db, uid, ae.MESSAGE_SENT, {"model": "m1"})
        await record_event(db, uid, ae.MESSAGE_SENT, {"model": "m2"})
        await record_event(db, uid, ae.TEAM_RUN, {})
        await record_event(db, other, ae.MESSAGE_SENT, {"model": "m1"})

        stats = await get_stats(db, uid, days=14)
        assert stats["enabled"] is True
        assert stats["total_events"] == 5
        assert {b["type"] for b in stats["by_type"]} == {"message_sent", "team_run"}
        assert stats["top_models"][0] == {"model": "m1", "count": 3}
        assert len(stats["per_day"]) == 1  # all today


@pytest.mark.asyncio
async def test_get_stats_disabled_flag(tmp_path, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "FEATURE_ANALYTICS", False)
    maker = await _db_session(tmp_path)
    async with maker() as db:
        assert await get_stats(db, "user1") == {"enabled": False}


@pytest.mark.asyncio
async def test_optional_user_id_anonymous(tmp_path):
    maker = await _db_session(tmp_path)

    class Req:
        cookies = {}
        headers = {}

    async with maker() as db:
        assert await optional_user_id(Req(), db) is None


def test_analytics_extension_registered():
    from backend.extensions import extensions

    assert register_analytics_extension() is True
    assert extensions.get("capability:analytics") is not None


# --- API ---------------------------------------------------------------------

def _api_client(tmp_path, monkeypatch, analytics_on: bool):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "FEATURE_ANALYTICS", analytics_on)
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    assert "history/sangam.db" not in str(settings.DATABASE_URL)
    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "analytics_test_user", "password": "StrongPass123!"}
    resp = client.post("/api/auth/register", json=creds)
    data = resp.json() if resp.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_analytics_api_404_when_flag_off(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch, analytics_on=False)
    headers = _auth(client)
    assert client.get("/api/analytics/stats", headers=headers).status_code == 404


def test_analytics_api_stats(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch, analytics_on=True)
    headers = _auth(client)
    resp = client.get("/api/analytics/stats", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["total_events"] == 0
