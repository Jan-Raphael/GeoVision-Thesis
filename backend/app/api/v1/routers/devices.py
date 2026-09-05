"""Pairing and device management, for the owner's dashboard (spec B.2)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import (
    AccessContextDep,
    AuditDep,
    ClientIPDep,
    ClockDep,
    CurrentUser,
    DeviceRepoDep,
    PairingTokenRepoDep,
    ProjectRepoDep,
    SettingsDep,
    require_permission,
)
from app.api.route import TransactionalRoute
from app.api.schemas.common import MessageResponse
from app.api.schemas.projects import DeviceSummaryResponse
from app.api.v1.presenters import present_device
from app.application.use_cases.devices import (
    ClaimPairingToken,
    IssuePairingToken,
    UnpairDevice,
    UpdateDeviceSettings,
)
from app.core.rate_limit import get_limiter
from app.domain.entities import CaptureSchedule
from app.domain.enums import CameraFace, Permission
from app.domain.services.authorization import AccessContext
from app.infrastructure.audit import AuditAction
from app.infrastructure.qr import build_pair_page_qr, build_provisioning_qr

router = APIRouter(tags=["devices"], route_class=TransactionalRoute)
limiter = get_limiter()

ProjectId = Annotated[UUID, Path(description="Project id")]
DeviceId = Annotated[UUID, Path(description="Device id")]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PairingTokenRequest(BaseModel):
    """Ask for a code to pair one camera face."""

    model_config = ConfigDict(extra="forbid")

    face: CameraFace = CameraFace.FRONT_DIAGONAL
    replace_existing: bool = Field(
        default=False, description="Allow re-pairing a face that already has a camera"
    )


class PairingTicketResponse(BaseModel):
    """What the pairing modal shows. The code appears exactly once."""

    display_code: str = Field(description="Type this into the camera's setup page")
    formatted_code: str = Field(description="Grouped for readability: K7M2-9XQF")
    expires_at: str
    expires_in_seconds: int
    project_code: str
    face: CameraFace
    device_name: str
    qr_png_base64: str = Field(description="Scan instead of typing")
    pair_page_url: str = Field(description="Opens a browser page to pair a phone or webcam")
    pair_page_qr_base64: str = Field(description="Scan with a phone to open pair_page_url")


class ClaimRequest(BaseModel):
    """Sent by the camera itself during provisioning."""

    model_config = ConfigDict(extra="forbid")

    # Named to match Device-Pairing-Protocol.md Phase 2 exactly. Module 13's
    # firmware is written from that note, so a field the server calls something
    # else is a bug waiting to be found on a roof.
    display_code: Annotated[str, Field(min_length=6, max_length=16)]
    hardware_id: Annotated[str | None, Field(default=None, max_length=64)]
    firmware_version: Annotated[str | None, Field(default=None, max_length=32)]


class ClaimResponse(BaseModel):
    """The device's credentials. ``device_secret`` is never shown again."""

    device_id: UUID
    device_secret: str = Field(description="Store in NVS. Not retrievable later.")
    device_name: str
    project_code: str
    face: CameraFace
    capture_times: list[str]
    timezone: str
    server_time: str


class DeviceSettingsRequest(BaseModel):
    """Adjust a paired camera."""

    model_config = ConfigDict(extra="forbid")

    weight: Annotated[float | None, Field(default=None, gt=0, le=5)]
    capture_times: Annotated[list[str] | None, Field(default=None, max_length=6)]
    timezone: Annotated[str | None, Field(default=None, max_length=64)]
    jitter_seconds: Annotated[int | None, Field(default=None, ge=0, le=1800)]
    enabled: bool | None = None
    homography: dict | None = None
    roi_polygon: dict | None = None


# ---------------------------------------------------------------------------
# Owner-facing endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/devices",
    summary="Cameras paired to this project",
    response_model=list[DeviceSummaryResponse],
)
async def list_devices(
    project_id: ProjectId,
    access: AccessContextDep,
    devices: DeviceRepoDep,
    clock: ClockDep,
) -> list[DeviceSummaryResponse]:
    """The Devices panel: which cameras are connected, and how they are doing."""
    _ = access
    found = await devices.list_for_project(project_id)
    now = clock.now()
    return [present_device(device, liveness=device.liveness_at(now)) for device in found]


