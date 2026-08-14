"""The data crossing the ``ai/`` → ``backend/`` boundary.

Plain frozen dataclasses: no ORM, no Pydantic, no torch tensors. This is
deliberate and it is what keeps the boundary real. The backend's API process
must never import torch (ADR-011), so anything it receives from here has to be
constructible without it — a numpy array or a tensor leaking into one of these
would drag the dependency across by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai.models.base import Classification, DetectionResult, ModelInfo
from ai.preprocessing.quality import QualityReport

__all__ = ["InferenceResult", "ServiceStatus"]


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """Everything one image produced on its way through the worker."""

    #: ``None`` when the quality gate rejected the frame. The classifier is never
    #: run on a rejected image — a model handed a blurry frame does not decline
    #: to answer, it answers confidently and wrongly.
    classification: Classification | None
    quality: QualityReport
    detections: DetectionResult = field(default_factory=DetectionResult)
    preprocessing_ms: int = 0
    total_ms: int = 0
    preprocessing_fingerprint: str = ""

    @property
    def rejected(self) -> bool:
        """Whether the quality gate stopped this image."""
        return self.classification is None

    @property
    def inference_ms(self) -> int:
        """Model time only, excluding preprocessing."""
        classify = self.classification.inference_ms if self.classification else 0
        return classify + self.detections.inference_ms


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """What ``GET /model/status`` reports."""

    classifier: ModelInfo
    detector: ModelInfo | None
    preprocessing_fingerprint: str
    loaded_at: str
    #: Rolling mean over recent images, so a slow model is visible without
    #: anyone having to go and measure it.
    mean_latency_ms: float = 0.0
    images_processed: int = 0

    @property
    def using_stubs(self) -> bool:
        """Whether any model in the path is a placeholder.

        Surfaced on the endpoint so a demo can never be mistaken for a result.
        """
        return self.classifier.is_stub or (self.detector is not None and self.detector.is_stub)
