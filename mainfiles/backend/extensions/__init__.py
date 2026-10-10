"""Sangam extensions — one unified surface for every pluggable capability.

Tools (``backend.tools``) and skills (``backend.skills``) are projected into a
single :class:`ExtensionRegistry` so they can be listed, enabled, and disabled
through one API, while the original registries keep working untouched.

Typical bootstrap::

    from backend.extensions import extensions, initialize_extensions

    initialize_extensions()          # register every tool + skill once
    extensions.list_enabled()        # what's active right now
    extensions.disable("tool:web_search")
"""
from __future__ import annotations

from .manifest import ExtensionKind, ExtensionManifest
from .registry import (
    ExtensionRegistry,
    extensions,
    initialize_extensions,
    is_initialized,
)

__all__ = [
    "ExtensionKind",
    "ExtensionManifest",
    "ExtensionRegistry",
    "extensions",
    "initialize_extensions",
    "is_initialized",
]
