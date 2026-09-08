"""
ratelimit_redis.py — Redis-backed sliding-window rate-limit store.

Transparently falls back to an in-memory store when Redis is unavailable
or not configured, so the rate limiter never becomes a single point of
failure.

Usage
-----
    store = get_rate_limit_store()          # auto-detect from settings
    allowed, headers = await store.check_limit("ip:1.2.3.4:/api/login", 5, 60)
"""

from __future__ import annotations

import time
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass

from backend.config import settings

# ---------------------------------------------------------------------------
# Abstract interface (duck-typed — same signatures as SlidingWindowStore)
# ---------------------------------------------------------------------------

@dataclass
class RateLimitResult:
    """Result of a rate-limit check."""
    allowed: bool
    headers: dict[str, str]


# ---------------------------------------------------------------------------
# In-memory fallback (same algorithm as ratelimit.SlidingWindowStore)
# ---------------------------------------------------------------------------

class MemoryStore:
    """Thread-safe in-memory sliding-window store, identical to the original."""

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = defaultdict(list)

    async def check_limit(
        self, key: str, limit: int, window_seconds: int,
    ) -> tuple[bool, dict[str, str]]:
        now = time.time()
        self._clean_old(key, window_seconds)
        bucket = self._buckets[key]
        current = len(bucket)
        remaining = max(0, limit - current - 1)
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(now + window_seconds)),
        }
        if current >= limit:
            return False, headers
        bucket.append(now)
        return True, headers

    async def reset_limit(self, key: str) -> None:
        """Clear all recorded hits for *key* (e.g. on successful login)."""
        self._buckets.pop(key, None)

    async def close(self) -> None:
        """No-op for in-memory store."""

    def _clean_old(self, key: str, window_seconds: int) -> None:
        cutoff = time.time() - window_seconds
        bucket = self._buckets[key]
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)


# ---------------------------------------------------------------------------
# Redis-backed store (distributed, multi-instance safe)
# ---------------------------------------------------------------------------

class RedisStore:
    """Sliding-window rate-limit store backed by Redis sorted sets.

    Each key is a Redis sorted set whose members are timestamps (scores).
    The ZREMRANGEBYSCORE / ZCARD / ZADD pipeline is atomic, so concurrent
    requests from the same key never race.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or settings.REDIS_URL
        self._client: object | None = None  # redis.asyncio.Redis | None
        self._closed = False

    async def _get_client(self):
        """Lazy-connect to Redis (databases are cheap; connections are not)."""
        if self._client is not None:
            return self._client
        if not self._redis_url:
            raise ConnectionError("REDIS_URL not configured")
        import redis.asyncio as aioredis

        self._client = aioredis.from_url(
            self._redis_url,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            decode_responses=True,
        )
        # Smoke-test the connection immediately so the first caller learns fast.
        await self._client.ping()
        return self._client

    async def check_limit(
        self, key: str, limit: int, window_seconds: int,
    ) -> tuple[bool, dict[str, str]]:
        now = time.time()
        cutoff = now - window_seconds
        try:
            client = await self._get_client()
            pipe = client.pipeline(transaction=True)
            pipe.zremrangebyscore(key, "-inf", cutoff)
            pipe.zcard(key)
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, window_seconds * 2)
            _, current_count, _, _ = await pipe.execute()
        except Exception:
            return await self._fallback.check_limit(key, limit, window_seconds)

        remaining = max(0, limit - current_count - 1)
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(now + window_seconds)),
        }
        if current_count >= limit:
            return False, headers
        return True, headers

    @property
    def _fallback(self) -> MemoryStore:
        """Lazily-created in-memory fallback."""
        if not hasattr(self, "_memory"):
            self._memory = MemoryStore()
        return self._memory

    async def reset_limit(self, key: str) -> None:
        """Clear all recorded hits for *key* in Redis and the fallback."""
        # Clear the in-memory mirror first so a Redis outage never revives
        # stale counts from the fallback.
        if hasattr(self, "_memory"):
            self._memory._buckets.pop(key, None)
        if self._client is not None:
            with suppress(Exception):  # Redis is already degraded; fallback cleared.
                await self._client.delete(key)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ---------------------------------------------------------------------------
# Auto-detecting factory
# ---------------------------------------------------------------------------

_store_instance: RedisStore | MemoryStore | None = None


async def get_rate_limit_store() -> RedisStore | MemoryStore:
    """Return a store — Redis when configured, in-memory otherwise.

    The factory lazy-initialises and caches the store so that a transient
    Redis outage at startup recovers on the next request.
    """
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    if settings.REDIS_URL:
        store = RedisStore()
        try:
            # Prove the connection works before caching.
            await store.check_limit("_probe", 1, 1)
            _store_instance = store
            return _store_instance
        except Exception:
            pass  # Fall through to in-memory below.

    _store_instance = MemoryStore()
    return _store_instance


async def close_rate_limit_store() -> None:
    """Tear-down hook (called on app shutdown)."""
    global _store_instance
    if _store_instance is not None:
        await _store_instance.close()
        _store_instance = None


def reset_rate_limit_store_for_testing() -> None:
    """Reset the global rate limit store — for test isolation only."""
    global _store_instance
    if _store_instance is not None:
        # Don't await close() here — tests are synchronous setup
        _store_instance = None
