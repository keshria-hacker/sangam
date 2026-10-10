"""Regression test: every API route endpoint must have resolvable type hints.

Catches the silent FastAPI failure where `from __future__ import annotations`
+ an unimported annotation (e.g. `request: Request` without importing Request)
makes FastAPI treat the param as a query arg instead of raising — producing
mysterious 422s. `typing.get_type_hints` raises NameError on such endpoints.
"""
from __future__ import annotations

import os
import sys
import typing
from pathlib import Path

os.environ["TEST_MODE"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def _iter_endpoints(app):
    seen = set()

    def walk(routes):
        for route in routes:
            # Recurse into mounted routers (FastAPI wraps them).
            orig = getattr(route, "original_router", None)
            if orig is not None and getattr(orig, "routes", None):
                yield from walk(orig.routes)
                continue
            sub = getattr(route, "routes", None)
            if sub:
                yield from walk(sub)
                continue
            endpoint = getattr(route, "endpoint", None)
            methods = getattr(route, "methods", None) or set()
            path = getattr(route, "path", "")
            if endpoint is None or not methods:
                continue
            if path in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
                continue
            key = (path, endpoint.__name__)
            if key in seen:
                continue
            seen.add(key)
            yield path, endpoint

    yield from walk(app.routes)


def test_all_route_type_hints_resolvable():
    from backend.main import create_app

    app = create_app()
    failures = []
    checked = 0
    for path, endpoint in _iter_endpoints(app):
        checked += 1
        try:
            typing.get_type_hints(endpoint)
        except NameError as exc:
            failures.append(f"{path}: {exc}")
        except Exception:  # noqa: BLE001 — only NameError matters here
            pass
    assert checked > 50, f"expected many routes, found {checked}"
    assert not failures, "unresolvable type hints:\n" + "\n".join(failures)


def test_no_request_param_shadow():
    """No endpoint may declare a `request` param that isn't starlette's Request."""
    from fastapi import Request

    from backend.main import create_app

    app = create_app()
    failures = []
    for path, endpoint in _iter_endpoints(app):
        try:
            hints = typing.get_type_hints(endpoint)
        except NameError:
            continue  # covered by the test above
        for name, hint in hints.items():
            if name == "request" and hint is not Request:
                failures.append(f"{path}: 'request' is not starlette Request")
    assert not failures, "\n".join(failures)
