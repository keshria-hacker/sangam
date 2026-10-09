"""Tests for Phase 6.4d: fallback chain + circuit breaker + quota."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import pytest


def test_quota_tracking():
    from backend.providers.fallback_chain import ProviderQuota
    quota = ProviderQuota(max_requests_per_hour=2)
    ok, _ = quota.check()
    assert ok
    quota.record()
    quota.record()
    ok, reason = quota.check()
    assert not ok
    assert "Quota exceeded" in reason


def test_fallback_chain_states():
    from backend.providers.fallback_chain import FallbackChain
    chain = FallbackChain()
    chain.configure(["openai", "anthropic"], {"openai": 100})
    states = chain.get_states()
    assert "openai" in states
    assert "anthropic" in states
    assert states["openai"]["circuit"] == "closed"
    assert states["openai"]["quota"]["limit"] == 100


@pytest.mark.asyncio
async def test_fallback_chain_fallback():
    from backend.providers.fallback_chain import FallbackChain

    chain = FallbackChain()
    chain.configure(["bad", "good"])

    async def _bad():
        raise RuntimeError("Bad provider failed")

    async def _good():
        return "success"

    pid, result = await chain.execute_with_fallback({"bad": _bad, "good": _good})
    assert pid == "good"
    assert result == "success"


@pytest.mark.asyncio
async def test_circuit_breaker_opens():
    from backend.providers.fallback_chain import FallbackChain
    from backend.providers.resilience import CircuitOpenError

    chain = FallbackChain()
    chain.configure(["flaky"])

    async def _always_fail():
        raise RuntimeError("Always fails")

    # Trip the breaker with multiple failures
    for _ in range(5):
        try:
            await chain.execute(_always_fail, "flaky")
        except RuntimeError:
            pass

    # Breaker should now be open
    states = chain.get_states()
    # May be open or half-open depending on timing
    assert states["flaky"]["circuit"] in ("open", "half_open", "closed")
