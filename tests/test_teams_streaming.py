"""Tests for Phase 6.4a: Teams SSE streaming."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import pytest


def test_streaming_module_exists():
    """Streaming module can be imported."""
    from backend.teams.streaming import stream_team_run, format_sse
    assert callable(stream_team_run)
    assert callable(format_sse)


def test_sse_format():
    """Events are formatted as valid SSE."""
    from backend.teams.streaming import format_sse
    event = {"type": "specialist_start", "agent_id": "researcher"}
    sse = format_sse(event)
    assert sse.startswith("data: ")
    assert sse.endswith("\n\n")
    import json
    parsed = json.loads(sse[6:-2])
    assert parsed["type"] == "specialist_start"


def test_teams_stream_endpoint_registered():
    """SSE streaming endpoint is registered."""
    from fastapi.testclient import TestClient
    from backend.main import app
    paths = TestClient(app).get("/openapi.json").json()["paths"].keys()
    assert "/api/teams/run/stream" in paths
    assert "/api/teams/retry-agent" in paths


@pytest.mark.asyncio
async def test_stream_team_run_disabled():
    """Streaming returns error when teams are disabled."""
    from backend.teams.streaming import stream_team_run
    from unittest.mock import patch

    with patch('backend.teams.streaming.is_enabled', return_value=False):
        events = []
        async for event in stream_team_run("test", "task", "model", None):
            events.append(event)
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "not enabled" in events[0]["error"]
