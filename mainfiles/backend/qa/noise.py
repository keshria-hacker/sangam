"""Noise handling for recorded tests: timestamps, UUIDs, random IDs.

Normalization is explicit, never silent: a field is normalized only
when it matches a noise pattern (ISO/RFC timestamps, UUIDs, hex
request ids) OR its dot-path is listed in ``noise_fields``. Secrets
are never normalized — they are redacted at record time (recorder).
"""
from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}\b")
_TS_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b")
_HEX_ID_RE = re.compile(r"\b[0-9a-f]{16,64}\b")


def normalize_text(text: str) -> str:
    out = _TS_RE.sub("<timestamp>", text or "")
    out = _UUID_RE.sub("<uuid>", out)
    out = _HEX_ID_RE.sub("<id>", out)
    return out


def _strip(value, path: list[str], noise_fields: set[str]):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            dotted = ".".join([*path, str(k)])
            if dotted in noise_fields or str(k) in noise_fields:
                out[k] = "<noise>"
            else:
                out[k] = _strip(v, [*path, str(k)], noise_fields)
        return out
    if isinstance(value, list):
        return [_strip(v, path, noise_fields) for v in value]
    if isinstance(value, str):
        return normalize_text(value)
    return value


def normalize_json(value, noise_fields: list[str] | None = None):
    """Normalize a decoded JSON body for comparison."""
    return _strip(value, [], set(noise_fields or []))
