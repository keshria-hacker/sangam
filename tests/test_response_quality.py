"""Response quality tests: no-ai-slop cleanup, ADHD-friendly formatting."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.response_quality import (  # noqa: E402
    adhd_format,
    apply_quality,
    register_quality_extension,
    remove_slop,
)


# --- slop --------------------------------------------------------------------

def test_remove_slop_swaps():
    out, n = remove_slop("Let's delve into the tapestry of ideas.")
    assert out == "Let's look at the mix of ideas."
    assert n == 2


def test_remove_slop_deletions_fix_capitalization():
    out, n = remove_slop("It's important to note that the sky is blue.")
    assert out == "The sky is blue."
    assert n >= 1


def test_remove_slop_leading_opener():
    out, n = remove_slop("Great question! The answer is 42.")
    assert out == "The answer is 42."


def test_remove_slop_preserves_clean_text():
    text = "The mitochondria is the powerhouse of the cell."
    out, n = remove_slop(text)
    assert out == text and n == 0


def test_remove_slop_case_preserving():
    out, _ = remove_slop("Delve into the docs for details.")
    assert out == "Look at the docs for details."


def test_remove_slop_empty():
    assert remove_slop("") == ("", 0)
    assert remove_slop("   ") == ("   ", 0)


# --- adhd ---------------------------------------------------------------------

def test_adhd_strips_opener():
    out, n = adhd_format("Of course! Here's the thing.")
    assert out == "Here's the thing." and n >= 1


def test_adhd_reflows_wall_of_text():
    wall = "This is a sentence. " * 60  # ~1200 chars, one paragraph
    out, n = adhd_format(wall)
    assert n >= 1
    assert out.count("\n\n") >= 1
    assert all(len(p) <= 650 for p in out.split("\n\n"))


def test_adhd_leaves_code_blocks_alone():
    code = "```python\n" + "x = 1\n" * 100 + "```"
    out, n = adhd_format(code)
    assert "\n\n" not in out  # not reflowed


def test_adhd_collapses_blank_lines():
    out, n = adhd_format("a\n\n\n\nb")
    assert out == "a\n\nb" and n >= 1


# --- apply_quality + postprocessor hook ----------------------------------------

def test_apply_quality_combined():
    text = "Great question! Let's delve into it. " + "Word. " * 200
    out, stats = apply_quality(text, no_slop=True, adhd_friendly=True)
    assert stats["slop_removed"] >= 1
    assert stats["adhd_changes"] >= 1
    assert "delve" not in out


def test_apply_quality_disabled_is_identity():
    text = "Let's delve into the tapestry!"
    out, stats = apply_quality(text)
    assert out == text and stats == {"slop_removed": 0, "adhd_changes": 0}


def test_postprocessor_applies_quality(monkeypatch):
    from backend import response_postprocessor as pp
    from backend.config import settings

    monkeypatch.setattr(settings, "QUALITY_NO_SLOP", True)
    monkeypatch.setattr(settings, "QUALITY_ADHD_FRIENDLY", False)
    out = pp.post_process_response("Let's delve into the docs.", guidance=None)
    assert out == "Let's look at the docs."


def test_postprocessor_quality_off_by_default(monkeypatch):
    from backend import response_postprocessor as pp
    from backend.config import settings

    monkeypatch.setattr(settings, "QUALITY_NO_SLOP", False)
    monkeypatch.setattr(settings, "QUALITY_ADHD_FRIENDLY", False)
    text = "Let's delve into the tapestry!"
    assert pp.post_process_response(text, guidance=None) == text


def test_quality_extension_registered():
    from backend.extensions import extensions

    assert register_quality_extension() is True
    manifest = extensions.get("capability:response_quality")
    assert manifest is not None and manifest.version == "1.0.0"
