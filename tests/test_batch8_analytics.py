"""Batch 8: GET /api/analytics/summary — the route the routing quota view
polled but which never existed (it always fell back to "Analytics not
enabled"). Covers: disabled -> 404; enabled -> summary shape with the
message count from DB events and tokens/cost from the telemetry ledger
(asserted as deltas, since the ledger is process-global and other test
files may have recorded entries in the same pytest run).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.api_routes.analytics_routes as analytics_routes  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.database import AsyncSessionLocal, Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.ratelimit_redis import reset_rate_limit_store_for_testing  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b8.db")
    reset_engine_for_testing()
    reset_rate_limit_store_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth_headers(client):
    creds = {"username": "b8_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def _user_id():
    async def _get():
        from sqlalchemy import select

        from backend.models import User

        async with AsyncSessionLocal() as session:
            row = await session.scalar(select(User))
            return row.id

    return asyncio.run(_get())


def _seed_messages(user_id, n):
    async def _seed():
        from backend.analytics.events import MESSAGE_SENT
        from backend.models import AnalyticsEvent

        async with AsyncSessionLocal() as session:
            for _ in range(n):
                session.add(AnalyticsEvent(user_id=user_id, event_type=MESSAGE_SENT, properties="{}"))
            await session.commit()

    asyncio.run(_seed())


def test_summary_disabled_returns_404(client, monkeypatch):
    monkeypatch.setattr(analytics_routes, "is_enabled", lambda name: False)
    headers = _auth_headers(client)
    r = client.get("/api/analytics/summary", headers=headers)
    assert r.status_code == 404


def test_summary_shape_and_deltas(client, monkeypatch):
    monkeypatch.setattr(analytics_routes, "is_enabled", lambda name: True)
    headers = _auth_headers(client)
    from backend.contracts import telemetry_ledger

    before = client.get("/api/analytics/summary", headers=headers)
    assert before.status_code == 200, before.text
    base = before.json()["summary"]
    assert set(base) == {"messages", "tokens", "cost_usd"}

    _seed_messages(_user_id(), 2)
    telemetry_ledger.record(provider="test", model="m", latency_ms=1.0,
                            input_tokens=100, output_tokens=50)
    after = client.get("/api/analytics/summary", headers=headers).json()["summary"]
    assert after["messages"] - base["messages"] == 2
    assert after["tokens"] - base["tokens"] == 150
    assert after["cost_usd"] == base["cost_usd"]  # no prices supplied -> cost stays put
