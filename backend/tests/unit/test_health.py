"""Tests for the liveness and readiness endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.infrastructure.health import ProbeResult, ProbeStatus, ReadinessReport

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.unit


async def test_health_returns_ok(client: AsyncClient) -> None:
    """Liveness reports the app identity without touching any dependency."""
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "GeoVision"
    assert body["version"] == "0.1.0"
    assert body["environment"] == "ci"


async def test_health_does_not_require_dependencies(client: AsyncClient) -> None:
    """Liveness must stay green during a database outage.

    If this endpoint touched PostgreSQL, a brief database blip would make an
    orchestrator restart the process and turn a small outage into a large one.
    """
    response = await client.get("/health")
    assert response.status_code == 200


async def test_health_response_carries_request_id(client: AsyncClient) -> None:
    """Every response is stamped with a correlation id."""
    response = await client.get("/health")
    assert response.headers.get("X-Request-ID")


async def test_inbound_request_id_is_echoed(client: AsyncClient) -> None:
    """A caller-supplied request id is preserved for cross-system tracing."""
    response = await client.get("/health", headers={"X-Request-ID": "esp32-abc-123"})
    assert response.headers["X-Request-ID"] == "esp32-abc-123"


async def test_readiness_returns_503_when_dependencies_are_down(
    client: AsyncClient,
) -> None:
    """Readiness degrades (503) rather than erroring when services are absent.

    In Module 01 the compose stack may not be running at all, so the endpoint
    must report each dependency's state instead of raising.
    """
    response = await client.get("/health/ready")

    assert response.status_code in {200, 503}
    body = response.json()
    assert body["status"] in {"ready", "degraded"}
    assert set(body["checks"]) == {"postgres", "redis", "object_storage"}
    for check in body["checks"].values():
        assert check["status"] in {"ok", "failed", "skipped"}


class TestReadinessReport:
    """Unit tests for readiness aggregation, with no I/O involved."""

    def test_ready_when_all_probes_pass(self) -> None:
        report = ReadinessReport(
            probes=[
                ProbeResult("postgres", ProbeStatus.OK, 1.2),
                ProbeResult("redis", ProbeStatus.OK, 0.4),
            ]
        )
        assert report.is_ready is True
        assert report.as_dict()["status"] == "ready"

    def test_degraded_when_any_probe_fails(self) -> None:
        report = ReadinessReport(
            probes=[
                ProbeResult("postgres", ProbeStatus.OK, 1.2),
                ProbeResult("redis", ProbeStatus.FAILED, detail="connection refused"),
            ]
        )
        assert report.is_ready is False
        assert report.as_dict()["status"] == "degraded"

    def test_skipped_probe_does_not_block_readiness(self) -> None:
        """A deliberately skipped check is not a failure."""
        report = ReadinessReport(
            probes=[ProbeResult("object_storage", ProbeStatus.SKIPPED)],
        )
        assert report.is_ready is True

    def test_latency_is_rounded_and_detail_omitted_when_empty(self) -> None:
        payload = ProbeResult("redis", ProbeStatus.OK, 1.23456).as_dict()
        assert payload == {"status": "ok", "latency_ms": 1.23}
