"""Device-facing ingest endpoints.

Authenticated by HMAC, never by JWT. Every route here is reached by an ESP32-CAM
that has just woken up, and the responses are shaped for firmware rather than a
browser: short, explicit, and actionable — a camera that gets a 413 should know
to lower its JPEG quality rather than retry the same frame until the battery
dies.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from app.api.deps import (
    ClockDep,
    CurrentDevice,
    DeviceRepoDep,
    ImageRepoDep,
    ProjectRepoDep,
    SettingsDep,
    StorageDep,
    TaskQueueDep,
)
from app.application.use_cases.devices import RecordDeviceEvent
from app.application.use_cases.ingest import (
    CaptureMetadata,
    GetDeviceConfig,
    IngestImage,
)
from app.core.exceptions import ValidationFailedError

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestResponse(BaseModel):
    """Acknowledgement for an accepted capture."""

    image_id: str
    filename: str
    accepted: bool = True
    duplicate: bool = Field(default=False, description="True when this capture was already stored")
    server_time: str = Field(description="Use to correct RTC drift")


class DeviceConfigResponse(BaseModel):
    """The schedule and clock a camera pulls on each heartbeat."""

    device_name: str
    project_code: str
    capture_times: list[str]
    timezone: str
    jitter_seconds: int
    enabled: bool
    server_time: str
    max_upload_bytes: int


class DeviceEventRequest(BaseModel):
    """Telemetry from the camera."""

    event_type: Annotated[str, Field(max_length=32)]
    payload: dict[str, Any] = Field(default_factory=dict)
    battery_mv: Annotated[int | None, Field(default=None, ge=0, le=10_000)]
    rssi_dbm: Annotated[int | None, Field(default=None, ge=-120, le=0)]
    free_heap: Annotated[int | None, Field(default=None, ge=0)]
    queue_depth: Annotated[int | None, Field(default=None, ge=0)]


@router.post(
    "/images",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a capture",
    response_model=IngestResponse,
)
async def ingest_image(
    request: Request,
    device: CurrentDevice,
    images: ImageRepoDep,
    devices: DeviceRepoDep,
    projects: ProjectRepoDep,
    storage: StorageDep,
    tasks: TaskQueueDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> IngestResponse:
    """Accept one image from an authenticated camera.

    Multipart with two parts: ``file`` (the JPEG) and ``meta`` (JSON capture
    metadata). The form is parsed **here** rather than through FastAPI's
    parameter injection because ``get_current_device`` has already read the raw
    body to verify the signature over it — Starlette caches that body, so
    parsing it again is safe and explicit.

    The device supplies no project and no filename. Both come from the
    authenticated ``device_id``, so a compromised camera can only ever write
    into the folder it was paired to.
    """
    form = await request.form()
    upload = form.get("file")
    raw_meta = form.get("meta")

    if upload is None or not hasattr(upload, "read"):
        msg = "Missing the 'file' part of the upload."
        raise ValidationFailedError(msg, code="MISSING_FILE")
    if not isinstance(raw_meta, str):
        msg = "Missing the 'meta' JSON part of the upload."
        raise ValidationFailedError(msg, code="MISSING_META")

    meta = _parse_meta(raw_meta)
    payload = await upload.read()

    result = await IngestImage(
        images,
        devices,
        projects,
        storage,
        tasks,
        max_bytes=settings.max_image_upload_bytes,
        min_width=settings.min_image_width,
        min_height=settings.min_image_height,
        max_future_hours=settings.max_capture_future_hours,
        clock=clock,
    ).execute(device, payload=payload, meta=meta)

    return IngestResponse(
        image_id=str(result.image.id),
        filename=result.image.filename,
        duplicate=result.duplicate,
        server_time=clock.now().isoformat(),
    )


@router.get("/config", summary="Pull schedule and server time", response_model=DeviceConfigResponse)
async def device_config(
    device: CurrentDevice,
    projects: ProjectRepoDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> DeviceConfigResponse:
    """Return the camera's current schedule and the server clock.

    ``server_time`` is the field that matters: the firmware compares it against
    its DS3231 and corrects drift beyond 30 seconds. Without it a slowly
    drifting clock would eventually push every request outside the HMAC skew
    window and lock the camera out of its own project.
    """
    config = await GetDeviceConfig(
        projects, max_upload_bytes=settings.max_image_upload_bytes, clock=clock
    ).execute(device)
    return DeviceConfigResponse(
        device_name=config.device_name,
        project_code=config.project_code,
        capture_times=list(config.capture_times),
        timezone=config.timezone,
        jitter_seconds=config.jitter_seconds,
        enabled=config.enabled,
        server_time=config.server_time.isoformat(),
        max_upload_bytes=config.max_upload_bytes,
    )


@router.post("/events", summary="Report telemetry", status_code=status.HTTP_202_ACCEPTED)
async def record_event(
    payload: DeviceEventRequest,
    device: CurrentDevice,
    devices: DeviceRepoDep,
    clock: ClockDep,
) -> dict[str, str]:
    """Record a boot, heartbeat, error, or sleep event.

    This is what populates the device health panel and the battery curve
    reported in the thesis, so it is accepted even when nothing was captured —
    a camera that wakes, finds no Wi-Fi, and sleeps again is exactly the event
    worth knowing about.
    """
    await RecordDeviceEvent(devices, clock=clock).execute(
        device.id,
        event_type=payload.event_type,
        payload={
            **payload.payload,
            "free_heap": payload.free_heap,
            "queue_depth": payload.queue_depth,
        },
        battery_mv=payload.battery_mv,
        rssi_dbm=payload.rssi_dbm,
    )
    return {"accepted": "true", "server_time": clock.now().isoformat()}


def _parse_meta(raw: str) -> CaptureMetadata:
    """Parse the ``meta`` part into validated capture metadata.

    Raises:
        ValidationFailedError: If the JSON is malformed or required fields are
            missing. Firmware bugs are caught here with a specific message
            rather than surfacing as a 500.
    """
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = "The 'meta' part is not valid JSON."
        raise ValidationFailedError(msg, code="BAD_META_JSON") from exc

    if not isinstance(document, dict):
        msg = "The 'meta' part must be a JSON object."
        raise ValidationFailedError(msg, code="BAD_META_JSON")

    captured_raw = document.get("captured_at")
    sha256 = document.get("sha256")
    if not captured_raw or not sha256:
        msg = "The 'meta' part needs both 'captured_at' and 'sha256'."
        raise ValidationFailedError(msg, code="INCOMPLETE_META")

    try:
        captured_at = datetime.fromisoformat(str(captured_raw).replace("Z", "+00:00"))
    except ValueError as exc:
        msg = "'captured_at' must be an ISO-8601 timestamp."
        raise ValidationFailedError(msg, code="BAD_CAPTURED_AT") from exc

    # A naive timestamp is assumed UTC: the firmware stamps from GPS or the
    # DS3231, both of which are UTC, and a naive value here would otherwise be
    # interpreted in the server's zone.
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)

    def _number(key: str) -> float | None:
        value = document.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    def _integer(key: str) -> int | None:
        value = document.get(key)
        return int(value) if isinstance(value, (int, float)) else None

    return CaptureMetadata(
        captured_at=captured_at,
        sha256=str(sha256).lower(),
        latitude=_number("latitude"),
        longitude=_number("longitude"),
        gps_accuracy_m=_number("gps_accuracy_m"),
        altitude_m=_number("altitude_m"),
        satellites=_integer("satellites"),
        battery_mv=_integer("battery_mv"),
        rssi_dbm=_integer("rssi_dbm"),
        seq_hint=_integer("seq_hint"),
    )
