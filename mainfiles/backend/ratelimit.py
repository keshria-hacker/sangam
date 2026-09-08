"""
Rate limiting middleware for the API.

Provides per-IP and per-user rate limiting with configurable windows.
Uses Redis when ``REDIS_URL`` is configured, otherwise falls back to an
in-memory store — so the rate limiter works out of the box even without
Redis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from backend.ratelimit_redis import MemoryStore, RedisStore


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit tier."""
    requests: int          # Max requests allowed
    window_seconds: int    # Time window in seconds
    scope: str             # "ip" or "user"


# Default rate limit tiers — both IP-based and user-based
DEFAULT_LIMITS = [
    RateLimitConfig(requests=60, window_seconds=60, scope="ip"),      # 60 req/min per IP
    RateLimitConfig(requests=120, window_seconds=60, scope="user"),   # 120 req/min per authenticated user
]

# Stricter limits for specific endpoints.
ENDPOINT_LIMITS = {
    "/api/auth/login":      [RateLimitConfig(requests=5, window_seconds=60, scope="ip"),
                              RateLimitConfig(requests=5, window_seconds=60, scope="user")],
    "/api/auth/register":   [RateLimitConfig(requests=3, window_seconds=3600, scope="ip")],
    "/api/auth/forgot-password": [RateLimitConfig(requests=3, window_seconds=3600, scope="ip"),
                                   RateLimitConfig(requests=3, window_seconds=3600, scope="user")],
    "/api/auth/reset-password":  [RateLimitConfig(requests=5, window_seconds=3600, scope="ip"),
                                   RateLimitConfig(requests=5, window_seconds=3600, scope="user")],
    "/api/auth/logout":         [RateLimitConfig(requests=10, window_seconds=60, scope="ip"),
                                 RateLimitConfig(requests=10, window_seconds=60, scope="user")],
    "/api/chat/stream":     [RateLimitConfig(requests=30, window_seconds=60, scope="ip"),
                              RateLimitConfig(requests=60, window_seconds=60, scope="user")],
    "/api/files":           [RateLimitConfig(requests=20, window_seconds=60, scope="ip"),
                              RateLimitConfig(requests=40, window_seconds=60, scope="user")],
    "/api/skills/execute":  [RateLimitConfig(requests=10, window_seconds=60, scope="ip"),
                              RateLimitConfig(requests=10, window_seconds=60, scope="user")],
}

# Paths that bypass rate limiting entirely
EXEMPT_PATHS = {
    "/health", "/docs", "/openapi.json", "/",
    "/api/health", "/api/models/inaccessible/clear",
}

# Test mode: set TEST_MODE=1 to disable rate limiting (for CI/tests)
import os
TEST_MODE = os.getenv("TEST_MODE") == "1"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Apply rate limiting based on IP and/or authenticated user.

    Reads configuration from ENDPOINT_LIMITS for specific paths,
    falls back to DEFAULT_LIMITS for others.
    When a valid Authorization header is present, also applies
    user-scoped limits.

    The underlying store is auto-detected: Redis when ``REDIS_URL``
    is set, otherwise an in-memory store.
    """

    def __init__(self, app, exempt_paths: list[str] | None = None):
        super().__init__(app)
        self.store: MemoryStore | RedisStore | None = None
        self.exempt_paths = set(exempt_paths or list(EXEMPT_PATHS))

    async def _get_store(self) -> MemoryStore | RedisStore:
        """Lazy-init the store on first request (avoids startup Redis probe)."""
        if self.store is not None:
            return self.store
        from backend.ratelimit_redis import get_rate_limit_store

        self.store = await get_rate_limit_store()
        return self.store

    def _get_user_id(self, request: Request) -> str | None:
        """Extract user ID from request state (set by auth middleware)."""
        user = getattr(request.state, "user", None)
        if user and hasattr(user, "id"):
            return str(user.id)
        # Fallback: try to extract from Authorization header
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            # Use a hash of the token as the user key (privacy-safe)
            import hashlib
            token_hash = hashlib.sha256(auth[7:].encode()).hexdigest()[:16]
            return f"token:{token_hash}"
        return None

    async def dispatch(self, request: Request, call_next):
        # Test mode: skip rate limiting entirely
        if TEST_MODE:
            return await call_next(request)

        path = request.url.path

        # Skip rate limiting for exempt paths (e.g., health, docs)
        if path in self.exempt_paths:
            return await call_next(request)

        # Determine applicable limits
        limits = ENDPOINT_LIMITS.get(path, DEFAULT_LIMITS)
        client_ip = request.client.host if request.client else "unknown"
        user_id = self._get_user_id(request)
        store = await self._get_store()

        all_headers = {}
        for limit_config in limits:
            # Build the rate limit key based on scope
            if limit_config.scope == "user" and user_id:
                key = f"user:{user_id}:{path}"
            else:
                key = f"ip:{client_ip}:{path}"

            allowed, headers = await store.check_limit(
                key, limit_config.requests, limit_config.window_seconds
            )

            # Track the most restrictive remaining count
            for k, v in headers.items():
                if k not in all_headers or int(v) < int(all_headers[k]):
                    all_headers[k] = v

            if not allowed:
                return Response(
                    content='{"detail": "Rate limit exceeded. Please slow down."}',
                    status_code=429,
                    media_type="application/json",
                    headers=all_headers,
                )

        response = await call_next(request)
        for k, v in all_headers.items():
            response.headers[k] = v
        return response


def get_rate_limit_middleware():
    """Factory for the rate limit middleware (allows dependency injection in tests).

    The middleware auto-detects its backing store: Redis when ``REDIS_URL``
    is configured, in-memory otherwise.
    """
    return RateLimitMiddleware