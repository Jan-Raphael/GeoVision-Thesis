"""Request and response models for predictions, progress, and the model registry.

Separate from ``schemas/projects.py`` so the folder payload and the AI surface
can evolve without dragging each other along — and because Module 12's image
lightbox consumes these shapes directly while never touching a project schema.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ImageStatus, MacroStage, ModelKind

__all__ = [
    "AdHocPredictionResponse",
    "BoundingBoxResponse",
    "DetectionResponse",
    "HistoryEntryResponse",
    "ImageDetailResponse",
    "LiveModelResponse",
    "ModelListResponse",
    "ModelStatusResponse",
    "PredictionResponse",
    "ProgressResponse",
    "QualityResponse",
    "RecomputeAcceptedResponse",
    "RegisteredModelResponse",
    "SnapshotPointResponse",
    "StageBarsResponse",
    "TimelineResponse",
]


# ---------------------------------------------------------------------------
# Shared fragments
# ---------------------------------------------------------------------------


class BoundingBoxResponse(BaseModel):
    """A detection box, normalised to fractions of width and height.

    Normalised rather than in pixels so the same numbers position the box
    correctly on a 224-pixel thumbnail and on the full-resolution original.
    """

    model_config = ConfigDict(from_attributes=True)

    x: float
    y: float
    width: float
    height: float


class DetectionResponse(BaseModel):
    """One object the detector found."""

    model_config = ConfigDict(from_attributes=True)

    class_name: str
    confidence: float
    bbox: BoundingBoxResponse


class QualityResponse(BaseModel):
    """The quality gate's verdict and the scores behind it."""

    passed: bool
    flags: list[str] = Field(default_factory=list)
    blur_score: float = 0.0
    brightness: float = 0.0
    occlusion_ratio: float = 0.0


class PredictionResponse(BaseModel):
    """A stored classifier verdict."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    image_id: UUID
    model_id: UUID
    stage: str = Field(description="Fine-grained class name, e.g. 'walls'")
    class_index: int
    confidence: float
    macro_stage: MacroStage
    raw_progress_pct: float = Field(
        description="Nominal progress for this class alone, before smoothing. "
        "Not the project's progress — see /projects/{id}/progress."
    )
    is_eligible: bool = Field(
        description="Whether this prediction cleared the confidence gate and "
        "was allowed to influence project progress."
    )
    low_confidence: bool
    class_probabilities: dict[str, float] = Field(default_factory=dict)
    inference_ms: int | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


class ImageDetailResponse(BaseModel):
    """One capture with its prediction, detections, and signed URLs."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    device_id: UUID | None = None
    filename: str
    status: ImageStatus
    captured_at: datetime
    uploaded_at: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    gps_accuracy_m: float | None = None
    altitude_m: float | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    sha256: str
    map_url: str | None = None
    rejected_reason: str | None = None
    quality_flags: dict[str, object] = Field(default_factory=dict)
    prediction: PredictionResponse | None = None
    detections: list[DetectionResponse] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    original_url: str | None = None
    preprocessed_url: str | None = None
    thumb_url: str | None = None


class HistoryEntryResponse(BaseModel):
    """One row of ``GET /projects/{id}/history``."""

    model_config = ConfigDict(from_attributes=True)

    image_id: UUID
    filename: str
    captured_at: datetime
    status: ImageStatus
    latitude: float | None = None
    longitude: float | None = None
    thumb_url: str | None = None
    device_id: UUID | None = None
    #: ``None`` for a capture that is pending, rejected, or failed. Those rows
    #: are kept in the history on purpose — omitting them would understate how
    #: much was captured and hide the gate's rejection rate.
    stage: str | None = None
    confidence: float | None = None
    macro_stage: MacroStage | None = None
    raw_progress_pct: float | None = None
    is_eligible: bool | None = None


# ---------------------------------------------------------------------------
# Ad-hoc prediction
# ---------------------------------------------------------------------------


