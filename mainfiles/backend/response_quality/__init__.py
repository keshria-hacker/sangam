"""
backend.response_quality — output quality: no-ai-slop cleanup + ADHD-friendly
formatting (petergyang/no-ai-slop, ayghri/i-have-adhd).

Runs at persistence time on the fully-collected text (never the live stream),
alongside the confidence hedge in response_postprocessor.
"""
from __future__ import annotations

from .adhd import adhd_format
from .slop import remove_slop


def apply_quality(
    text: str,
    *,
    no_slop: bool = False,
    adhd_friendly: bool = False,
) -> tuple[str, dict[str, int]]:
    """Apply enabled quality passes. Returns (text, stats)."""
    stats = {"slop_removed": 0, "adhd_changes": 0}
    if not text or not text.strip():
        return text, stats
    if no_slop:
        text, stats["slop_removed"] = remove_slop(text)
    if adhd_friendly:
        text, stats["adhd_changes"] = adhd_format(text)
    return text, stats


def register_quality_extension() -> bool:
    """Project response quality into the unified extension registry."""
    try:
        from ..extensions import ExtensionKind, ExtensionManifest, extensions
    except ImportError:
        return False
    extensions.register(
        ExtensionManifest(
            name="capability:response_quality",
            version="1.0.0",
            kind=ExtensionKind.CAPABILITY,
            description="Response quality: AI-slop cleanup and ADHD-friendly formatting.",
            enabled_by_default=True,
        )
    )
    return True


__all__ = ["adhd_format", "apply_quality", "register_quality_extension", "remove_slop"]
