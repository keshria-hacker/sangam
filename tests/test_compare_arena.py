"""Tests for Phase 6.4c: model compare + Arena."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def test_compare_endpoints_registered():
    from fastapi.testclient import TestClient
    from backend.main import app
    paths = TestClient(app).get("/openapi.json").json()["paths"].keys()
    assert "/api/compare" in paths
    assert "/api/arena/vote" in paths
    assert "/api/arena/leaderboard" in paths


def test_arena_result_model():
    from backend.models import ArenaResult
    assert hasattr(ArenaResult, 'winner_model')
    assert hasattr(ArenaResult, 'loser_model')
    assert hasattr(ArenaResult, 'models_compared')
