"""
api_routes/quality_routes.py — writing-quality API (Batch 7).

POST /quality/preview — before/after diff (existing shape preserved:
original/cleaned/diff/stats). New `mode` field, default "edit" so
existing callers do not break:
  mode=detect -> detections [{pattern, line, quote}], text UNCHANGED
                 (cleaned == original, diff == ""), no rewrite.
  mode=edit   -> minimum edit + "what_changed" [{pattern, before, after}]
                 alongside the existing fields.
POST /quality/lint — offline deterministic lint (writing_lint.py);
  returns {issues} and never rewrites.
GET /quality/adhd-style — the prompt-level ADHD style block. Honest
  status (deep-memory wiring): wired=true — chat_stream_routes.py
  injects this block into the chat system prompt when the user's
  ``adhdFriendly`` setting is on, and leaves the prompt unchanged
  when it is off. The post-hoc adhdFriendly formatting toggle is
  separate and also works.
"""
import difflib

from fastapi import Depends
from pydantic import BaseModel

from ..auth import get_current_user
from ..response_quality import adhd_style_text, apply_quality, detect_slop
from ..response_quality.slop import remove_slop_with_changes
from ..writing_lint import lint_text
from .common import router


class QualityIn(BaseModel):
    text: str
    no_slop: bool = True
    adhd_friendly: bool = False
    mode: str = "edit"  # "edit" (default, legacy) or "detect"


class LintIn(BaseModel):
    text: str


@router.post("/quality/preview")
async def preview_quality(payload: QualityIn, user=Depends(get_current_user)):
    """Show before/after diff of quality processing (or detect-only)."""
    mode = (payload.mode or "edit").lower()
    if mode == "detect":
        detections = detect_slop(payload.text) if payload.no_slop else []
        return {
            "original": payload.text,
            "cleaned": payload.text,
            "diff": "",
            "stats": {"slop_removed": 0, "adhd_changes": 0, "detections": len(detections)},
            "mode": "detect",
            "detections": detections,
        }
    cleaned, stats = apply_quality(
        payload.text,
        no_slop=payload.no_slop,
        adhd_friendly=payload.adhd_friendly,
    )
    diff = list(difflib.unified_diff(
        payload.text.splitlines(keepends=True),
        cleaned.splitlines(keepends=True),
        fromfile="original", tofile="cleaned",
    ))
    what_changed: list[dict] = []
    if payload.no_slop:
        _slop_cleaned, what_changed = remove_slop_with_changes(payload.text)
    return {
        "original": payload.text,
        "cleaned": cleaned,
        "diff": "".join(diff),
        "stats": stats,
        "mode": "edit",
        "what_changed": what_changed,
    }


@router.post("/quality/lint")
async def lint_quality(payload: LintIn, user=Depends(get_current_user)):
    """Offline grammar/spell/repetition lint. Candidate issues only.

    `issues` is the pre-existing writing_lint shape (unchanged).
    `harper` adds the Harper-class pass (response_quality/harper.py),
    which blanks code fences / inline code / code-looking lines before
    linting, so identifiers and error strings never produce issues.
    Neither list rewrites the text.
    """
    from ..response_quality.harper import lint_harper

    return {"issues": lint_text(payload.text), "harper": lint_harper(payload.text)}


@router.get("/quality/adhd-style")
async def get_adhd_style(user=Depends(get_current_user)):
    """Prompt-level ADHD style block + honest wiring status."""
    return {
        "style": adhd_style_text(),
        "wired_into_chat": True,
        "wired_behind_setting": "adhdFriendly",
        "note": (
            "Wired into chat: chat_stream_routes.py prepends this style "
            "block to the chat system prompt when the user's adhdFriendly "
            "setting is on; when off, the prompt path is unchanged. The "
            "post-hoc adhdFriendly toggle (opener-strip + reflow + list "
            "cap) is separate and also works."
        ),
    }
