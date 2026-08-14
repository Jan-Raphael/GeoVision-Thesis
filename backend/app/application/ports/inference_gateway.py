"""Outbound port for asking a model a question and waiting for the answer.

``TaskQueue`` covers the system's normal direction of travel: ingest hands an
image off and forgets about it, and some seconds later a number has moved. Two
endpoints in this module's contract need the opposite — a *reply*:

``POST /predict``
    The stateless demo path. Somebody uploads a photograph during the defense
    and expects to see a stage and a confidence, now, in the response body.
``GET /model/status``
    Reports the device a model is loaded on, when it was loaded, and its rolling
    latency. All three are properties of the **worker process**, and none of them
    exist anywhere the API can read.

The API cannot answer either question itself, because answering means loading
torch, and the API process is forbidden from importing torch (ADR-011) — a rule
enforced by the ``no-torch-in-api`` import contract rather than trusted to
memory. So the API asks the worker over the broker and waits, bounded by a
timeout. That round trip is the whole reason this port exists, and it is
declared here, in the application layer, so the use cases depend on an interface
instead of on Celery.

Everything crossing this boundary is a frozen dataclass of primitives. The
values *originate* in ``ai.inference.schemas``, but importing those here would
drag ``ai`` — and therefore torch — back into the API through the front door
the port was built to close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

__all__ = [
    "AdHocBox",
    "AdHocDetection",
    "AdHocPrediction",
    "AdHocQuality",
    "InferenceGateway",
    "WorkerModelInfo",
    "WorkerStatus",
]


@dataclass(frozen=True, slots=True)
class AdHocQuality:
    """The quality gate's verdict on an ad-hoc frame.

    The scores are reported even when the frame passes, because "accepted, blur
    score 41 against a threshold of 40" and "accepted, blur score 300" are very
    different situations and only the number distinguishes them.
    """

    passed: bool
    flags: tuple[str, ...] = ()
    blur_score: float = 0.0
    brightness: float = 0.0
    occlusion_ratio: float = 0.0


@dataclass(frozen=True, slots=True)
class AdHocBox:
    """A detection box, normalised to fractions of width and height."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class AdHocDetection:
    """One object the detector found in an ad-hoc prediction."""

    class_name: str
    confidence: float
    bbox: AdHocBox


@dataclass(frozen=True, slots=True)
class AdHocPrediction:
    """What one image produced on the stateless ``POST /predict`` path.

    Deliberately parallel to the persisted :class:`~app.domain.entities.Prediction`
    without being it: nothing here has an id, because nothing here was stored.
    The demo endpoint runs the identical pipeline and then throws the result
    away, so a defense demonstration cannot quietly pollute a real project's
    progress history.

    Attributes:
        rejected: The quality gate stopped the frame, so no classification was
            attempted. A model handed a blurry image does not decline to
            answer — it answers confidently and wrongly — so the gate runs
            first and the caller is told plainly that it fired.
        model_is_stub: Whether a placeholder produced this. Surfaced on every
            response, never inferred by the caller, so a demo can never be
            mistaken for a trained result.
    """

    rejected: bool
    quality: AdHocQuality
    stage: str | None = None
    class_index: int | None = None
    confidence: float | None = None
    macro_stage: str | None = None
    progress_pct: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    detections: tuple[AdHocDetection, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)
    rejection_reason: str | None = None
    preprocessing_ms: int = 0
    inference_ms: int = 0
    total_ms: int = 0
    model_name: str = ""
    model_version: str = ""
    model_is_stub: bool = True
    preprocessing_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class WorkerModelInfo:
    """Provenance for one model loaded in a worker process."""

    name: str
    architecture: str
    version: str
    class_names: tuple[str, ...]
    input_size: int
    device: str = "cpu"
    is_stub: bool = False
    preprocessing_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerStatus:
    """A live snapshot of what a worker has loaded, for ``GET /model/status``."""

    classifier: WorkerModelInfo
    detector: WorkerModelInfo | None
    preprocessing_fingerprint: str
    loaded_at: str
    mean_latency_ms: float = 0.0
    images_processed: int = 0

    @property
    def using_stubs(self) -> bool:
        """Whether any model in the path is a placeholder."""
        return self.classifier.is_stub or (self.detector is not None and self.detector.is_stub)


class InferenceGateway(Protocol):
    """A way to reach the worker and get an answer back."""

    async def predict(
        self, image_bytes: bytes, *, timeout_s: float | None = None
    ) -> AdHocPrediction:
        """Run one image through the full pipeline and return the result.

        Persists nothing.

        Args:
            image_bytes: The uploaded image, as received.
            timeout_s: How long to wait. ``None`` uses the configured default.

        Returns:
            The prediction, or a result with ``rejected=True`` if the quality
            gate stopped the frame — which is an answer, not a failure.

        Raises:
            ServiceUnavailableError: If no worker answered in time. This is not
                degraded to a partial result on purpose: an ad-hoc prediction
                with no prediction in it would be a lie with a 200 on it.
        """
        ...

    async def status(self, *, timeout_s: float | None = None) -> WorkerStatus | None:
        """Ask a worker what it currently has loaded.

        Returns:
            The snapshot, or ``None`` when no worker answered. ``None`` is a
            legitimate outcome rather than an error: ``/model/status`` still has
            the registry in PostgreSQL to report, and an endpoint whose purpose
            is *observing health* must not itself fail when things are unhealthy.
        """
        ...

    async def queue_depth(self) -> dict[str, int]:
        """Pending task counts per queue.

        Returns an empty mapping when the broker cannot be reached — the same
        reasoning as :meth:`status`.
        """
        ...
