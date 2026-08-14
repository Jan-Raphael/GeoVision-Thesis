"""Image ingest — the critical path.

Every capture the system will ever reason about arrives through here, so the
ordering of steps is deliberate rather than incidental:

* **The device never chooses its project or filename.** Both are derived from
  the authenticated ``device_id``. A camera that could name its own destination
  could write into another owner's folder.
* **Idempotency before work.** A device that loses the ACK re-sends identical
  bytes; that must produce one row, not two, and must not re-run inference.
* **Storage before the database row.** A crash between them leaves an orphaned
  blob — wasted bytes, garbage-collectable. The reverse order leaves a row
  pointing at nothing, which breaks the gallery and the report.
* **``captured_at`` comes from the device, ``uploaded_at`` from the server.** A
  camera that was offline for three days uploads a backlog whose captures must
  land in the days they were *taken*, because that is what the progress windows
  key on (``Progress-Calculation.md``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from app.application.ports.events import (
    EventPublisher,
    EventType,
    NullEventPublisher,
    RealtimeEvent,
)
from app.application.ports.task_queue import (
    QUEUE_INFERENCE,
    TASK_PROCESS_IMAGE,
    TaskQueue,
)
from app.core.clock import SYSTEM_CLOCK, Clock
from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationFailedError,
)
from app.domain.entities import Image
from app.domain.enums import DeviceStatus, ImageSource, ImageStatus
from app.domain.services.image_naming import build_image_filename, build_original_key
from app.domain.value_objects import GeoPoint

if TYPE_CHECKING:
    from datetime import datetime

    from app.application.ports.storage import ObjectStorage
    from app.domain.entities import Device, Project
    from app.domain.repositories import (
        DeviceRepository,
        ImageRepository,
        ProjectRepository,
    )

__all__ = ["CaptureMetadata", "DeviceConfig", "GetDeviceConfig", "IngestImage", "IngestResult"]

#: JPEG start-of-image marker. Checked directly rather than trusting the
#: multipart Content-Type, which the client controls.
JPEG_MAGIC = b"\xff\xd8\xff"
MIN_IMAGE_BYTES = 1024


@dataclass(frozen=True, slots=True)
class CaptureMetadata:
    """What the camera reports alongside the image bytes."""

    captured_at: datetime
    sha256: str
    latitude: float | None = None
    longitude: float | None = None
    gps_accuracy_m: float | None = None
    altitude_m: float | None = None
    satellites: int | None = None
    battery_mv: int | None = None
    rssi_dbm: int | None = None
    #: Advisory only. The server assigns the real sequence number.
    seq_hint: int | None = None


@dataclass(frozen=True, slots=True)
class IngestResult:
    """The outcome of an upload."""

    image: Image
    duplicate: bool = False

    @property
    def accepted(self) -> bool:
        """Whether the capture is now stored (including as a duplicate)."""
        return True


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    """What a device pulls on each heartbeat."""

    device_name: str
    project_code: str
    capture_times: tuple[str, ...]
    timezone: str
    jitter_seconds: int
    enabled: bool
    server_time: datetime
    max_upload_bytes: int


class IngestImage:
    """Accept one capture from an authenticated device."""

    def __init__(
        self,
        images: ImageRepository,
        devices: DeviceRepository,
        projects: ProjectRepository,
        storage: ObjectStorage,
        tasks: TaskQueue,
        *,
        events: EventPublisher | None = None,
        max_bytes: int = 8 * 1024 * 1024,
        min_width: int = 320,
        min_height: int = 240,
        max_future_hours: int = 24,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._images = images
        self._devices = devices
        self._projects = projects
        self._storage = storage
        self._tasks = tasks
        # Optional so Module 05's own tests, and any deployment without a
        # broker, construct this exactly as before. Realtime is an
        # optimisation: the capture is stored either way.
        self._events = events or NullEventPublisher()
        self._max_bytes = max_bytes
        self._min_width = min_width
        self._min_height = min_height
        self._max_future_hours = max_future_hours
        self._clock = clock

    async def execute(
        self, device: Device, *, payload: bytes, meta: CaptureMetadata
    ) -> IngestResult:
        """Store a capture and hand it off for inference.

        Args:
            device: The authenticated device. **Its** project is used, never one
                named by the request.
            payload: The raw JPEG bytes.
            meta: The camera's reported metadata.

        Returns:
            The stored image, flagged if this was a duplicate delivery.

        Raises:
            ForbiddenError: If the device has been unpaired.
            PayloadTooLargeError: If the image exceeds the limit.
            ValidationFailedError: If the bytes are not a usable JPEG, the hash
                does not match, or the capture time is implausible.
            NotFoundError: If the device's project has vanished.
        """
        if not device.is_usable:
            # A revoked camera keeps its history but may not add to it.
            msg = "This device has been unpaired."
            raise ForbiddenError(msg, code="DEVICE_REVOKED")

        project = await self._projects.get(device.project_id)
        if project is None:  # pragma: no cover - cascade would have removed the device
            msg = "Project not found."
            raise NotFoundError(msg)

        self._validate_payload(payload, meta)
        captured_at = self._validate_capture_time(meta.captured_at)

        # Idempotency, before any storage write or sequence allocation. A device
        # whose ACK was lost re-sends the same bytes; that must be cheap and
        # must not produce a second row or a second inference job.
        existing = await self._images.get_by_hash(project.id, meta.sha256)
        if existing is not None:
            await self._record_liveness(device, meta)
            return IngestResult(image=existing, duplicate=True)

        # Race-free: the repository takes a transaction-scoped advisory lock on
        # (project, day), so two cameras uploading at 07:00:00 cannot both be
        # handed 001.
        seq = await self._images.next_sequence_number(project.id, captured_at.date())
        filename = build_image_filename(project.code, captured_at, seq)
        key = build_original_key(str(project.id), filename, captured_at, device.face)

        # Storage first. A crash here leaves an orphan blob (harmless); the
        # reverse order leaves a row pointing at bytes that do not exist.
        stored = await self._storage.put(
            key,
            payload,
            content_type="image/jpeg",
            metadata={
                "project_code": project.code.value,
                "device_name": device.device_name,
                "captured_at": captured_at.isoformat(),
            },
        )

        image = await self._images.add(
            Image(
                id=uuid4(),
                project_id=project.id,
                device_id=device.id,
                filename=filename,
                storage_key=stored.key,
                captured_at=captured_at,
                sha256=meta.sha256,
                source=ImageSource.DEVICE,
                status=ImageStatus.PENDING,
                seq_number=seq,
                location=_location(meta),
                gps_accuracy_m=meta.gps_accuracy_m,
                altitude_m=meta.altitude_m,
                satellites=meta.satellites,
                size_bytes=len(payload),
            )
        )

        await self._record_liveness(device, meta)
        await self._touch_project(project, captured_at)

        # Module 09 consumes this. Until its worker exists the row's `pending`
        # status is the durable backlog, so nothing is lost by the queue being
        # a logging stub today.
        await self._tasks.enqueue(
            TASK_PROCESS_IMAGE, {"image_id": str(image.id)}, queue=QUEUE_INFERENCE
        )
        # Announced before the AI has run, so a watching dashboard shows the
        # capture arriving with a "processing" badge rather than nothing for
        # however long inference takes.
        await self._events.publish(
            RealtimeEvent(
                type=EventType.IMAGE_RECEIVED,
                project_id=project.id,
                payload={
                    "image_id": str(image.id),
                    "filename": image.filename,
                    "captured_at": image.captured_at.isoformat(),
                    "device_name": device.device_name,
                    "lat": image.location.latitude if image.location else None,
                    "lon": image.location.longitude if image.location else None,
                },
            )
        )
        return IngestResult(image=image)

    # -- validation ---------------------------------------------------------

    def _validate_payload(self, payload: bytes, meta: CaptureMetadata) -> None:
        """Check size, format, and integrity."""
        size = len(payload)
        if size > self._max_bytes:
            limit_mb = self._max_bytes // (1024 * 1024)
            # 413 with a clear limit: the firmware can act on this by lowering
            # its JPEG quality rather than retrying the same oversized frame
            # until the battery dies.
            msg = f"Image exceeds the {limit_mb} MB limit."
            raise PayloadTooLargeError(msg, details={"max_bytes": self._max_bytes})
        if size < MIN_IMAGE_BYTES:
            msg = "Image is empty or truncated."
            raise ValidationFailedError(msg, code="IMAGE_TRUNCATED")
        if not payload.startswith(JPEG_MAGIC):
            msg = "Uploaded data is not a JPEG image."
            raise ValidationFailedError(msg, code="NOT_A_JPEG")

        # Integrity end to end: the device computed this hash over the file it
        # read from its SD card, so a mismatch means corruption in transit or on
        # the card - either way the bytes are not what was captured.
        actual = hashlib.sha256(payload).hexdigest()
        if actual != meta.sha256.lower():
            msg = "Image hash does not match the uploaded bytes."
            raise ValidationFailedError(msg, code="HASH_MISMATCH")

        self._validate_dimensions(payload)

    def _validate_dimensions(self, payload: bytes) -> None:
        """Reject frames too small to classify.

        A sensor that fails to warm up returns a tiny or malformed frame; those
        are worth catching at the door rather than sending an unusable image
        through preprocessing and inference.
        """
        try:
            import io

            from PIL import Image as PILImage

            with PILImage.open(io.BytesIO(payload)) as decoded:
                width, height = decoded.size
        except Exception as exc:
            msg = "Image could not be decoded."
            raise ValidationFailedError(msg, code="IMAGE_UNDECODABLE") from exc

        if width < self._min_width or height < self._min_height:
            msg = f"Image is {width}x{height}; the minimum is {self._min_width}x{self._min_height}."
            raise ValidationFailedError(msg, code="IMAGE_TOO_SMALL")

    def _validate_capture_time(self, captured_at: datetime) -> datetime:
        """Reject an implausible capture time.

        A capture stamped far in the future means a corrupt RTC. Accepting it
        would put the image in a window that has not happened yet, where it
        would sit ahead of every real capture and skew the timeline. The past is
        deliberately unbounded: a camera can legitimately upload a backlog days
        old, and that is exactly the case the system is built to handle.
        """
        now = self._clock.now()
        if captured_at > now + timedelta(hours=self._max_future_hours):
            msg = "Capture time is too far in the future - check the device clock."
            raise ValidationFailedError(msg, code="CLOCK_IMPLAUSIBLE")
        return captured_at

    # -- side effects -------------------------------------------------------

    async def _record_liveness(self, device: Device, meta: CaptureMetadata) -> None:
        """Refresh last-seen, battery, and signal strength."""
        await self._devices.record_heartbeat(
            device.id,
            seen_at=self._clock.now(),
            battery_mv=meta.battery_mv,
            rssi_dbm=meta.rssi_dbm,
        )

    async def _touch_project(self, project: Project, captured_at: datetime) -> None:
        """Advance the project's last-capture marker.

        Only ever moves forward: a backlog upload of an older capture must not
        make a project look staler than it is, or the inactivity rule would
        misfire (``Project-Status-Rules.md``).
        """
        if project.last_capture_at is None or captured_at > project.last_capture_at:
            await self._projects.update(replace(project, last_capture_at=captured_at))


class GetDeviceConfig:
    """What a camera pulls on each heartbeat."""

    def __init__(
        self,
        projects: ProjectRepository,
        *,
        max_upload_bytes: int = 8 * 1024 * 1024,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._projects = projects
        self._max_upload_bytes = max_upload_bytes
        self._clock = clock

    async def execute(self, device: Device) -> DeviceConfig:
        """Return the device's current schedule and the server clock.

        ``server_time`` is the important field: the firmware compares it against
        its DS3231 and corrects drift beyond 30 seconds. Without that, a slowly
        drifting RTC would eventually push every request outside the HMAC skew
        window and lock the camera out of its own project.

        Raises:
            NotFoundError: If the device's project has vanished.
        """
        project = await self._projects.get(device.project_id)
        if project is None:  # pragma: no cover
            msg = "Project not found."
            raise NotFoundError(msg)

        schedule = device.capture_schedule
        return DeviceConfig(
            device_name=device.device_name,
            project_code=project.code.value,
            capture_times=schedule.times,
            timezone=schedule.timezone,
            jitter_seconds=schedule.jitter_seconds,
            enabled=schedule.enabled and device.status is not DeviceStatus.REVOKED,
            server_time=self._clock.now(),
            max_upload_bytes=self._max_upload_bytes,
        )


def _location(meta: CaptureMetadata) -> GeoPoint | None:
    """Build a coordinate from the reported fix, if there was one."""
    if meta.latitude is None or meta.longitude is None:
        return None
    try:
        point = GeoPoint(latitude=meta.latitude, longitude=meta.longitude)
    except ValueError:
        # A nonsense fix should not reject an otherwise good capture; the image
        # is simply stored without a geotag.
        return None
    # (0, 0) is a GPS module reporting before it has a fix, not a site in the
    # Gulf of Guinea.
    return None if point.is_null_island else point
