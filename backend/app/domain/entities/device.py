"""ESP32-CAM device, pairing token, and device-event entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from app.domain.enums import CameraFace, DeviceStatus
from app.domain.value_objects import ProjectCode

__all__ = ["CaptureSchedule", "Device", "DeviceEvent", "PairingToken"]

#: A device unheard-from for longer than this is considered offline.
OFFLINE_AFTER = timedelta(hours=6)


@dataclass(frozen=True, slots=True)
class CaptureSchedule:
    """When a camera wakes to capture.

    Attributes:
        times: Local wall-clock times, ``HH:MM``.
        timezone: IANA zone the times are expressed in.
        jitter_seconds: Randomisation window, so a fleet of devices does not
            all POST at exactly 07:00:00.
    """

    times: tuple[str, ...] = ("07:00", "16:00")
    timezone: str = "Asia/Manila"
    jitter_seconds: int = 120
    enabled: bool = True

    def __post_init__(self) -> None:
        """Validate the schedule is sane and within the allowed capture budget."""
        if not self.times:
            msg = "capture schedule needs at least one time"
            raise ValueError(msg)
        if len(self.times) > 6:
            msg = f"at most 6 captures per day, got {len(self.times)}"
            raise ValueError(msg)
        for entry in self.times:
            hours, _, minutes = entry.partition(":")
            if not (hours.isdigit() and minutes.isdigit()):
                msg = f"invalid capture time {entry!r}, expected HH:MM"
                raise ValueError(msg)
            if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
                msg = f"capture time out of range: {entry!r}"
                raise ValueError(msg)

    @property
    def captures_per_day(self) -> int:
        """How many wake-ups a day this schedule implies."""
        return len(self.times)


@dataclass(frozen=True, slots=True)
class Device:
    """A paired ESP32-CAM node.

    The device name is derived, never typed: ``ESP_<PROJECT_CODE>_<FACE>``.
    Only the *hash* of the shared HMAC secret is retained — the plaintext is
    shown once, at pairing, and never again.
    """

    id: UUID
    project_id: UUID
    device_name: str
    face: CameraFace
    weight: float
    status: DeviceStatus = DeviceStatus.PAIRED
    firmware_version: str | None = None
    hardware_id: str | None = None
    capture_schedule: CaptureSchedule = field(default_factory=CaptureSchedule)
    homography: dict[str, object] | None = None
    roi_polygon: dict[str, object] | None = None
    last_seen_at: datetime | None = None
    last_battery_mv: int | None = None
    last_rssi_dbm: int | None = None
    paired_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @staticmethod
    def build_name(code: ProjectCode, face: CameraFace) -> str:
        """Derive the canonical device name, e.g. ``ESP_NG_00_FD``."""
        return f"ESP_{code.value}_{face.code}"

    @property
    def is_usable(self) -> bool:
        """Whether this device may still authenticate and upload."""
        return self.status is not DeviceStatus.REVOKED and self.revoked_at is None

    @property
    def is_calibrated(self) -> bool:
        """Whether a homography exists for perspective rectification.

        Without one the preprocessing pipeline skips rectification rather than
        failing, so an uncalibrated camera still produces usable predictions.
        """
        return self.homography is not None

    def liveness_at(self, moment: datetime) -> DeviceStatus:
        """Derive online/offline from the last heartbeat.

        Terminal states (``REVOKED``) and the not-yet-seen state are returned
        unchanged.
        """
        if self.status is DeviceStatus.REVOKED:
            return DeviceStatus.REVOKED
        if self.last_seen_at is None:
            return DeviceStatus.PAIRED
        return (
            DeviceStatus.ONLINE
            if moment - self.last_seen_at <= OFFLINE_AFTER
            else DeviceStatus.OFFLINE
        )


@dataclass(frozen=True, slots=True)
class PairingToken:
    """A single-use, short-lived code that binds a camera to a project.

    Only the hash is stored. The human-readable code is displayed once, as text
    and as a QR payload, and expires in 15 minutes.
    """

    id: UUID
    project_id: UUID
    face: CameraFace
    token_hash: str
    expires_at: datetime
    created_by: UUID
    used_at: datetime | None = None
    used_by_device_id: UUID | None = None
    created_at: datetime | None = None

    def is_claimable_at(self, moment: datetime) -> bool:
        """Whether the token may still be exchanged for a device secret."""
        return self.used_at is None and self.expires_at > moment


@dataclass(frozen=True, slots=True)
class DeviceEvent:
    """A telemetry record from a device: boot, heartbeat, upload, error, sleep.

    The series of these is what powers the device health panel and the battery
    curve reported in the thesis.
    """

    id: UUID
    device_id: UUID
    event_type: str
    payload: dict[str, object] = field(default_factory=dict)
    battery_mv: int | None = None
    rssi_dbm: int | None = None
    created_at: datetime | None = None
