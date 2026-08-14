"""Dependency health probes used by the readiness endpoint.

``/health`` proves only that the Python process is alive. ``/health/ready``
proves the process can actually do its job, which means PostgreSQL, Redis, and
the object store are all reachable. During Module 01 that distinction is how
you verify the whole dev stack in a single request instead of discovering a
misconfigured service three modules later.

Each probe is defensive: it never raises, always reports latency, and treats an
unreachable dependency as data rather than as a crash.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.config import Settings

#: Per-probe budget. Generous enough to absorb a cold client construction on
#: first request, tight enough that a hung dependency is reported promptly.
PROBE_TIMEOUT = 8.0


class ProbeStatus(StrEnum):
    """Outcome of a single dependency probe."""

    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Result of probing one dependency.

    Attributes:
        name: Dependency identifier, e.g. ``"postgres"``.
        status: Probe outcome.
        latency_ms: Round-trip time in milliseconds, ``None`` when skipped.
        detail: Short human-readable explanation on failure.
    """

    name: str
    status: ProbeStatus
    latency_ms: float | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Render for the JSON response, omitting empty fields."""
        payload: dict[str, Any] = {"status": str(self.status)}
        if self.latency_ms is not None:
            payload["latency_ms"] = round(self.latency_ms, 2)
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass(slots=True)
class ReadinessReport:
    """Aggregate readiness across every dependency."""

    probes: list[ProbeResult] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        """True when no probe failed. Skipped probes do not block readiness."""
        return all(probe.status is not ProbeStatus.FAILED for probe in self.probes)

    def as_dict(self) -> dict[str, Any]:
        """Render the full readiness payload."""
        return {
            "status": "ready" if self.is_ready else "degraded",
            "checks": {probe.name: probe.as_dict() for probe in self.probes},
        }


async def _timed(
    name: str,
    coro: Any,
    *,
    timeout: float = PROBE_TIMEOUT,  # noqa: ASYNC109 - a probe budget, not a cancellation contract
) -> ProbeResult:
    """Await *coro*, converting any failure into a ``FAILED`` result."""
    started = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError:
        return ProbeResult(name, ProbeStatus.FAILED, detail=f"timed out after {timeout:g}s")
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return ProbeResult(name, ProbeStatus.FAILED, detail=detail[:200])
    elapsed_ms = (time.perf_counter() - started) * 1000
    return ProbeResult(name, ProbeStatus.OK, latency_ms=elapsed_ms)


async def _probe_postgres(settings: Settings) -> None:
    """Open a connection and run ``SELECT 1``."""
    import asyncpg

    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
        timeout=3.0,
    )
    try:
        await conn.execute("SELECT 1")
    finally:
        await conn.close()


async def _probe_redis(settings: Settings) -> None:
    """Ping the Redis server."""
    from redis.asyncio import Redis

    client: Redis = Redis.from_url(settings.redis_url, socket_connect_timeout=3)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _probe_object_storage(settings: Settings) -> None:
    """Confirm the configured storage backend is reachable.

    Goes through the **same backend the application uses**, rather than
    building a throwaway boto3 client. Two reasons:

    1. It probes what actually serves requests. With ``GV_STORAGE_BACKEND=local``
       a boto3 probe would report on an S3 endpoint nothing else talks to -
       green light, wrong dependency.
    2. The shared client is constructed once. Building a boto3 client is
       surprisingly expensive (botocore loads its service model from disk) and
       on a cold process reliably exceeded a 3-second probe budget - which is
       exactly how this probe first failed against a perfectly healthy MinIO.

    ``exists()`` on a key that will not be there is enough: a 404 still proves
    the endpoint answered, and it avoids writing to storage on every probe.
    """
    from app.infrastructure.storage import get_storage

    storage = get_storage(settings)
    await storage.exists("_healthcheck/probe")


async def check_readiness(settings: Settings) -> ReadinessReport:
    """Probe every dependency concurrently and aggregate the results.

    Args:
        settings: Active application settings.

    Returns:
        A :class:`ReadinessReport`; ``is_ready`` is False if anything failed.
    """
    results = await asyncio.gather(
        _timed("postgres", _probe_postgres(settings)),
        _timed("redis", _probe_redis(settings)),
        _timed("object_storage", _probe_object_storage(settings)),
    )
    return ReadinessReport(probes=list(results))
