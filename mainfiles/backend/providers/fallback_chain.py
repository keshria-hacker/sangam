"""
fallback_chain.py — provider fallback with circuit breakers and quotas (Phase 6.4d).

Tries providers in priority order. Each provider has:
- Circuit breaker (from resilience.py)
- Quota (max requests per hour, configurable)
- Cooldown after failures
"""
from __future__ import annotations

import time
from typing import Any

from .resilience import CircuitBreakerRegistry, CircuitOpenError


class ProviderQuota:
    """Track per-provider usage against a quota."""

    def __init__(self, max_requests_per_hour: int = 1000):
        self.max_requests = max_requests_per_hour
        self._requests: list[float] = []  # timestamps

    def check(self) -> tuple[bool, str | None]:
        """Check if quota allows another request."""
        now = time.time()
        # Remove old entries (> 1 hour)
        self._requests = [t for t in self._requests if now - t < 3600]
        if len(self._requests) >= self.max_requests:
            return False, f"Quota exceeded ({self.max_requests}/hour)"
        return True, None

    def record(self):
        self._requests.append(time.time())

    def usage(self) -> dict[str, Any]:
        now = time.time()
        recent = [t for t in self._requests if now - t < 3600]
        return {
            "used": len(recent),
            "limit": self.max_requests,
            "remaining": max(0, self.max_requests - len(recent)),
        }


class FallbackChain:
    """Try providers in order, with circuit breakers and quotas."""

    def __init__(self):
        self.breakers = CircuitBreakerRegistry()
        self.quotas: dict[str, ProviderQuota] = {}
        self._order: list[str] = []

    def configure(self, provider_ids: list[str], quotas: dict[str, int] | None = None):
        """Set provider priority order and quotas."""
        self._order = provider_ids
        for pid in provider_ids:
            if pid not in self.quotas:
                limit = (quotas or {}).get(pid, 1000)
                self.quotas[pid] = ProviderQuota(limit)

    def get_states(self) -> dict[str, dict[str, Any]]:
        """Get circuit breaker + quota state for all providers."""
        states = self.breakers.states()
        result = {}
        for pid in self._order:
            breaker = self.breakers.get(pid)
            quota = self.quotas.get(pid)
            result[pid] = {
                "circuit": breaker.state.value,
                "failures": breaker.failures,
                "retry_after": breaker.retry_after,
                "quota": quota.usage() if quota else None,
            }
        return result

    async def execute(
        self,
        fn: Any,
        provider_id: str,
        *args,
        **kwargs,
    ) -> Any:
        """Execute with circuit breaker and quota check for a specific provider."""
        # Quota check
        quota = self.quotas.get(provider_id)
        if quota:
            ok, reason = quota.check()
            if not ok:
                raise RuntimeError(f"Provider {provider_id}: {reason}")

        # Circuit breaker guard
        breaker = self.breakers.get(provider_id)
        await breaker.guard()  # Raises CircuitOpenError if open

        try:
            result = await fn(*args, **kwargs)
            await breaker.record_success()
            if quota:
                quota.record()
            return result
        except Exception as exc:
            await breaker.record_failure()
            raise

    async def execute_with_fallback(
        self,
        fns: dict[str, Any],
        *args,
        **kwargs,
    ) -> tuple[str, Any]:
        """Try providers in order until one succeeds. Returns (provider_id, result)."""
        last_error = None
        for pid in self._order:
            if pid not in fns:
                continue
            try:
                result = await self.execute(fns[pid], pid, *args, **kwargs)
                return pid, result
            except CircuitOpenError as e:
                last_error = e
                continue  # Try next provider
            except RuntimeError as e:
                # Quota errors -> try next provider; other RuntimeErrors -> try next too
                last_error = e
                continue
            except Exception as e:
                last_error = e
                continue  # Try next provider

        raise RuntimeError(f"All providers failed. Last error: {last_error}")


# Global instance
_fallback_chain: FallbackChain | None = None


def get_fallback_chain() -> FallbackChain:
    global _fallback_chain
    if _fallback_chain is None:
        _fallback_chain = FallbackChain()
    return _fallback_chain
