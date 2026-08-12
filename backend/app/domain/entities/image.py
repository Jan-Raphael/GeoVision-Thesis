"""Captured image, prediction, detection, and progress-snapshot entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from app.domain.enums import ImageSource, ImageStatus, MacroStage
from app.domain.value_objects import Confidence, GeoPoint, ProgressPct, ProjectCode

__all__ = [
    "BoundingBox",
    "Detection",
    "DetectionSummary",
    "Image",
    "Prediction",
    "ProgressSnapshot",
]


@dataclass(frozen=True, slots=True)
class Image:
    """One captured frame from a site camera, or a manual upload.

    Attributes:
        captured_at: **Device** time, from GPS or the DS3231 RTC. This is what
            aggregation windows key on, so a backlog upload lands in the window
            it was taken in rather than the one it arrived in.
        uploaded_at: Server time of receipt.
        sha256: Content hash, used for ingest idempotency — a re-delivered
            upload after a lost ACK must not create a second row.
    """

    id: UUID
    project_id: UUID
    filename: str
    storage_key: str
    captured_at: datetime
    sha256: str
    source: ImageSource = ImageSource.DEVICE
    status: ImageStatus = ImageStatus.PENDING
    device_id: UUID | None = None
    preprocessed_key: str | None = None
    thumb_key: str | None = None
    uploaded_at: datetime | None = None
    seq_number: int | None = None
    location: GeoPoint | None = None
    gps_accuracy_m: float | None = None
    altitude_m: float | None = None
    satellites: int | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    exif: dict[str, object] = field(default_factory=dict)
    quality_flags: dict[str, object] = field(default_factory=dict)
    rejected_reason: str | None = None
    created_at: datetime | None = None

    @staticmethod
    def build_filename(code: ProjectCode, captured_at: datetime, seq: int) -> str:
        """Assemble the canonical runtime filename.

        Format ``<CODE>_<YYYYMMDDTHHMMSSZ>_<NNN>.jpg`` — for example
        ``NG_00_20260813T070000Z_001.jpg``.

        The predicted stage is deliberately **absent**: at capture time the
        stage is unknown, and a predicted label in a filename would eventually
        be mistaken for ground truth (ADR-002).

        Args:
            code: The owning project's code.
            captured_at: Capture time. Converted to **UTC**; a naive datetime is
                assumed to already be UTC.
            seq: 1-based sequence within the project for that UTC day.

        Returns:
            The filename the server assigns to this capture.

        Raises:
            ValueError: If *seq* is outside the three-digit range.
        """
        if not 1 <= seq <= 999:
            msg = f"sequence number must be between 1 and 999, got {seq}"
            raise ValueError(msg)
        # Explicitly UTC, never `astimezone(tz=None)`: that converts to the
        # *server's local* zone while the name still claims "Z", which would
        # file captures into the wrong aggregation window on any non-UTC host.
        moment = captured_at if captured_at.tzinfo else captured_at.replace(tzinfo=UTC)
        stamp = moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        return f"{code.value}_{stamp}_{seq:03d}.jpg"

    @property
    def is_geotagged(self) -> bool:
        """Whether a usable GPS fix accompanied this capture."""
        return self.location is not None and not self.location.is_null_island

    @property
    def is_processed(self) -> bool:
        """Whether the pipeline has finished with this image, one way or another."""
        return self.status in {
            ImageStatus.INFERRED,
            ImageStatus.REJECTED,
            ImageStatus.FAILED,
        }


@dataclass(frozen=True, slots=True)
class Prediction:
    """The classifier's verdict on one image.

    Attributes:
        fine_class_index: Index into the frozen 10-class list. Frozen because
            it is the output order of the trained checkpoint — reordering it
            silently relabels history.
        raw_progress_pct: Nominal progress for the predicted class, before any
            multi-camera or temporal smoothing.
        is_eligible: Whether this prediction may influence project progress.
            False when confidence is below the gate.
    """

    id: UUID
    image_id: UUID
    model_id: UUID
    fine_class_index: int
    fine_class: str
    confidence: Confidence
    macro_stage: MacroStage
    raw_progress_pct: ProgressPct
    class_probabilities: dict[str, float] = field(default_factory=dict)
    inference_ms: int | None = None
    created_at: datetime | None = None

    @property
    def is_eligible(self) -> bool:
        """Whether this prediction clears the confidence gate."""
        return self.confidence.is_eligible

    @property
    def low_confidence(self) -> bool:
        """Whether to badge this prediction as uncertain in the UI."""
        return not self.confidence.is_eligible


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """A normalised detection box.

    Coordinates are fractions of image width/height, so a box drawn on a
    thumbnail lines up with the same box on the full-resolution original.
    """

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        """Validate that the box is normalised and has positive area."""
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("width", self.width),
            ("height", self.height),
        ):
            if not 0.0 <= value <= 1.0:
                msg = f"bounding box {name} must be normalised to [0, 1], got {value}"
                raise ValueError(msg)
        if self.width <= 0 or self.height <= 0:
            msg = "bounding box must have positive width and height"
            raise ValueError(msg)

    @property
    def area(self) -> float:
        """Fraction of the frame this box covers."""
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class Detection:
    """One object found by the detector."""

    id: UUID
    image_id: UUID
    model_id: UUID
    class_name: str
    confidence: Confidence
    bbox: BoundingBox
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DetectionSummary:
    """Aggregate object counts for one image.

    Stored alongside the individual boxes because the counts are what the
    corroboration rules and the reports actually read.
    """

    id: UUID
    image_id: UUID
    counts: dict[str, int] = field(default_factory=dict)
    total_objects: int = 0
    inference_ms: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """Aggregated progress for one project over one time window.

    **This table is the timeline graph.** Values are never recomputed on the
    fly: the chart reads stored snapshots, and ``algorithm_version`` records
    which version of the aggregation rules produced each row, so history stays
    reproducible after the algorithm changes.
    """

    id: UUID
    project_id: UUID
    window_start: datetime
    window_end: datetime
    raw_pct: ProgressPct
    ema_pct: ProgressPct
    displayed_pct: ProgressPct
    macro_stage: MacroStage
    foundation_pct: float = 0.0
    framing_pct: float = 0.0
    roofing_pct: float = 0.0
    finishing_pct: float = 0.0
    approval_pct: float = 0.0
    eligible_image_count: int = 0
    contributing_image_ids: tuple[UUID, ...] = ()
    device_weights: dict[str, float] = field(default_factory=dict)
    algorithm_version: str = "progress-v1"
    created_at: datetime | None = None

    @property
    def devices_reporting(self) -> int:
        """How many cameras contributed to this window."""
        return len(self.device_weights)