@router.post(
    "/projects/{project_id}/pairing-tokens",
    status_code=status.HTTP_201_CREATED,
    summary="Issue a pairing code",
    response_model=PairingTicketResponse,
)
async def issue_pairing_token(
    project_id: ProjectId,
    payload: PairingTokenRequest,
    access: Annotated[AccessContext, Depends(require_permission(Permission.DEVICE_MANAGE))],
    tokens: PairingTokenRepoDep,
    devices: DeviceRepoDep,
    projects: ProjectRepoDep,
    settings: SettingsDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
    clock: ClockDep,
) -> PairingTicketResponse:
    """Create a single-use code for a camera to claim.

    The code is displayed as text **and** as a QR encoding the server URL, so a
    technician can scan rather than transcribe eight characters into a captive
    portal. It expires in 15 minutes and works once.

    Only the code's hash is stored, so this response is the only time the
    plaintext exists on the server.
    """
    _ = access
    ticket = await IssuePairingToken(
        tokens,
        devices,
        projects,
        ttl_minutes=settings.pairing_token_ttl_minutes,
        clock=clock,
    ).execute(
        project_id,
        face=payload.face,
        created_by=user.id,
        replace_existing=payload.replace_existing,
    )

    await audit.record(
        AuditAction.PAIRING_TOKEN_ISSUED,
        entity_type="project",
        entity_id=project_id,
        actor_user_id=user.id,
        ip_address=client_ip,
        # The code itself is never audited - an audit log is widely readable.
        metadata={"face": payload.face.value, "device_name": ticket.device_name},
    )

    now = clock.now()
    return PairingTicketResponse(
        display_code=ticket.display_code,
        formatted_code=ticket.formatted_code,
        expires_at=ticket.expires_at.isoformat(),
        expires_in_seconds=int((ticket.expires_at - now).total_seconds()),
        project_code=ticket.project_code,
        face=ticket.face,
        device_name=ticket.device_name,
        qr_png_base64=build_provisioning_qr(
            ticket.provisioning_payload, server_url=settings.public_base_url
        ),
        pair_page_url=f"{settings.public_base_url.rstrip('/')}/pair?code={ticket.display_code}",
        pair_page_qr_base64=build_pair_page_qr(
            ticket.display_code, server_url=settings.public_base_url
        ),
    )


@router.patch(
    "/projects/{project_id}/devices/{device_id}",
    summary="Adjust a camera",
    response_model=DeviceSummaryResponse,
)
async def update_device(
    project_id: ProjectId,
    device_id: DeviceId,
    payload: DeviceSettingsRequest,
    access: Annotated[AccessContext, Depends(require_permission(Permission.DEVICE_MANAGE))],
    devices: DeviceRepoDep,
    clock: ClockDep,
) -> DeviceSummaryResponse:
    """Change the capture schedule, aggregation weight, or calibration.

    The device picks schedule changes up on its next heartbeat — it is asleep
    most of the time and cannot be pushed to.
    """
    _ = access
    existing = await devices.get(device_id)
    schedule = None
    if existing is not None and any(
        value is not None
        for value in (
            payload.capture_times,
            payload.timezone,
            payload.jitter_seconds,
            payload.enabled,
        )
    ):
        current = existing.capture_schedule
        schedule = CaptureSchedule(
            times=tuple(payload.capture_times) if payload.capture_times else current.times,
            timezone=payload.timezone or current.timezone,
            jitter_seconds=(
                payload.jitter_seconds
                if payload.jitter_seconds is not None
                else current.jitter_seconds
            ),
            enabled=payload.enabled if payload.enabled is not None else current.enabled,
        )

    updated = await UpdateDeviceSettings(devices).execute(
        project_id,
        device_id,
        weight=payload.weight,
        capture_schedule=schedule,
        homography=payload.homography,
        roi_polygon=payload.roi_polygon,
    )
    return present_device(updated, liveness=updated.liveness_at(clock.now()))


@router.post(
    "/projects/{project_id}/devices/{device_id}/unpair",
    summary="Unpair a camera",
    response_model=MessageResponse,
)
async def unpair_device(
    project_id: ProjectId,
    device_id: DeviceId,
    access: Annotated[AccessContext, Depends(require_permission(Permission.DEVICE_MANAGE))],
    devices: DeviceRepoDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
    clock: ClockDep,
) -> MessageResponse:
    """Revoke a camera's credentials.

    **Its captures are kept.** Swapping failed hardware must not rewrite the
    project's progress history — the photographs happened, whatever took them.
    The camera will see 401 on its next upload and re-enter provisioning.
    """
    _ = access
    await UnpairDevice(devices, clock=clock).execute(project_id, device_id)
    await audit.record(
        AuditAction.DEVICE_UNPAIRED,
        entity_type="device",
        entity_id=device_id,
        actor_user_id=user.id,
        ip_address=client_ip,
    )
    return MessageResponse(message="Camera unpaired. Its existing captures have been kept.")


# ---------------------------------------------------------------------------
# Device-facing endpoint (no user auth - possession of the code is the proof)
# ---------------------------------------------------------------------------


@router.post(
    "/pair/claim",
    summary="Claim a pairing code (called by the camera)",
    response_model=ClaimResponse,
)
@limiter.limit("10/minute")
async def claim_pairing_code(
    request: Request,
    response: Response,
    payload: ClaimRequest,
    tokens: PairingTokenRepoDep,
    devices: DeviceRepoDep,
    projects: ProjectRepoDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> ClaimResponse:
    """Exchange a pairing code for a device identity and secret.

    Called once by the ESP32 during provisioning. Unauthenticated by design —
    possession of a short-lived single-use code *is* the credential — which is
    why it is rate-limited: a code is only ~40 bits, and brute force is the
    obvious attack.

    ``device_secret`` is returned **exactly once**. It is stored encrypted and
    never appears in another response, a log line, or an audit entry.
    """
    claim = await ClaimPairingToken(
        tokens,
        devices,
        projects,
        encryption_key=settings.device_secret_key,
        clock=clock,
    ).execute(
        code=payload.display_code,
        hardware_id=payload.hardware_id,
        firmware_version=payload.firmware_version,
    )

    schedule = claim.device.capture_schedule
    return ClaimResponse(
        device_id=claim.device.id,
        device_secret=claim.device_secret,
        device_name=claim.device.device_name,
        project_code=claim.project_code,
        face=claim.device.face,
        capture_times=list(schedule.times),
        timezone=schedule.timezone,
        server_time=claim.server_time.isoformat(),
    )
