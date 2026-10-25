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


STRATEGIES = ("priority", "cost-optimized", "headroom", "quota-weighted",
              "round-robin", "fail-closed")


def choose_provider(candidates: list[str], strategy: str,
                    states: dict[str, dict[str, Any]],
                    costs: dict[str, float] | None = None,
                    billable: set[str] | None = None,
                    round_robin_state: dict[str, Any] | None = None,
                    ) -> tuple[str | None, dict[str, Any]]:
    """OmniRoute strategy layer over Sangam's provider registry (pure).

    ``states`` maps provider id -> get_states() shape (circuit,
    quota{remaining, limit}, plus optional latency_ms / cost_per_1k).
    A provider is healthy when its circuit is closed (or unknown —
    unknown is treated as closed only when no circuit info exists)
    and its quota has remaining capacity. Returns (provider, reasons);
    provider is None when no candidate is usable — including
    fail-closed, which NEVER falls back to a billable provider.

    - priority: first healthy candidate in order.
    - cost-optimized: lowest cost among healthy (costs arg, else
      per-provider cost_per_1k in states; no cost data anywhere ->
      falls back to priority, and says so).
    - headroom: most absolute quota remaining.
    - quota-weighted: highest remaining FRACTION of quota (differs
      from headroom when limits differ).
    - round-robin: next healthy candidate after the stored index;
      the index advances in round_robin_state (caller-owned).
    - fail-closed: healthy AND not in ``billable``; if none, None.
    Session pinning is separate (FallbackChain.pin_session): a pinned
    conversation stays on its provider unless it fails.
    """
    strategy = (strategy or "priority").lower()
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown routing strategy: {strategy!r} "
                         f"(known: {', '.join(STRATEGIES)})")
    billable = billable or set()
    costs = costs or {}

    def _healthy(pid: str) -> bool:
        st = states.get(pid, {})
        circuit = st.get("circuit")
        if circuit not in (None, "closed"):
            return False
        quota = st.get("quota") or {}
        remaining = quota.get("remaining")
        if remaining is not None and remaining <= 0:
            return False
        return True

    healthy = [p for p in candidates if _healthy(p)]
    if strategy == "fail-closed":
        healthy = [p for p in healthy if p not in billable]
        if not healthy:
            return None, {"strategy": strategy, "available": False,
                          "reason": "fail-closed: no non-billable provider available; "
                                    "refusing to fall back to a billable provider"}
        return healthy[0], {"strategy": strategy, "available": True,
                            "reason": "first healthy non-billable provider in priority order"}
    if not healthy:
        return None, {"strategy": strategy, "available": False,
                      "reason": "no healthy provider with quota remaining"}
    if strategy == "priority":
        return healthy[0], {"strategy": strategy, "available": True,
                            "reason": "first healthy provider in priority order"}
    if strategy == "cost-optimized":
        def _cost(pid: str) -> float | None:
            if pid in costs:
                return costs[pid]
            return (states.get(pid, {}) or {}).get("cost_per_1k")
        priced = [(pid, _cost(pid)) for pid in healthy]
        if all(c is None for _, c in priced):
            return healthy[0], {"strategy": strategy, "available": True,
                                "reason": "no cost data for any provider — fell back to priority order"}
        pid = min(priced, key=lambda kv: (kv[1] if kv[1] is not None else float("inf"),
                                          healthy.index(kv[0])))[0]
        return pid, {"strategy": strategy, "available": True,
                     "reason": f"lowest known cost among healthy providers ({_cost(pid)})"}
    if strategy == "headroom":
        def _remaining(pid: str) -> int:
            return ((states.get(pid, {}) or {}).get("quota") or {}).get("remaining", 0) or 0
        pid = max(healthy, key=lambda p: (_remaining(p), -healthy.index(p)))
        return pid, {"strategy": strategy, "available": True,
                     "reason": f"most absolute quota remaining ({_remaining(pid)})"}
    if strategy == "quota-weighted":
        def _fraction(pid: str) -> float:
            q = (states.get(pid, {}) or {}).get("quota") or {}
            limit = q.get("limit") or 0
            return (q.get("remaining", 0) / limit) if limit else 0.0
        pid = max(healthy, key=lambda p: (_fraction(p), -healthy.index(p)))
        return pid, {"strategy": strategy, "available": True,
                     "reason": f"highest remaining quota fraction ({_fraction(pid):.2f})"}
    # round-robin
    state = round_robin_state if round_robin_state is not None else {}
    idx = int(state.get("index", 0) or 0)
    order = candidates
    for step in range(len(order)):
        pid = order[(idx + step) % len(order)]
        if pid in healthy:
            state["index"] = (idx + step + 1) % len(order)
            return pid, {"strategy": strategy, "available": True,
                         "reason": f"round-robin turn after index {idx}"}
    return None, {"strategy": strategy, "available": False,
                  "reason": "round-robin found no healthy provider"}


