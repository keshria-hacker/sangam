"""
OmniRoute configuration — user-set endpoint + key, stored outside git.

OmniRoute is a self-hosted AI gateway (or cloud at api.omniroute.online)
that aggregates 290+ providers behind one OpenAI-compatible endpoint.
Sangam uses it to auto-discover LLMs: once configured, its models appear
in the model selector automatically.

Config lives in ``mainfiles/omniroute.json`` (gitignored). The API key
itself is stored encrypted in the ProviderKey table via the normal key
flow; only the endpoint URL lives here.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

DEFAULT_LOCAL_ENDPOINT = "http://localhost:20128/v1"
DEFAULT_CLOUD_ENDPOINT = "https://api.omniroute.online/v1"

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "omniroute.json"

_lock = threading.RLock()


def _read() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def get_endpoint() -> str:
    """Return the configured OmniRoute base URL (no trailing /models)."""
    with _lock:
        ep = _read().get("endpoint", DEFAULT_LOCAL_ENDPOINT)
    return (ep or DEFAULT_LOCAL_ENDPOINT).rstrip("/")


def set_endpoint(endpoint: str) -> str:
    ep = (endpoint or "").strip().rstrip("/")
    if not ep:
        raise ValueError("Endpoint URL is required")
    if not ep.startswith(("http://", "https://")):
        raise ValueError("Endpoint must start with http:// or https://")
    with _lock:
        cfg = _read()
        cfg["endpoint"] = ep
        _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return ep


def get_config_summary() -> dict:
    return {"endpoint": get_endpoint()}
