"""Tests for backend/providers/resilience.py (F5: provider resilience).

The resilience module is loaded standalone (synthetic ``backend.providers``
package entry) to prove it stays importable without the heavy provider
dependency chain. ``normalize_error`` still comes from the real
``backend.response_events`` module.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mainfiles" / "backend"
if str(ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(ROOT / "mainfiles"))

import backend  # noqa: F401,E402  # light package (docstring only); needs sys.path above


def _load_resilience_standalone():
    """Load resilience.py without executing backend/providers/__init__.py."""
    providers_pkg = types.ModuleType("backend.providers")
    providers_pkg.__path__ = [str(BACKEND / "providers")]
    spec = importlib.util.spec_from_file_location(
        "backend.providers.resilience",
        BACKEND / "providers" / "resilience.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    return providers_pkg, module, spec


@pytest.fixture(scope="module")
def resilience():
    """Provide the standalone-loaded resilience module; restore sys.modules after."""
    providers_pkg, module, spec = _load_resilience_standalone()
    added: list[str] = []
    overwritten: dict[str, types.ModuleType] = {}

    def _install(name: str, mod: types.ModuleType) -> None:
        if name in sys.modules:
            overwritten[name] = sys.modules[name]
        else:
            added.append(name)
        sys.modules[name] = mod

    _install("backend.providers", providers_pkg)
    _install("backend.providers.resilience", module)
    spec.loader.exec_module(module)
    yield module
    for name in added:
        sys.modules.pop(name, None)
    sys.modules.update(overwritten)


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        f"status {status}",
        request=httpx.Request("GET", "https://example.com/v1/chat"),
        response=httpx.Response(status),
    )


# =============================================================================
# retry_async
# =============================================================================


async def test_retry_async_succeeds_after_retryable_failures(resilience):
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("connection refused")
        return "ok"

    result = await resilience.retry_async(flaky, attempts=5, base_delay=0.001)
    assert result == "ok"
    assert calls["n"] == 3


async def test_retry_async_exhausts_attempts_then_raises(resilience):
    calls = {"n": 0}

    async def always_down():
        calls["n"] += 1
        raise _http_status_error(503)

    with pytest.raises(httpx.HTTPStatusError):
        await resilience.retry_async(always_down, attempts=3, base_delay=0.001)
    assert calls["n"] == 3


async def test_retry_async_gives_up_immediately_on_non_retryable(resilience):
    calls = {"n": 0}

    async def bad_key():
        calls["n"] += 1
        raise _http_status_error(401)

    with pytest.raises(httpx.HTTPStatusError):
        await resilience.retry_async(bad_key, attempts=3, base_delay=0.001)
    assert calls["n"] == 1


async def test_retry_async_never_retries_cancelled_error(resilience):
    calls = {"n": 0}

    async def cancelled():
        calls["n"] += 1
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await resilience.retry_async(cancelled, attempts=3, base_delay=0.001)
    assert calls["n"] == 1


async def test_retry_async_custom_is_retryable(resilience):
    calls = {"n": 0}

    async def flaky_custom():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("always retry me")
        return "second"

    result = await resilience.retry_async(
        flaky_custom,
        attempts=3,
        base_delay=0.001,
        is_retryable=lambda exc: isinstance(exc, RuntimeError),
    )
    assert result == "second"
    assert calls["n"] == 2


# =============================================================================
# CircuitBreaker
# =============================================================================


async def test_breaker_starts_closed(resilience):
    breaker = resilience.CircuitBreaker("p1")
    assert breaker.state == resilience.CircuitState.CLOSED
    await breaker.guard()  # must not raise


async def test_breaker_opens_after_threshold(resilience):
    breaker = resilience.CircuitBreaker("p1", failure_threshold=3, cooldown_seconds=60.0)
    await breaker.record_failure()
    await breaker.record_failure()
    await breaker.guard()  # still closed
    await breaker.record_failure()
    assert breaker.state == resilience.CircuitState.OPEN
    with pytest.raises(resilience.CircuitOpenError) as exc_info:
        await breaker.guard()
    assert exc_info.value.name == "p1"
    assert exc_info.value.retry_after > 0


async def test_breaker_half_open_probe_recovers(resilience):
    breaker = resilience.CircuitBreaker("p1", failure_threshold=1, cooldown_seconds=0.05)
    await breaker.record_failure()
    assert breaker.state == resilience.CircuitState.OPEN
    await asyncio.sleep(0.08)  # let the cooldown elapse
    await breaker.guard()  # half-open probe allowed
    assert breaker.state == resilience.CircuitState.HALF_OPEN
    await breaker.record_success()
    assert breaker.state == resilience.CircuitState.CLOSED
    await breaker.guard()  # closed again


async def test_breaker_half_open_failure_reopens(resilience):
    breaker = resilience.CircuitBreaker("p1", failure_threshold=1, cooldown_seconds=0.05)
    await breaker.record_failure()
    await asyncio.sleep(0.08)
    await breaker.guard()  # probe
    await breaker.record_failure()  # probe failed
    assert breaker.state == resilience.CircuitState.OPEN
    with pytest.raises(resilience.CircuitOpenError):
        await breaker.guard()


async def test_breaker_single_probe_in_flight(resilience):
    breaker = resilience.CircuitBreaker("p1", failure_threshold=1, cooldown_seconds=0.05)
    await breaker.record_failure()
    await asyncio.sleep(0.08)
    await breaker.guard()  # first probe takes the slot
    with pytest.raises(resilience.CircuitOpenError):
        await breaker.guard()  # second caller rejected while probing


async def test_breaker_success_resets_failure_count(resilience):
    breaker = resilience.CircuitBreaker("p1", failure_threshold=3, cooldown_seconds=60.0)
    await breaker.record_failure()
    await breaker.record_failure()
    await breaker.record_success()
    await breaker.record_failure()
    await breaker.record_failure()
    await breaker.guard()  # still closed: count was reset
    assert breaker.state == resilience.CircuitState.CLOSED


# =============================================================================
# CircuitBreakerRegistry
# =============================================================================


def test_registry_get_returns_same_instance_per_id(resilience):
    registry = resilience.CircuitBreakerRegistry()
    assert registry.get("openai") is registry.get("openai")
    assert registry.get("openai") is not registry.get("anthropic")


def test_registry_states_shape(resilience):
    registry = resilience.CircuitBreakerRegistry()
    assert registry.states() == {}
    registry.get("openai")
    states = registry.states()
    assert set(states) == {"openai"}
    entry = states["openai"]
    assert entry["state"] == "closed"
    assert entry["failures"] == 0
    assert entry["retry_after"] == 0.0


async def test_registry_breaker_tracks_failures(resilience):
    registry = resilience.CircuitBreakerRegistry(failure_threshold=2)
    breaker = registry.get("groq")
    await breaker.record_failure()
    assert registry.states()["groq"]["failures"] == 1
    assert registry.states()["groq"]["state"] == "closed"
    await breaker.record_failure()
    assert registry.states()["groq"]["state"] == "open"


def test_module_level_breakers_singleton(resilience):
    assert resilience.breakers.get("x") is resilience.breakers.get("x")
    assert isinstance(resilience.breakers, resilience.CircuitBreakerRegistry)


# =============================================================================
# _stream_with_resilience (integration in backend.providers)
# =============================================================================

try:
    import backend.providers as _providers_pkg

    _HAS_PROVIDERS_PKG = True
except ImportError:  # full provider deps (litellm, …) not installed
    _providers_pkg = None
    _HAS_PROVIDERS_PKG = False

needs_providers_pkg = pytest.mark.skipif(
    not _HAS_PROVIDERS_PKG, reason="backend.providers requires full dependencies"
)
providers_pkg = _providers_pkg


@needs_providers_pkg
async def test_stream_with_resilience_happy_path():
    async def factory():
        yield "a"
        yield "b"

    chunks = [c async for c in providers_pkg._stream_with_resilience("test-ok", factory)]
    assert chunks == ["a", "b"]
    assert providers_pkg.breakers.get("test-ok").state == providers_pkg.CircuitState.CLOSED


@needs_providers_pkg
async def test_stream_with_resilience_retries_before_first_chunk(monkeypatch):
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("down")
        yield "recovered"

    async def no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    chunks = [
        c async for c in providers_pkg._stream_with_resilience("test-retry", factory, attempts=3)
    ]
    assert chunks == ["recovered"]
    assert calls["n"] == 2


@needs_providers_pkg
async def test_stream_with_resilience_no_retry_after_chunks_yielded():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        yield "partial"
        raise _http_status_error(503)

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in providers_pkg._stream_with_resilience("test-partial", factory):
            pass
    assert calls["n"] == 1  # no retry: a chunk was already yielded
    assert providers_pkg.breakers.get("test-partial").failures == 1


@needs_providers_pkg
async def test_stream_with_resilience_non_retryable_raises_fast():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        raise _http_status_error(401)
        yield "never"  # pragma: no cover

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in providers_pkg._stream_with_resilience("test-401", factory):
            pass
    assert calls["n"] == 1


@needs_providers_pkg
async def test_stream_with_resilience_open_circuit_raises():
    breaker = providers_pkg.breakers.get("test-open")
    for _ in range(5):
        await breaker.record_failure()
    assert breaker.state == providers_pkg.CircuitState.OPEN

    async def factory():
        yield "never"  # pragma: no cover

    with pytest.raises(providers_pkg.CircuitOpenError):
        async for _ in providers_pkg._stream_with_resilience("test-open", factory):
            pass


@needs_providers_pkg
async def test_stream_with_resilience_never_retries_cancelled():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        raise asyncio.CancelledError()
        yield "never"  # pragma: no cover

    with pytest.raises(asyncio.CancelledError):
        async for _ in providers_pkg._stream_with_resilience("test-cancel", factory):
            pass
    assert calls["n"] == 1