class FallbackChain:
    """Try providers in order, with circuit breakers and quotas."""

    def __init__(self):
        self.breakers = CircuitBreakerRegistry()
        self.quotas: dict[str, ProviderQuota] = {}
        self._order: list[str] = []
        self._pins: dict[str, str] = {}
        self._rr_state: dict[str, Any] = {"index": 0}

    def configure(self, provider_ids: list[str], quotas: dict[str, int] | None = None):
        """Set provider priority order and quotas."""
        self._order = provider_ids
        for pid in provider_ids:
            if pid not in self.quotas:
                limit = (quotas or {}).get(pid, 1000)
                self.quotas[pid] = ProviderQuota(limit)

    def pin_session(self, session_id: str, provider_id: str) -> None:
        """Pin a conversation to a provider (OmniRoute session pinning):
        it stays there unless it fails or the user switches. Unpin
        with unpin_session; a pin to an unknown provider is refused."""
        if provider_id not in self._order:
            raise ValueError(f"Unknown provider: {provider_id}")
        self._pins[session_id] = provider_id

    def unpin_session(self, session_id: str) -> None:
        self._pins.pop(session_id, None)

    def pinned_provider(self, session_id: str | None) -> str | None:
        return self._pins.get(session_id) if session_id else None

    def choose(self, strategy: str = "priority",
               candidates: list[str] | None = None,
               costs: dict[str, float] | None = None,
               billable: set[str] | None = None,
               session_id: str | None = None) -> tuple[str | None, dict[str, Any]]:
        """Strategy choice over live chain state. A pinned session
        wins over the strategy (and is reported as such) unless the
        pinned provider is unhealthy — pinning never forces a dead
        provider."""
        cands = candidates or list(self._order)
        states = self.get_states()
        pinned = self.pinned_provider(session_id)
        if pinned and pinned in cands:
            st = states.get(pinned, {})
            circuit = st.get("circuit")
            quota = st.get("quota") or {}
            if circuit in (None, "closed") and (quota.get("remaining") is None
                                               or quota["remaining"] > 0):
                return pinned, {"strategy": strategy, "available": True,
                                "reason": f"session pinned to {pinned}",
                                "pinned": True}
        provider, reasons = choose_provider(cands, strategy, states, costs=costs,
                                            billable=billable,
                                            round_robin_state=self._rr_state)
        reasons["pinned"] = False
        return provider, reasons

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
        session_id: str | None = None,
        **kwargs,
    ) -> tuple[str, Any]:
        """Try providers in order until one succeeds. Returns (provider_id, result).

        A pinned session's provider is tried first; on failure the
        chain falls through to the normal order (pinning never forces
        a dead provider)."""
        last_error = None
        order = list(self._order)
        pinned = self.pinned_provider(session_id)
        if pinned and pinned in order:
            order = [pinned] + [p for p in order if p != pinned]
        for pid in order:
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
        # Phase 7: auto-configure with default provider order.
        # Local first (ollama), then cloud providers.
        _fallback_chain.configure([
            "ollama", "openai", "anthropic", "gemini", "groq",
            "together", "openrouter", "deepseek", "mistral", "nvidia",
            "omniroute",
        ])
    return _fallback_chain


def reset_fallback_chain() -> None:
    """Reset the global chain (for tests)."""
    global _fallback_chain
    _fallback_chain = None
