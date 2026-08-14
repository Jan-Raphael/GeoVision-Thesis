"""Replay-protection nonce cache.

Two implementations of :class:`~app.core.device_auth.NonceCache`:

``RedisNonceCache``
    ``SET NX EX`` - one atomic round trip that both tests and records the nonce.
    Shared across API workers, which is what makes it real replay protection.
``InMemoryNonceCache``
    Process-local, for tests. **Not** valid for a deployment: with several
    workers each keeps its own set, so a replayed request that lands on a
    different worker is accepted. The settings validator refuses it outside
    local development for exactly that reason.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings

__all__ = ["InMemoryNonceCache", "RedisNonceCache", "get_nonce_cache", "reset_nonce_cache"]


class RedisNonceCache:
    """Redis-backed, atomic, shared across processes."""

    def __init__(self, redis_url: str) -> None:
        """Create a lazily-connecting client."""
        from redis.asyncio import Redis

        self._redis = Redis.from_url(
            redis_url, socket_connect_timeout=3, socket_timeout=3, decode_responses=True
        )

    async def claim(self, key: str, ttl_seconds: int) -> bool:
        """Record *key* if unseen. Returns whether the claim succeeded.

        ``SET key 1 NX EX ttl`` is a single atomic operation: it sets the key
        only if absent and returns whether it did. A separate ``EXISTS`` then
        ``SET`` would leave a window in which two concurrent replays both see
        "unseen" and are both accepted.
        """
        result = await self._redis.set(key, "1", nx=True, ex=ttl_seconds)
        return bool(result)

    async def close(self) -> None:
        """Release the connection pool."""
        await self._redis.aclose()


class InMemoryNonceCache:
    """Process-local nonce cache for tests.

    See the module docstring for why this must not be used in a deployment.
    """

    def __init__(self) -> None:
        """Start with an empty store."""
        self._seen: dict[str, float] = {}

    async def claim(self, key: str, ttl_seconds: int) -> bool:
        """Record *key* if unseen, expiring entries lazily."""
        now = time.monotonic()
        # Sweep on write. The cache only ever holds one entry per request in
        # the last few minutes, so a full scan is cheaper than a background task.
        if len(self._seen) > 1000:
            self._seen = {k: v for k, v in self._seen.items() if v > now}
        if self._seen.get(key, 0.0) > now:
            return False
        self._seen[key] = now + ttl_seconds
        return True

    def clear(self) -> None:
        """Drop every entry. Tests use this for isolation."""
        self._seen.clear()


_nonce_cache: RedisNonceCache | InMemoryNonceCache | None = None


def get_nonce_cache(settings: Settings) -> RedisNonceCache | InMemoryNonceCache:
    """Return the configured nonce cache, building it on first use."""
    global _nonce_cache
    if _nonce_cache is None:
        _nonce_cache = (
            InMemoryNonceCache()
            if settings.nonce_cache_backend == "memory"
            else RedisNonceCache(settings.redis_url)
        )
    return _nonce_cache


def reset_nonce_cache() -> None:
    """Drop the cached instance. Tests call this after changing settings."""
    global _nonce_cache
    _nonce_cache = None
