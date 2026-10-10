"""
api_routes/quality_routes.py — de-slop diff (Phase 4).
"""
import difflib

from fastapi import Depends
from pydantic import BaseModel

from ..auth import get_current_user
from ..response_quality import apply_quality
from .common import router


class QualityIn(BaseModel):
    text: str
    no_slop: bool = True
    adhd_friendly: bool = False


@router.post("/quality/preview")
async def preview_quality(payload: QualityIn, user=Depends(get_current_user)):
    """Show before/after diff of quality processing."""
    cleaned, stats = apply_quality(
        payload.text,
        no_slop=payload.no_slop,
        adhd_friendly=payload.adhd_friendly,
    )
    # Unified diff
    diff = list(difflib.unified_diff(
        payload.text.splitlines(keepends=True),
        cleaned.splitlines(keepends=True),
        fromfile="original", tofile="cleaned",
    ))
    return {
        "original": payload.text,
        "cleaned": cleaned,
        "diff": "".join(diff),
        "stats": stats,
    }
