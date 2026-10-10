"""
backend.learn — learning mode (OpenMAIC interactive classroom pattern).

Teacher agent produces structured, research-first lessons; Tutor agent
gives Socratic feedback on the learner's answers. Gated by FEATURE_LEARNING.
"""
from __future__ import annotations

from .classroom import Feedback, LearnError, Lesson, start_lesson, tutor_feedback


def register_learn_extension() -> bool:
    """Project learning mode into the unified extension registry."""
    try:
        from ..extensions import ExtensionKind, ExtensionManifest, extensions
    except ImportError:
        return False
    extensions.register(
        ExtensionManifest(
            name="capability:learning",
            version="1.0.0",
            kind=ExtensionKind.CAPABILITY,
            description=(
                "Learning mode: interactive classroom with teacher lessons "
                "and Socratic tutor feedback."
            ),
            enabled_by_default=True,
        )
    )
    return True


__all__ = [
    "Feedback",
    "LearnError",
    "Lesson",
    "register_learn_extension",
    "start_lesson",
    "tutor_feedback",
]
