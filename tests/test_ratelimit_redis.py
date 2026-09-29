"""
Tests for the rate-limit store ``reset_limit`` method (audit C-007).

The brute-force login lockout needs a way to clear a key's recorded hits
on a successful login. Both MemoryStore and RedisStore must support it,
including clearing the in-memory fallback that RedisStore mirrors.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mainfiles"))

os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

from backend.ratelimit_redis import MemoryStore, RedisStore  # noqa: E402


class MemoryStoreResetLimitTests(unittest.TestCase):
    """``MemoryStore.reset_limit`` clears recorded hits for a key."""

    def setUp(self):
        self.store = MemoryStore()

    def test_reset_limit_clears_recorded_hits(self):
        """After a reset the same key gets a fresh budget again."""
        async def scenario():
            for _ in range(3):
                allowed, _ = await self.store.check_limit("login_fail:alice", 3, 900)
                self.assertTrue(allowed)
            # 4th hit is blocked while the counter is full.
            allowed, _ = await self.store.check_limit("login_fail:alice", 3, 900)
            self.assertFalse(allowed)

            await self.store.reset_limit("login_fail:alice")

            allowed, _ = await self.store.check_limit("login_fail:alice", 3, 900)
            self.assertTrue(allowed)

        asyncio.run(scenario())

    def test_reset_limit_unknown_key_is_noop(self):
        """Resetting a key that was never used must not raise."""
        async def scenario():
            await self.store.reset_limit("never-used")

        asyncio.run(scenario())


class RedisStoreResetLimitTests(unittest.TestCase):
    """``RedisStore.reset_limit`` deletes the Redis key and the fallback."""

    def test_reset_limit_deletes_redis_key(self):
        """The Redis key is deleted via the connected client."""
        async def scenario():
            store = RedisStore("redis://localhost:6379")
            store._client = AsyncMock()

            await store.reset_limit("login_fail:alice")

            store._client.delete.assert_awaited_once_with("login_fail:alice")

        asyncio.run(scenario())

    def test_reset_limit_clears_fallback_bucket(self):
        """Hits recorded in the in-memory fallback are cleared too."""
        async def scenario():
            store = RedisStore("redis://localhost:6379")
            store._client = AsyncMock()

            await store._fallback.check_limit("login_fail:alice", 5, 900)
            self.assertEqual(len(store._fallback._buckets["login_fail:alice"]), 1)

            await store.reset_limit("login_fail:alice")

            self.assertNotIn("login_fail:alice", store._fallback._buckets)

        asyncio.run(scenario())

    def test_reset_limit_without_client_is_noop(self):
        """No connected client (Redis unavailable) must not raise."""
        async def scenario():
            store = RedisStore()  # REDIS_URL not configured -> no client
            await store.reset_limit("whatever")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
