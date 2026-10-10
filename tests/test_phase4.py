"""Tests for Phase 4: artifacts, spec wizard, quality preview."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def test_spec_wizard():
    from backend.spec_wizard import build_spec, spec_to_agent_task
    spec = build_spec("Test", "Problem here", ["Goal 1"], ["Must be fast"],
                      ["Step 1"], ["Task 1"])
    assert "# Test" in spec
    assert "Problem here" in spec
    assert "- Goal 1" in spec
    assert "- [ ] Task 1" in spec
    task = spec_to_agent_task(spec)
    assert "Implement the following spec" in task


def test_spec_endpoints_registered():
    from fastapi.testclient import TestClient
    from backend.main import app
    paths = TestClient(app).get("/openapi.json").json()["paths"].keys()
    assert "/api/spec/build" in paths
    assert "/api/spec/to-task" in paths
    assert "/api/artifacts" in paths
    assert "/api/quality/preview" in paths


def test_quality_preview():
    from backend.response_quality import apply_quality
    text = "In conclusion, it is important to note that this is very good."
    cleaned, stats = apply_quality(text, no_slop=True, adhd_friendly=False)
    # Should remove some slop phrases
    assert isinstance(cleaned, str)
    assert isinstance(stats, dict)
