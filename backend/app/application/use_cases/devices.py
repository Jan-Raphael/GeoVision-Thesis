"""Device pairing and management (dashboard spec B.2).

The pairing flow, in three phases:

1. An owner issues a **single-use, 15-minute** code. Only its hash is stored.
2. The camera claims it and receives a per-device secret — returned **exactly
   once**, never retrievable, never logged.
3. Every later request is HMAC-signed with that secret.

The property worth stating plainly: a device is bound to a project at pairing,
and **the device never names its own project afterwards**. Ingest resolves the
project from the authenticated ``device_id``, so a compromised camera can only
ever write into the folder it was paired to.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.core.clock import SYSTEM_CLOCK, Clock
from app.core.device_auth import (
    encrypt_device_secret,
    format_pairing_code,
    generate_device_secret,
    generate_pairing_code,
    hash_pairing_code,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.domain.entities import CaptureSchedule, Device, DeviceEvent, PairingToken
from app.domain.enums import CameraFace, DeviceStatus

if TYPE_CHECKING:
    from datetime import datetime

    from app.domain.repositories import (
        DeviceRepository,
        PairingTokenRepository,
        ProjectRepository,
    )

__all__ = [
    "ClaimPairingToken",
    "IssuePairingToken",
    "PairingClaim",
    "PairingTicket",
    "RecordDeviceEvent",
    "UnpairDevice",
    "UpdateDeviceSettings",
]


@dataclass(frozen=True, slots=True)
class PairingTicket:
    """What the owner's browser shows after requesting a pairing code.

    ``display_code`` is the only time the plaintext exists server-side; the
    stored row holds a hash.
    """

    token_id: UUID
    display_code: str
    formatted_code: str
    expires_at: datetime
    project_code: str
    face: CameraFace
    device_name: str
    provisioning_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class PairingClaim:
    """What the camera receives, once, when it claims a code."""

    device: Device
    device_secret: str
    project_code: str
    server_time: datetime


class IssuePairingToken:
    """Create a single-use code binding one camera face to one project."""

    def __init__(
        self,
        tokens: PairingTokenRepository,
        devices: DeviceRepository,
        projects: ProjectRepository,
        *,
        ttl_minutes: int = 15,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._tokens = tokens
        self._devices = devices
        self._projects = projects
        self._ttl_minutes = ttl_minutes
        self._clock = clock

    async def execute(
        self,
        project_id: UUID,
        *,
        face: CameraFace,
        created_by: UUID,
        replace_existing: bool = False,
    ) -> PairingTicket:
        """Issue a pairing code.

        Args:
            project_id: The project the camera will be bound to.
            face: Which façade this camera watches.
            created_by: The owner or engineer issuing the code.
            replace_existing: Permit issuing a code for a face that is already
                taken, e.g. when swapping failed hardware.

        Returns:
            The ticket to display as text and QR.

        Raises:
            NotFoundError: If the project does not exist.
            ConflictError: If the face already has an active camera and
                *replace_existing* is False.
        """
        project = await self._projects.get(project_id)
        if project is None:
            msg = "Project not found."
            raise NotFoundError(msg)

        if not replace_existing and await self._devices.face_taken(project_id, face):
            raise ConflictError(
                f"This project already has a camera on the {face.value} face. "
                "Unpair it first, or pass replace=true to swap the hardware.",
                code="FACE_ALREADY_PAIRED",
                details={"face": face.value},
            )

        code = generate_pairing_code()
        now = self._clock.now()
        expires_at = now + timedelta(minutes=self._ttl_minutes)

        token = await self._tokens.add(
            PairingToken(
                id=uuid4(),
                project_id=project_id,
                face=face,
                # Only the hash is stored. A database leak yields no usable codes.
                token_hash=hash_pairing_code(code),
                expires_at=expires_at,
                created_by=created_by,
            )
        )

        device_name = Device.build_name(project.code, face)
        return PairingTicket(
            token_id=token.id,
            display_code=code,
            formatted_code=format_pairing_code(code),
            expires_at=expires_at,
            project_code=project.code.value,
            face=face,
            device_name=device_name,
            provisioning_payload={
                "v": 1,
                "code": code,
                "project_code": project.code.value,
                "face": face.code,
                "device_name": device_name,
            },
        )


class ClaimPairingToken:
    """Exchange a pairing code for a device identity and secret."""

    def __init__(
        self,
        tokens: PairingTokenRepository,
        devices: DeviceRepository,
        projects: ProjectRepository,
        *,
        encryption_key: str,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._tokens = tokens
        self._devices = devices
        self._projects = projects
        self._encryption_key = encryption_key
        self._clock = clock

    async def execute(
        self,
        *,
        code: str,
        hardware_id: str | None = None,
        firmware_version: str | None = None,
    ) -> PairingClaim:
        """Claim a code and create the device.

        Args:
            code: The displayed code, in any formatting the user typed.
            hardware_id: The ESP32's MAC, bound at first claim so the identity
                is traceable to physical hardware.
            firmware_version: Reported firmware build.

        Returns:
            The device and its **plaintext secret** — the only time it exists.

        Raises:
            ValidationFailedError: If the code is unknown or expired.
            ConflictError: If the code was already used.
        """
        token = await self._tokens.get_by_hash(hash_pairing_code(code))
        if token is None:
            # Unknown and expired are deliberately different messages: neither
            # discloses anything (the caller already knows what they typed), and
            # "expired" saves a support round trip.
            msg = "That pairing code is not valid."
            raise ValidationFailedError(msg, code="INVALID_PAIRING_CODE")

        now = self._clock.now()
        if token.used_at is not None:
            raise ConflictError(
                "That pairing code has already been used. Generate a new one.",
                code="PAIRING_CODE_USED",
            )
        if token.expires_at <= now:
            msg = "That pairing code has expired. Generate a new one."
            raise ValidationFailedError(msg, code="PAIRING_CODE_EXPIRED")

        project = await self._projects.get(token.project_id)
        if project is None:  # pragma: no cover - cascade would have removed the token
            msg = "Project not found."
            raise NotFoundError(msg)

        secret = generate_device_secret()
        device = await self._devices.add(
            Device(
                id=uuid4(),
                project_id=token.project_id,
                device_name=Device.build_name(project.code, token.face),
                face=token.face,
                # Diagonal placements see two façades, so they carry more weight
                # in the multi-camera average (Progress-Calculation.md).
                weight=token.face.default_weight,
                status=DeviceStatus.PAIRED,
                firmware_version=firmware_version,
                hardware_id=hardware_id,
                capture_schedule=CaptureSchedule(timezone=project.timezone),
                paired_at=now,
            ),
            secret_encrypted=encrypt_device_secret(secret, self._encryption_key),
        )

        await self._tokens.mark_used(token.id, device.id, now)

        return PairingClaim(
            device=device,
            device_secret=secret,
            project_code=project.code.value,
            server_time=now,
        )


class UpdateDeviceSettings:
    """Adjust a paired camera's schedule, weight, or calibration."""

    def __init__(self, devices: DeviceRepository) -> None:
        """Wire the use case to its collaborators."""
        self._devices = devices

    async def execute(
        self,
        project_id: UUID,
        device_id: UUID,
        *,
        weight: float | None = None,
        capture_schedule: CaptureSchedule | None = None,
        homography: dict[str, object] | None = None,
        roi_polygon: dict[str, object] | None = None,
    ) -> Device:
        """Apply a partial update.

        Raises:
            NotFoundError: If the device does not belong to this project.
            ValidationFailedError: If the weight is out of range.
        """
        device = await self._devices.get(device_id)
        if device is None or device.project_id != project_id:
            msg = "Device not found."
            raise NotFoundError(msg)

        if weight is not None and not 0 < weight <= 5:
            msg = "Camera weight must be greater than 0 and at most 5."
            raise ValidationFailedError(msg)

        return await self._devices.update(
            replace(
                device,
                weight=weight if weight is not None else device.weight,
                capture_schedule=capture_schedule or device.capture_schedule,
                homography=homography if homography is not None else device.homography,
                roi_polygon=roi_polygon if roi_polygon is not None else device.roi_polygon,
            )
        )


