"""
response_postprocessor.py — Confidence-aware response post-processing.

Adds a calibrated uncertainty hedge to responses where the Phase 6 guidance
signals high ambiguity AND the query mode is factual/analysis (where a
confident tone is most misleading).

Design constraints:
- NEVER mutates the live stream. This runs only on the fully-collected text
  at persistence time, so what the user watched stream stays intact and the
  stored/reloaded version carries the hedge.
- Idempotent: if the model already hedged (or this module already ran), the
  text is returned unchanged.
- Never crashes the chat: the caller wraps this in try/except like every
  other Phase integration.
"""
from __future__ import annotations

from typing import Any

# Phrases that indicate the model already expressed uncertainty — if any of
# these appear, adding another hedge would be noise.
_EXISTING_HEDGE_MARKERS = [
    "i think", "i believe", "i'm not sure", "i am not sure", "probably",
    "might be", "could be", "possibly", "i'm not certain", "i am not certain",
    "unclear", "not certain", "may vary", "it depends", "take this with",
    "worth verifying", "double-check", "verify this",
]

# Calibrated, single-sentence hedges. Deterministic (first entry) rather than
# random so repeated generations under the same conditions read consistently.
_HEDGES = [
    "Note: I'm not fully certain about this — it may be worth verifying.",
    "Note: This answer may be incomplete; consider verifying the details.",
    "Note: Treat this as a best-effort answer; some details may be off.",
]

# Modes where a confident tone on uncertain ground is most harmful.
_ELIGIBLE_MODES = {"factual", "analysis"}


def _already_hedged(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _EXISTING_HEDGE_MARKERS)


def _has_hedge_suffix(text: str) -> bool:
    """True if the text already ends with one of our own hedge sentences."""
    lower = text.lower().strip()
    return any(lower.startswith(h[:-1].lower()) for h in _HEDGES) or any(
        h[:-1].lower() in lower for h in _HEDGES
    )


def post_process_response(text: str, guidance: Any) -> str:
    """Prepend a calibrated hedge to low-confidence factual/analysis answers.

    Activation conditions (ALL must hold):
    - guidance.intent.is_ambiguous is True
    - guidance.mode is factual or analysis
    - the text does not already hedge uncertainty

    Returns the text unchanged in every other case.
    """
    if not text or not text.strip():
        return text

    if guidance is None:
        return text

    intent = getattr(guidance, "intent", None)
    if intent is None or not getattr(intent, "is_ambiguous", False):
        return text

    mode = getattr(guidance, "mode", None)
    mode_val = getattr(mode, "value", mode)  # StrEnum -> str
    if mode_val not in _ELIGIBLE_MODES:
        return text

    if _already_hedged(text) or _has_hedge_suffix(text):
        return text

    # Prepend as its own line so markdown rendering keeps it separate.
    return f"{_HEDGES[0]}\n\n{text}"
