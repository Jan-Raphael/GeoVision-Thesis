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


async def _timed(name: str, coro: Any) -> ProbeResult:
    """Await *coro*, converting any failure into a ``FAILED`` result."""
    started = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=3.0)
    except TimeoutError:
        return ProbeResult(name, ProbeStatus.FAILED, detail="timed out after 3s")
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
    """Confirm the configured bucket exists and is reachable.

    ``boto3`` is synchronous, so it runs in a worker thread to avoid blocking
    the event loop.
    """
    import boto3
    from botocore.config import Config

    def _head_bucket() -> None:
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            use_ssl=settings.s3_use_ssl,
            config=Config(connect_timeout=3, read_timeout=3, retries={"max_attempts": 1}),
        )
        client.head_bucket(Bucket=settings.s3_bucket)

    await asyncio.to_thread(_head_bucket)


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