class UnpairDevice:
    """Revoke a camera's credentials without touching its captures."""

    def __init__(self, devices: DeviceRepository, *, clock: Clock = SYSTEM_CLOCK) -> None:
        """Wire the use case to its collaborators."""
        self._devices = devices
        self._clock = clock

    async def execute(self, project_id: UUID, device_id: UUID) -> Device:
        """Revoke the device and wipe its secret.

        **Historical images and predictions are kept.** Swapping a failed camera
        must not rewrite the project's progress history — the captures happened,
        whatever hardware took them. The device row survives too, so old images
        keep a valid ``device_id`` reference.

        Raises:
            NotFoundError: If the device does not belong to this project.
        """
        device = await self._devices.get(device_id)
        if device is None or device.project_id != project_id:
            msg = "Device not found."
            raise NotFoundError(msg)

        await self._devices.revoke(device_id, self._clock.now())
        refreshed = await self._devices.get(device_id)
        return refreshed if refreshed is not None else device


class RecordDeviceEvent:
    """Append a telemetry record: boot, heartbeat, error, sleep."""

    #: Events a device may report. An open vocabulary would make the health
    #: timeline unqueryable within a month.
    ALLOWED = frozenset({"boot", "heartbeat", "upload", "error", "sleep", "ota", "wake"})

    def __init__(self, devices: DeviceRepository, *, clock: Clock = SYSTEM_CLOCK) -> None:
        """Wire the use case to its collaborators."""
        self._devices = devices
        self._clock = clock

    async def execute(
        self,
        device_id: UUID,
        *,
        event_type: str,
        payload: dict[str, object] | None = None,
        battery_mv: int | None = None,
        rssi_dbm: int | None = None,
    ) -> DeviceEvent:
        """Record the event and refresh the device's liveness fields.

        Raises:
            ValidationFailedError: If *event_type* is not recognised.
        """
        if event_type not in self.ALLOWED:
            msg = f"Unknown event type {event_type!r}."
            raise ValidationFailedError(msg)

        now = self._clock.now()
        await self._devices.record_heartbeat(
            device_id, seen_at=now, battery_mv=battery_mv, rssi_dbm=rssi_dbm
        )
        return DeviceEvent(
            id=uuid4(),
            device_id=device_id,
            event_type=event_type,
            payload=payload or {},
            battery_mv=battery_mv,
            rssi_dbm=rssi_dbm,
            created_at=now,
        )
