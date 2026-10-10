"""Provider resilience: retries with backoff and circuit breakers.

This module is intentionally dependency-light (stdlib + asyncio only at
import time) so it can be imported standalone. The default retryability
check lazily imports :func:`backend.response_events.normalize_error`,
which maps provider exceptions to a ``retryable`` flag (429 / 5xx /
timeouts / network errors are retryable; auth and client errors are not).
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any


class CircuitState(StrEnum):
    """Lifecycle states of a :class:`CircuitBreaker`."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a provider's circuit breaker is open."""

    def __init__(self, name: str, retry_after: float) -> None:
        super().__init__(
            f"Circuit breaker open for provider '{name}'; retry after {retry_after:.1f}s"
        )
        self.name = name
        self.retry_after = retry_after


def _default_is_retryable(exc: BaseException) -> bool:
    """Retryability via the canonical error normalizer (lazy import)."""
    from backend.response_events import normalize_error

    return normalize_error(exc).retryable


def _backoff_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    """Exponential backoff with jitter for a 0-based retry ``attempt``."""
    delay = min(max_delay, base_delay * 2**attempt)
    return delay + random.uniform(0, 0.25 * delay)


async def retry_async(
    call: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    is_retryable: Callable[[BaseException], bool] | None = None,
) -> Any:
    """Call zero-arg async ``call`` with retries on retryable errors.

    Sleeps ``min(max_delay, base_delay * 2**attempt)`` plus jitter between
    attempts. ``asyncio.CancelledError`` is never retried.
    """
    check = is_retryable or _default_is_retryable
    for attempt in range(attempts):
        try:
            return await call()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if attempt >= attempts - 1 or not check(exc):
                raise
            await asyncio.sleep(_backoff_delay(attempt, base_delay, max_delay))
    raise RuntimeError("retry_async exhausted attempts without result")  # pragma: no cover


class CircuitBreaker:
    """Per-provider circuit breaker: fail fast when a provider is down.

    After ``failure_threshold`` consecutive failures the breaker opens and
    :meth:`guard` raises :class:`CircuitOpenError` until ``cooldown_seconds``
    elapse. Then one probe is allowed (half-open): success closes the
    breaker, failure re-opens it.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        half_open_probe: bool = True,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_probe = half_open_probe
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failures(self) -> int:
        return self._failures

    def retry_after(self) -> float:
        """Seconds until the breaker allows a probe (0 if not open)."""
        if self._state != CircuitState.OPEN or self._opened_at is None:
            return 0.0
        return max(0.0, self.cooldown_seconds - (time.monotonic() - self._opened_at))

    async def guard(self) -> None:
        """Raise :class:`CircuitOpenError` if calls are currently blocked."""
        async with self._lock:
            if self._state == CircuitState.OPEN:
                remaining = self.retry_after()
                if remaining > 0:
                    raise CircuitOpenError(self.name, remaining)
                # Cooldown elapsed: allow a single half-open probe.
                if self.half_open_probe and self._probe_in_flight:
                    raise CircuitOpenError(self.name, 0.0)
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = True
            elif self._state == CircuitState.HALF_OPEN and self._probe_in_flight:
                raise CircuitOpenError(self.name, 0.0)

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED
            self._probe_in_flight = False
            self._opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            self._probe_in_flight = False
            if self._state == CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()


class CircuitBreakerRegistry:
    """Owns one :class:`CircuitBreaker` per provider id (created on demand)."""

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        half_open_probe: bool = True,
    ) -> None:
        self._defaults = {
            "failure_threshold": failure_threshold,
            "cooldown_seconds": cooldown_seconds,
            "half_open_probe": half_open_probe,
        }
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, provider_id: str) -> CircuitBreaker:
        """Return the breaker for ``provider_id``, creating it on demand."""
        breaker = self._breakers.get(provider_id)
        if breaker is None:
            breaker = CircuitBreaker(provider_id, **self._defaults)
            self._breakers[provider_id] = breaker
        return breaker

    def states(self) -> dict[str, dict[str, Any]]:
        """Snapshot of every known breaker for health reporting."""
        return {
            pid: {
                "state": b.state.value,
                "failures": b.failures,
                "retry_after": b.retry_after(),
            }
            for pid, b in self._breakers.items()
        }


#: Module-level registry used by the provider facade.
breakers = CircuitBreakerRegistry()
