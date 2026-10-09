"""Runtime feature-flag overrides.

Flags default from env (settings.FEATURE_*) but can be toggled at runtime via
POST /api/features/{name}. Overrides persist in ``{mainfiles}/feature_flags.json``
and take precedence over env defaults. Use :func:`is_enabled` as the single
source of truth instead of reading ``settings.FEATURE_*`` directly.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
OVERRIDES_PATH = BASE_DIR / "feature_flags.json"

#: Canonical flag names (without the FEATURE_ prefix, lowercase).
KNOWN_FLAGS = (
    "voice",
    "image_gen",
    "multi_agent",
    "learning",
    "analytics",
    "spec_kit",
    "mcp",
    "reasoning_effort",
    "web_search",
    "response_quality",
)

_lock = threading.RLock()
_overrides: dict[str, bool] | None = None


def _load() -> dict[str, bool]:
    global _overrides
    with _lock:
        if _overrides is None:
            _overrides = {}
            try:
                if OVERRIDES_PATH.exists():
                    data = json.loads(OVERRIDES_PATH.read_text())
                    if isinstance(data, dict):
                        _overrides = {str(k): bool(v) for k, v in data.items()}
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not load feature flag overrides: %s", exc)
        return dict(_overrides)


def _save(overrides: dict[str, bool]) -> None:
    try:
        OVERRIDES_PATH.write_text(json.dumps(overrides, indent=2, sort_keys=True))
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not persist feature flag overrides: %s", exc)


def get_overrides() -> dict[str, bool]:
    """Return the current runtime overrides (flag name -> enabled)."""
    return _load()


def set_override(name: str, enabled: bool) -> dict[str, bool]:
    """Persist a runtime override and return the full override map."""
    global _overrides
    name = name.lower()
    if name not in KNOWN_FLAGS:
        raise ValueError(f"Unknown feature flag: {name}")
    with _lock:
        current = _load()
        current[name] = bool(enabled)
        _overrides = current
        _save(current)
        return dict(current)


def clear_override(name: str) -> dict[str, bool]:
    """Remove a runtime override (falls back to env default)."""
    global _overrides
    name = name.lower()
    with _lock:
        current = _load()
        current.pop(name, None)
        _overrides = current
        _save(current)
        return dict(current)


def is_enabled(name: str) -> bool:
    """Single source of truth: override wins, else the env-backed default."""
    name = name.lower()
    overrides = _load()
    if name in overrides:
        return overrides[name]
    from .config import settings

    return bool(getattr(settings, f"FEATURE_{name.upper()}", False))


def effective_flags() -> dict[str, bool]:
    """Full flag map with overrides applied."""
    from .config import settings

    base = dict(settings.feature_flags())
    base.update(_load())
    return base


def reset_for_testing() -> None:
    """Clear in-memory overrides (tests only)."""
    global _overrides
    with _lock:
        _overrides = None
