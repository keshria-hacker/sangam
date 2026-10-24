"""DRAFT regression test — ARCHITECTURE.md §13.2 must match live API routes.

Why: the §13.2 table drifted badly (26 live routes missing, 1 wrong method,
2 phantom rows documenting deleted routes) — twice in two days. This test
diffs the table against the real FastAPI routes so docs can't silently drift
again.

Placement: copy to `tests/test_docs_routes_drift.py` in the Sangam repo.
Follows the same app-building pattern as `tests/test_route_hints.py`.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def _norm(path: str) -> str:
    path = path.split("?")[0].rstrip("/")
    return re.sub(r"\{[^}]+\}", "{}", path) or "/"


def _walk(routes, prefix=""):
    # Phase 0 fix: FastAPI include_router() wraps routers as
    # _IncludedRouter objects whose inner routes carry NO prefix — the
    # prefix lives on include_context.prefix. The old walk ignored that,
    # so every /api route came out bare, was filtered out by
    # _live_routes(), and the test saw 0 live routes. Apply the prefix
    # as we recurse so the walked paths are the real served paths.
    seen: set[tuple[str, str]] = set()
    for route in routes:
        orig = getattr(route, "original_router", None)
        if orig is not None and getattr(orig, "routes", None):
            ctx = getattr(route, "include_context", None)
            route_prefix = getattr(ctx, "prefix", "") or ""
            yield from _walk(orig.routes, prefix + route_prefix)
            continue
        sub = getattr(route, "routes", None)
        if sub:
            # Mounts carry their own path prefix.
            mount_prefix = getattr(route, "path", "") or ""
            yield from _walk(sub, prefix + mount_prefix)
            continue
        endpoint = getattr(route, "endpoint", None)
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if endpoint is None or not methods:
            continue
        full_path = prefix + path
        if full_path in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
            continue
        key = (full_path, endpoint.__name__)
        if key in seen:
            continue
        seen.add(key)
        yield full_path, methods


def _live_routes(app):
    seen: set[tuple[str, str]] = set()
    for path, methods in _walk(app.routes):
        if path.startswith("/api/v1"):  # duplicate mount of the same routers
            continue
        if not path.startswith("/api/"):
            continue  # frontend "/" and root health aren't API routes
        for method in sorted(methods):
            if method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                seen.add((method, _norm(path)))
    return seen


def _table_routes():
    doc = _ROOT / "ARCHITECTURE.md"
    text = doc.read_text()
    start = text.index("### 13.2 API Endpoints Summary")
    end = text.index("### 13.3", start)
    section = text[start:end]
    rows: set[tuple[str, str]] = set()
    for line in section.splitlines():
        m = re.match(r"\|\s*([A-Z]+)\s*\|\s*`(/api[^`]*)`", line)
        if m:
            rows.add((m.group(1), _norm(m.group(2))))
    return rows


def test_docs_table_matches_live_routes():
    from backend.main import create_app

    app = create_app()
    live = _live_routes(app)
    table = _table_routes()
    assert len(live) > 50, f"expected many routes, found {len(live)}"
    missing = sorted(live - table)
    stale = sorted(table - live)
    detail = ""
    if missing:
        detail += "live routes missing from §13.2:\n" + "\n".join(
            f"  {m} {p}" for m, p in missing
        )
    if stale:
        detail += "\ntable rows with no live route:\n" + "\n".join(
            f"  {m} {p}" for m, p in stale
        )
    assert not missing and not stale, (
        "ARCHITECTURE.md §13.2 drifted from the code:\n" + detail
    )
