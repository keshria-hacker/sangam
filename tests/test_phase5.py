"""Tests for Phase 5: automations."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def test_automation_validation():
    from backend.automations import validate_automation, parse_schedule
    assert validate_automation("daily", "agent") is None
    assert validate_automation("hourly", "chat") is None
    assert validate_automation("0 9 * * *", "agent") is None
    assert validate_automation("never", "agent") is not None
    assert validate_automation("daily", "invalid") is not None


def test_parse_schedule():
    from backend.automations import parse_schedule
    from datetime import datetime, UTC
    now = datetime.now(UTC)
    nxt = parse_schedule("daily")
    assert nxt > now
    assert (nxt - now).days >= 1


def test_automation_endpoints_registered():
    from fastapi.testclient import TestClient
    from backend.main import app
    paths = TestClient(app).get("/openapi.json").json()["paths"].keys()
    assert "/api/automations" in paths
