"""
backend.analytics — opt-in local-first usage analytics (openpanel-style).

Events stay in the local SQLite DB; the dashboard shows aggregates only.
Gated by FEATURE_ANALYTICS (default off).
"""
from __future__ import annotations

from . import events
from .events import optional_user_id, record_event
from .stats import get_stats


def register_analytics_extension() -> bool:
    """Project analytics into the unified extension registry."""
    try:
        from ..extensions import ExtensionKind, ExtensionManifest, extensions
    except ImportError:
        return False
    extensions.register(
        ExtensionManifest(
            name="capability:analytics",
            version="1.0.0",
            kind=ExtensionKind.CAPABILITY,
            description="Opt-in local usage analytics with a private dashboard.",
            enabled_by_default=True,
        )
    )
    return True


__all__ = ["events", "get_stats", "optional_user_id", "record_event", "register_analytics_extension"]
