"""Shared types for the preprocessing pipeline.

Kept in their own module so every step can name them without importing the
pipeline that composes those steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "CalibrationContext",
    "Image",
    "PreprocessingStep",
    "StepTiming",
]

#: A decoded image: HxWx3, BGR, uint8.
#:
#: **BGR, not RGB.** OpenCV's native order, and converting at every boundary is
#: how channel-swap bugs appear — they do not crash, they just produce a model
#: trained on blue buildings. The conversion happens exactly once, at the tensor
#: boundary in ``ai/models/``, and nowhere else.
Image = NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class CalibrationContext:
    """Per-device geometry, carried alongside the image.

    Both fields are optional and both default to "no calibration", because a
    camera works perfectly well before anybody has calibrated it — rectification
    and occlusion detection simply become no-ops. Requiring calibration up front
    would mean no image could be processed until somebody clicked four corners,
    which is not how a camera gets installed on a roof.
    """

    #: 3x3 homography mapping the captured view onto a canonical rectangle.
    #: Stored on ``devices.homography``.
    homography: NDArray[np.float64] | None = None

    #: Polygon (Nx2, pixel coordinates in the *original* frame) bounding the
    #: façade being monitored. Stored on ``devices.roi_polygon``.
    roi_polygon: NDArray[np.int32] | None = None

    #: Free-form, for provenance in the demo figure and debugging.
    device_name: str | None = None

    @property
    def has_homography(self) -> bool:
        """Whether this device has been geometrically calibrated."""
        return self.homography is not None

    @property
    def has_roi(self) -> bool:
        """Whether a façade region has been marked out."""
        return self.roi_polygon is not None and len(self.roi_polygon) >= 3


@dataclass(slots=True)
class StepTiming:
    """How long one step took, for the latency figure in the thesis."""

    name: str
    milliseconds: float


@runtime_checkable
class PreprocessingStep(Protocol):
    """One ordered transformation.

    A Protocol rather than a base class: steps are independently testable
    functions-with-parameters, and inheritance would buy nothing but a shared
    ``__init__`` nobody needs.

    Every step must be **deterministic** — the same input array yields a
    byte-identical output array. Randomness belongs in augmentation
    (training-only, Module 07), never here, or training and serving diverge in a
    way no test would catch.
    """

    #: Stable identifier, matching the key in ``preprocessing.yaml``.
    name: str

    def apply(self, image: Image, ctx: CalibrationContext) -> Image:
        """Transform *image*, returning a new array."""
        ...

    def describe(self) -> dict[str, Any]:
        """Return this step's parameters, for the config fingerprint.

        Whatever this returns is hashed into
        :attr:`~ai.preprocessing.pipeline.PreprocessingPipeline.fingerprint`, so
        it must include **every** parameter that changes the output. A parameter
        omitted here is a parameter that can silently differ between training
        and serving.
        """
        ...


@dataclass(slots=True)
class PipelineDebug:
    """Optional per-step image capture, for the demo figure.

    Off by default. Keeping every intermediate costs one full-resolution array
    per step, which is fine for one demo image and wasteful across a 1 500-image
    training run.
    """

    enabled: bool = False
    frames: list[tuple[str, Image]] = field(default_factory=list)

    def record(self, name: str, image: Image) -> None:
        """Keep a copy of *image* after the step called *name*."""
        if self.enabled:
            self.frames.append((name, image.copy()))
