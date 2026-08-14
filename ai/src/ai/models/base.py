"""What a classifier and a detector must provide.

Protocols rather than base classes, so a real torch model and a stub satisfy the
same contract without inheriting from anything. That is what lets Modules 09–14
be built, tested, and demonstrated months before a checkpoint exists — and it is
why swapping the stub for real weights later is a configuration change rather
than a rewrite.

Neither protocol mentions torch. The inference service imports torch only when a
real backend is selected, so the whole progress pipeline runs — and is tested —
on a machine with no deep-learning stack installed at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "BoundingBox",
    "Classification",
    "DetectedObject",
    "DetectionResult",
    "ModelInfo",
    "ObjectDetector",
    "StageClassifier",
]

#: A preprocessed image: HxWx3, BGR, uint8 — the output of
#: :class:`~ai.preprocessing.pipeline.PreprocessingPipeline`.
Image = NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Provenance for a loaded model, surfaced by ``GET /model/status``.

    ``preprocessing_fingerprint`` is the load-bearing field. It records which
    preprocessing pipeline the weights were trained through, so Module 09 can
    refuse to serve a model whose pipeline no longer matches the one running
    (ADR-025). Without it, a config edit after training degrades accuracy
    silently and nothing anywhere reports an error.
    """

    name: str
    architecture: str
    version: str
    class_names: tuple[str, ...]
    input_size: int
    device: str = "cpu"
    is_stub: bool = False
    preprocessing_fingerprint: str | None = None
    weights_path: str | None = None


@dataclass(frozen=True, slots=True)
class Classification:
    """One image's predicted construction stage."""

    class_index: int
    class_name: str
    confidence: float
    #: Full softmax distribution, class name → probability. Kept because the
    #: runner-up matters: "Footings 0.51 / Foundation 0.47" is a very different
    #: situation from "Footings 0.51 / Roof 0.47", and only the distribution
    #: shows which one happened.
    probabilities: dict[str, float] = field(default_factory=dict)
    inference_ms: int = 0


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """A detection box, normalised to fractions of width and height.

    Normalised so a box drawn on a 224x224 thumbnail lands in the same place on
    the 1600x1200 original. Pixel coordinates would silently be wrong on every
    surface except the one they were computed for.
    """

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class DetectedObject:
    """One object the detector found."""

    class_name: str
    confidence: float
    bbox: BoundingBox


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Everything the detector found in one image."""

    objects: tuple[DetectedObject, ...] = ()
    inference_ms: int = 0

    @property
    def counts(self) -> dict[str, int]:
        """Objects per class — what the corroboration rules and reports read."""
        tally: dict[str, int] = {}
        for item in self.objects:
            tally[item.class_name] = tally.get(item.class_name, 0) + 1
        return tally

    @property
    def total(self) -> int:
        """How many objects were found."""
        return len(self.objects)


@runtime_checkable
class StageClassifier(Protocol):
    """Predicts the construction stage of one preprocessed frame."""

    @property
    def info(self) -> ModelInfo:
        """Provenance for ``GET /model/status`` and the skew check."""
        ...

    def predict(self, image: Image) -> Classification:
        """Classify one image."""
        ...

    def warm_up(self) -> None:
        """Run one throwaway inference.

        Called once per worker process at startup. The first forward pass
        through a torch model allocates buffers and resolves kernels, costing
        several hundred milliseconds — paying that on a real upload makes the
        first capture after every deploy look pathologically slow.
        """
        ...


@runtime_checkable
class ObjectDetector(Protocol):
    """Finds construction objects, corroborating the classifier."""

    @property
    def info(self) -> ModelInfo:
        """Provenance for ``GET /model/status``."""
        ...

    def detect(self, image: Image) -> DetectionResult:
        """Detect objects in one image."""
        ...

    def warm_up(self) -> None:
        """Run one throwaway inference."""
        ...
