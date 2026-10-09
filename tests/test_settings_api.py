"""Tests for the typed settings API (Phase 2)."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def _client():
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app)


def test_settings_endpoints_registered():
    c = _client()
    paths = c.get("/openapi.json").json()["paths"].keys()
    assert "/api/user/settings" in paths
    assert "/api/v1/user/settings" in paths


def test_settings_requires_auth():
    c = _client()
    r = c.get("/api/user/settings")
    assert r.status_code == 401
    r = c.put("/api/user/settings", json={"settings": {}})
    assert r.status_code == 401