class AdHocPredictionResponse(BaseModel):
    """The stateless ``POST /predict`` result.

    Carries ``persisted: false`` explicitly. This endpoint exists for the live
    defense demo, and a response indistinguishable from a stored one invites
    exactly the confusion the separation was meant to prevent.
    """

    rejected: bool
    persisted: bool = False
    stage: str | None = None
    class_index: int | None = None
    confidence: float | None = None
    macro_stage: str | None = None
    progress: float | None = Field(
        default=None,
        description="Nominal progress for the predicted class. This is a "
        "single-image reading, not a project percentage.",
    )
    probabilities: dict[str, float] = Field(default_factory=dict)
    detections: list[DetectionResponse] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    quality: QualityResponse
    rejection_reason: str | None = None
    preprocessing_ms: int = 0
    inference_ms: int = 0
    total_ms: int = 0
    model_name: str = ""
    model_version: str = ""
    model_is_stub: bool = True
    preprocessing_fingerprint: str = ""


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


class StageBarsResponse(BaseModel):
    """The five stage bars."""

    model_config = ConfigDict(from_attributes=True)

    foundation_pct: float
    framing_pct: float
    roofing_pct: float
    finishing_pct: float
    approval_pct: float


class ProgressResponse(BaseModel):
    """``GET /projects/{id}/progress``."""

    displayed_pct: float
    macro_stage: MacroStage | None = None
    stages: StageBarsResponse
    updated_at: datetime | None = None
    algorithm_version: str
    eligible_image_count: int = 0
    devices_reporting: int = 0
    has_data: bool = Field(
        description="False when no snapshot exists yet. Distinguishes "
        "'nothing measured' from a measured 0 %."
    )


class SnapshotPointResponse(BaseModel):
    """One stored snapshot on the progress chart."""

    model_config = ConfigDict(from_attributes=True)

    window_start: datetime
    window_end: datetime
    displayed_pct: float
    raw_pct: float
    ema_pct: float
    macro_stage: MacroStage
    eligible_image_count: int = 0
    devices_reporting: int = 0
    algorithm_version: str = "progress-v1"


class TimelineResponse(BaseModel):
    """The full snapshot series."""

    points: list[SnapshotPointResponse] = Field(default_factory=list)
    algorithm_version: str = "progress-v1"


class RecomputeAcceptedResponse(BaseModel):
    """Acknowledgement that a recompute was queued."""

    status: str = "queued"
    project_id: UUID
    message: str = "Progress recomputation has been queued."


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RegisteredModelResponse(BaseModel):
    """One row of the model registry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    kind: ModelKind
    architecture: str
    version: str
    class_names: list[str] = Field(default_factory=list)
    input_size: int
    is_active: bool
    is_stub: bool
    metrics: dict[str, float] = Field(default_factory=dict)
    trained_at: datetime | None = None


class LiveModelResponse(BaseModel):
    """What a worker actually has in memory right now."""

    name: str
    architecture: str
    version: str
    class_names: list[str] = Field(default_factory=list)
    input_size: int
    device: str = "cpu"
    is_stub: bool = False
    preprocessing_fingerprint: str | None = None


class ModelStatusResponse(BaseModel):
    """``GET /model/status`` — registry reconciled with a live worker probe."""

    worker_reachable: bool = Field(
        description="False when no inference worker answered. The registry "
        "fields are still populated; the live ones are null."
    )
    using_stubs: bool = Field(
        description="True when a placeholder is answering rather than trained "
        "weights. Surfaced so a demo is never mistaken for a result."
    )
    classifier: RegisteredModelResponse | None = None
    detector: RegisteredModelResponse | None = None
    live_classifier: LiveModelResponse | None = None
    live_detector: LiveModelResponse | None = None
    preprocessing_fingerprint: str | None = None
    preprocessing_matches: bool | None = Field(
        default=None,
        description="Whether the running preprocessing pipeline is the one the "
        "weights were trained through (ADR-025). Null when the loaded model "
        "carries no fingerprint; false means predictions are silently degraded.",
    )
    loaded_at: str | None = None
    mean_latency_ms: float | None = None
    images_processed: int | None = None
    queue_depth: dict[str, int] = Field(default_factory=dict)


class ModelListResponse(BaseModel):
    """Every registered model — the thesis comparison table."""

    models: list[RegisteredModelResponse] = Field(default_factory=list)
