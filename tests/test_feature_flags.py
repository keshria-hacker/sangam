"""Tests for runtime feature-flag overrides (backend/feature_flags.py + API)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def _reload_ff(monkeypatch, tmp_path):
    import backend.feature_flags as ff

    monkeypatch.setattr(ff, "OVERRIDES_PATH", tmp_path / "feature_flags.json")
    ff.reset_for_testing()
    return ff


def test_override_takes_precedence_over_env(monkeypatch, tmp_path):
    ff = _reload_ff(monkeypatch, tmp_path)
    # voice defaults True (config); override to False wins.
    assert ff.is_enabled("voice") is True
    ff.set_override("voice", False)
    assert ff.is_enabled("voice") is False
    ff.set_override("voice", True)
    assert ff.is_enabled("voice") is True


def test_unknown_flag_rejected(monkeypatch, tmp_path):
    ff = _reload_ff(monkeypatch, tmp_path)
    try:
        ff.set_override("nope", True)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown flag")


def test_overrides_persist_to_disk(monkeypatch, tmp_path):
    ff = _reload_ff(monkeypatch, tmp_path)
    ff.set_override("analytics", True)
    # Simulate a fresh process: drop the in-memory cache.
    ff.reset_for_testing()
    assert ff.is_enabled("analytics") is True
    assert (tmp_path / "feature_flags.json").exists()


def test_effective_flags_include_overrides(monkeypatch, tmp_path):
    ff = _reload_ff(monkeypatch, tmp_path)
    ff.set_override("learning", False)
    flags = ff.effective_flags()
    assert flags["learning"] is False
    assert "voice" in flags and "analytics" in flags


import pytest


@pytest.fixture()
def api_client(monkeypatch, tmp_path):
    """Self-contained app client with fresh DB and isolated flag overrides."""
    from fastapi.testclient import TestClient

    import backend.feature_flags as ff

    monkeypatch.setattr(ff, "OVERRIDES_PATH", tmp_path / "feature_flags.json")
    ff.reset_for_testing()

    db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    os.environ["DATABASE_URL"] = db_url

    import backend.models  # noqa: F401
    from backend.config import settings

    settings.DATABASE_URL = db_url
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app

    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    ff.reset_for_testing()


def _auth(api_client):
    creds = {"username": "flag_test_user", "password": "StrongPass123!"}
    r = api_client.post("/api/auth/register", json=creds)
    if r.status_code not in (200, 201):
        r = api_client.post("/api/auth/login", json=creds)
    assert r.status_code in (200, 201), r.text
    d = r.json()
    return {"Authorization": f"Bearer {d['access_token']}", "X-CSRF-Token": d["csrf_token"]}


def test_features_api_roundtrip(api_client):
    h = _auth(api_client)

    r = api_client.get("/api/features", headers=h)
    assert r.status_code == 200
    assert "voice" in r.json()["features"]

    r = api_client.post("/api/features/voice", json={"enabled": False}, headers=h)
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = api_client.get("/api/features", headers=h)
    assert r.json()["features"]["voice"] is False
    assert r.json()["overrides"]["voice"] is False

    r = api_client.post("/api/features/bogus", json={"enabled": True}, headers=h)
    assert r.status_code == 404

    # Voice routes should now 404 (flag off).
    r = api_client.get("/api/voice/status", headers=h)
    assert r.status_code == 404

    # Restore for other tests.
    api_client.post("/api/features/voice", json={"enabled": True}, headers=h)
