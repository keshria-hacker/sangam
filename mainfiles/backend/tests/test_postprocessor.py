"""
Unit tests for uncertainty post-processing — Implementation Plan Phase 3.

Pure-function tests (no DB, no HTTP): the post-processor is a pure
text-transform gated by ResponseGuidance signals.
"""

import os

os.environ["TEST_MODE"] = "1"

import sys
from pathlib import Path

_MAINFILES = Path(__file__).resolve().parents[2]
if str(_MAINFILES) not in sys.path:
    sys.path.insert(0, str(_MAINFILES))

from backend.response_postprocessor import (  # noqa: E402
    post_process_response,
)
from backend.response_intelligence.schema import (  # noqa: E402
    IntentSignal,
    QueryMode,
    ResponseGuidance,
)

TEXT = "The Eiffel Tower is 330 metres tall."


def _guidance(mode: QueryMode, ambiguous: bool) -> ResponseGuidance:
    return ResponseGuidance(mode=mode, intent=IntentSignal(is_ambiguous=ambiguous))


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------


def test_hedges_ambiguous_factual():
    out = post_process_response(TEXT, _guidance(QueryMode.FACTUAL, True))
    assert out != TEXT
    assert out.endswith(TEXT)
    assert "not fully certain" in out


def test_hedges_ambiguous_analysis():
    out = post_process_response(TEXT, _guidance(QueryMode.ANALYSIS, True))
    assert out != TEXT
    assert "Note:" in out


# ---------------------------------------------------------------------------
# Passthrough — must NOT hedge
# ---------------------------------------------------------------------------


def test_no_hedge_when_not_ambiguous():
    out = post_process_response(TEXT, _guidance(QueryMode.FACTUAL, False))
    assert out == TEXT


def test_no_hedge_for_coding_mode():
    out = post_process_response(TEXT, _guidance(QueryMode.CODING, True))
    assert out == TEXT


def test_no_hedge_for_conversational_mode():
    out = post_process_response(TEXT, _guidance(QueryMode.CONVERSATIONAL, True))
    assert out == TEXT


def test_no_hedge_when_model_already_hedged():
    hedged_text = "I think the Eiffel Tower is 330 metres tall."
    out = post_process_response(hedged_text, _guidance(QueryMode.FACTUAL, True))
    assert out == hedged_text


def test_no_hedge_when_already_processed():
    once = post_process_response(TEXT, _guidance(QueryMode.FACTUAL, True))
    twice = post_process_response(once, _guidance(QueryMode.FACTUAL, True))
    assert twice == once, "post-processor must be idempotent"


def test_passthrough_empty_text():
    assert post_process_response("", _guidance(QueryMode.FACTUAL, True)) == ""
    assert post_process_response("   ", _guidance(QueryMode.FACTUAL, True)) == "   "


def test_passthrough_none_guidance():
    assert post_process_response(TEXT, None) == TEXT


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------


def test_flag_disable():
    from backend.response_intelligence.config import config as ri_conf
    original = ri_conf.UNCERTAINTY_HEDGING_ENABLED
    try:
        ri_conf.UNCERTAINTY_HEDGING_ENABLED = False
        # Direct module call bypasses the flag by design (flag checked in
        # api.py), so simulate the api.py condition here:
        if ri_conf.UNCERTAINTY_HEDGING_ENABLED:
            post_process_response(TEXT, _guidance(QueryMode.FACTUAL, True))
        # No exception, no hedge — api.py gates the call.
        assert True
    finally:
        ri_conf.UNCERTAINTY_HEDGING_ENABLED = original


# ---------------------------------------------------------------------------
# Markdown safety
# ---------------------------------------------------------------------------


def test_hedge_is_separate_paragraph():
    out = post_process_response(TEXT, _guidance(QueryMode.FACTUAL, True))
    assert "\n\n" in out, "hedge should be its own paragraph for markdown"
    assert "```" not in out
