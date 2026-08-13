"""Per-account throttling of failed authentication attempts.

Complements the per-IP rate limiter in :mod:`app.core.rate_limit`, which
defends a different flank. Per-IP limiting stops one host hammering the login
endpoint but is trivially bypassed by an attacker with many source addresses;
this counts failures against the **account being targeted**, so a
credential-stuffing run spread across a botnet still trips for that account.

Two design choices worth noting:

* **Only failures count.** A user logging in correctly is never throttled, no
  matter how often. Counting successes would punish a busy dashboard tab.
* **Keys are hashed.** Usernames and email addresses never enter the store, so
  a dump of throttle state discloses nothing about who has accounts.

The backend is an in-process dictionary today, which is correct for a single
worker and honest about its limitation: with several API processes each keeps
its own count, so the effective allowance multiplies. :class:`RedisThrottle`
replaces it once Redis is available (Module 05) — same interface, atomic
``INCR``, shared across workers.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Protocol

from app.core.exceptions import RateLimitedError

__all__ = [
    "AttemptThrottle",
    "InMemoryThrottle",
    "get_login_throttle",
    "throttle_key",
]

#: Failed logins allowed per account inside the window.
MAX_LOGIN_FAILURES = 5
#: Window length in seconds.
LOGIN_FAILURE_WINDOW = 300


def throttle_key(identifier: str) -> str:
    """Derive a storage key from a login identifier.

    Hashed and case-folded: ``Jan_M`` and ``jan_m`` share a bucket (they are
    the same account), and neither string is retained.
    """
    return hashlib.sha256(identifier.strip().lower().encode()).hexdigest()[:32]


class AttemptThrottle(Protocol):
    """Counts failed attempts against a key."""

    async def check(self, key: str) -> None:
        """Raise :class:`RateLimitedError` if *key* is currently locked out."""
        ...

    async def record_failure(self, key: str) -> int:
        """Count one failure and return the new total inside the window."""
        ...

    async def reset(self, key: str) -> None:
        """Clear the counter — called after a successful authentication."""
        ...


@dataclass
class _Bucket:
    """One key's failure count and when its window opened."""

    count: int = 0
    window_started: float = 0.0


@dataclass
class InMemoryThrottle:
    """Process-local fixed-window throttle.

    Adequate for a single API worker. See the module docstring for why this is
    a stopgap rather than the final answer.
    """

    max_attempts: int = MAX_LOGIN_FAILURES
    window_seconds: int = LOGIN_FAILURE_WINDOW
    _buckets: dict[str, _Bucket] = field(default_factory=dict)

    def _current(self, key: str) -> _Bucket:
        """Return the live bucket for *key*, rolling the window if it expired."""
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None or now - bucket.window_started >= self.window_seconds:
            bucket = _Bucket(count=0, window_started=now)
            self._buckets[key] = bucket
        return bucket

    async def check(self, key: str) -> None:
        """Deny if the account has already exhausted its failure allowance."""
        bucket = self._current(key)
        if bucket.count >= self.max_attempts:
            remaining = int(self.window_seconds - (time.monotonic() - bucket.window_started))
            raise RateLimitedError(
                "Too many failed sign-in attempts for this account. "
                f"Try again in about {max(remaining, 1)} seconds.",
                details={"retry_after_seconds": max(remaining, 1)},
            )

    async def record_failure(self, key: str) -> int:
        """Count one failed attempt."""
        bucket = self._current(key)
        bucket.count += 1
        return bucket.count

    async def reset(self, key: str) -> None:
        """Clear the counter after a successful sign-in."""
        self._buckets.pop(key, None)

    def clear(self) -> None:
        """Drop every counter. Tests use this for isolation."""
        self._buckets.clear()


_login_throttle: InMemoryThrottle | None = None


def get_login_throttle() -> InMemoryThrottle:
    """Return the process-wide login throttle."""
    global _login_throttle
    if _login_throttle is None:
        _login_throttle = InMemoryThrottle()
    return _login_throttle


def reset_login_throttle() -> None:
    """Drop the throttle. Tests call this between cases."""
    global _login_throttle
    _login_throttle = None
