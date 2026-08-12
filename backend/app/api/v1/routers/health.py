"""Liveness and readiness endpoints.

The split matters operationally:

``GET /health``
    **Liveness.** Cheap, no dependencies. A container orchestrator restarts the
    process when this fails. It must never touch the database - otherwise a
    brief database blip triggers a restart loop that makes the outage worse.

``GET /health/ready``
    **Readiness.** Probes PostgreSQL, Redis, and object storage. A load
    balancer stops routing traffic here when it fails, but the process is left
    running. Also the fastest way to verify the local dev stack.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from app.core.config import Settings, get_settings
from app.infrastructure.health import check_readiness

router = APIRouter(tags=["health"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get(
    "/health",
    summary="Liveness probe",
    response_description="The process is running",
)
async def health(settings: SettingsDep) -> dict[str, Any]:
    """Report that the application process is alive.

    Deliberately dependency-free so that it stays truthful during a database
    outage.
    """
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "environment": str(settings.environment),
    }


@router.get(
    "/health/ready",
    summary="Readiness probe",
    response_description="Every dependency is reachable",
)
async def readiness(settings: SettingsDep, response: Response) -> dict[str, Any]:
    """Probe each backing service and report per-dependency status.

    Returns ``200`` when everything is reachable and ``503`` otherwise; the
    body always lists each check with its latency so a failure is immediately
    attributable to one service.
    """
    report = await check_readiness(settings)
    if not report.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    payload = report.as_dict()
    payload["version"] = settings.version
    return payload
