"""Deterministic stand-in models, for building the system before the dataset.

Modules 09 through 14 all sit downstream of a trained checkpoint, and the
dataset is the project's long pole. Rather than let that block six modules, the
inference path is built against these — they satisfy the same protocols a real
ResNet18 and YOLOv8 will, so swapping them out later is a configuration change
(``GV_USE_STUB_MODELS=false`` plus a weights file), not a rewrite.

**What a stub proves and what it does not.** It proves the plumbing: that an
upload becomes a prediction, that the prediction becomes a progress number, that
the number reaches the dashboard, that the approval flow fires at the ceiling.
It proves nothing whatsoever about accuracy. Every evaluation figure in the
thesis needs real weights — see [[Module-07-Classifier-Training]]. The stub is
loudly labelled everywhere it surfaces (``is_stub`` on
:class:`~ai.models.base.ModelInfo`, ``"stub"`` in the version string, and a
warning at load) precisely so nobody mistakes a demo for a result.

**Deterministic and stateless.** The predicted class is derived from a hash of
the image bytes, so the same photograph always yields the same answer — across
processes, across restarts, and on reprocessing. A random stub would make the
idempotency and replay tests meaningless, which are the properties Module 09
most needs to demonstrate.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field

import numpy as np

from ai.models.base import (
    BoundingBox,
    Classification,
    DetectedObject,
    DetectionResult,
    Image,
    ModelInfo,
)
from ai.progress.mapping import class_names

__all__ = ["STUB_DETECTION_CLASSES", "StubClassifier", "StubDetector"]

logger = logging.getLogger(__name__)

#: What the real YOLOv8 will be trained to find (``Module-08-YOLO-Detection``).
STUB_DETECTION_CLASSES = (
    "column",
    "wall",
    "beam",
    "roof_truss",
    "scaffolding",
    "excavator",
    "worker",
)


def _digest(image: Image, salt: bytes = b"") -> int:
    """Stable integer derived from the image contents.

    BLAKE2b over the raw buffer, deliberately not Python's ``hash()``: string and
    bytes hashing is randomised per process (``PYTHONHASHSEED``), so a
    ``hash()``-based stub would give one answer in the API process and a
    different one in the Celery worker — reproducing, in the stub, exactly the
    class of bug ADR-022 was written about.
    """
    return int.from_bytes(
        hashlib.blake2b(np.ascontiguousarray(image).tobytes() + salt, digest_size=8).digest(),
        "big",
    )


@dataclass(slots=True)
class StubClassifier:
    """A deterministic stand-in for the ResNet18 stage classifier.

    Args:
        fixed_class_index: Always predict this class. Used to drive a specific
            scenario — most usefully pushing a project to the machine ceiling to
            exercise the approval flow, which would otherwise need a very
            particular set of images.
        preprocessing_fingerprint: Recorded on :attr:`info` so the skew check has
            something to compare against even in stub mode. There is nothing to
            be skewed *from* here, but leaving it unset would mean the check is
            never exercised until real weights arrive.
    """

    fixed_class_index: int | None = None
    preprocessing_fingerprint: str | None = None
    _classes: tuple[str, ...] = field(default_factory=lambda: class_names(), repr=False)

    def __post_init__(self) -> None:
        """Warn loudly. A stub reaching production would be a silent disaster."""
        logger.warning(
            "StubClassifier active - predictions are DETERMINISTIC PLACEHOLDERS, "
            "not model output. Set GV_USE_STUB_MODELS=false with trained weights "
            "before reporting any accuracy figure."
        )

    @property
    def info(self) -> ModelInfo:
        """Provenance, flagged as a stub in three separate places."""
        return ModelInfo(
            name="stub-classifier",
            architecture="stub",
            version="stub-v1",
            class_names=self._classes,
            input_size=224,
            device="cpu",
            is_stub=True,
            preprocessing_fingerprint=self.preprocessing_fingerprint,
        )

    def predict(self, image: Image) -> Classification:
        """Return a deterministic pseudo-classification for *image*."""
        started = time.perf_counter()

        if self.fixed_class_index is not None:
            index = self.fixed_class_index % len(self._classes)
        else:
            index = _digest(image) % len(self._classes)

        probabilities = self._distribution(index, image)
        return Classification(
            class_index=index,
            class_name=self._classes[index],
            confidence=probabilities[self._classes[index]],
            probabilities=probabilities,
            inference_ms=int((time.perf_counter() - started) * 1000),
        )

    def warm_up(self) -> None:
        """No-op: there is nothing to allocate."""

    def _distribution(self, index: int, image: Image) -> dict[str, float]:
        """Build a plausible softmax-shaped distribution peaked at *index*.

        Mass is concentrated on the winner and spread over its **ordinal
        neighbours**, because that is how the real model will fail: the classes
        are a monotone construction sequence, and Footings/Foundation confusion
        is far likelier than Footings/Roof. A stub that spread mass uniformly
        would make the low-confidence path untestable in any realistic shape.
        """
        # Deterministic per image, so confidence is stable across reprocessing
        # but varies between images - enough to exercise the eligibility gate.
        spread = _digest(image, b"conf") % 30  # 0-29
        peak = 0.62 + spread / 100.0  # 0.62 - 0.91

        weights = []
        for position in range(len(self._classes)):
            distance = abs(position - index)
            weights.append(1.0 if distance == 0 else 1.0 / (distance + 1) ** 3)

        remainder = 1.0 - peak
        neighbour_total = sum(weights) - 1.0
        distribution = {}
        for position, name in enumerate(self._classes):
            if position == index:
                distribution[name] = round(peak, 4)
            else:
                share = weights[position] / neighbour_total if neighbour_total else 0.0
                distribution[name] = round(remainder * share, 4)
        return distribution


@dataclass(slots=True)
class StubDetector:
    """A deterministic stand-in for the YOLOv8 detector.

    Returns a small, stable set of plausible boxes so the detection storage path,
    the count aggregation, and the dashboard overlay are all exercised. The boxes
    correspond to nothing in the image, which is the point: this is plumbing, not
    perception.
    """

    max_objects: int = 6
    _classes: tuple[str, ...] = field(default=STUB_DETECTION_CLASSES, repr=False)

    def __post_init__(self) -> None:
        """Warn, for the same reason the classifier does."""
        logger.warning("StubDetector active - detections are placeholders, not model output.")

    @property
    def info(self) -> ModelInfo:
        """Provenance, flagged as a stub."""
        return ModelInfo(
            name="stub-detector",
            architecture="stub",
            version="stub-v1",
            class_names=self._classes,
            input_size=640,
            device="cpu",
            is_stub=True,
        )

    def detect(self, image: Image) -> DetectionResult:
        """Return a deterministic set of boxes for *image*."""
        started = time.perf_counter()
        seed = _digest(image, b"detect")
        count = seed % (self.max_objects + 1)

        objects: list[DetectedObject] = []
        for position in range(count):
            token = _digest(image, f"box{position}".encode())
            name = self._classes[token % len(self._classes)]

            # Kept inside [0, 1] with positive area by construction: the backend's
            # BoundingBox validates this and would reject an out-of-range box, so
            # a stub that produced one would fail on insert rather than in a way
            # anyone could diagnose.
            x = (token >> 8 & 0xFF) / 255.0 * 0.7
            y = (token >> 16 & 0xFF) / 255.0 * 0.7
            width = 0.08 + (token >> 24 & 0xFF) / 255.0 * 0.2
            height = 0.08 + (token >> 32 & 0xFF) / 255.0 * 0.2

            objects.append(
                DetectedObject(
                    class_name=name,
                    confidence=round(0.55 + (token >> 40 & 0xFF) / 255.0 * 0.4, 4),
                    bbox=BoundingBox(
                        x=round(x, 4),
                        y=round(y, 4),
                        width=round(min(width, 1.0 - x), 4),
                        height=round(min(height, 1.0 - y), 4),
                    ),
                )
            )

        return DetectionResult(
            objects=tuple(objects),
            inference_ms=int((time.perf_counter() - started) * 1000),
        )

    def warm_up(self) -> None:
        """No-op: there is nothing to allocate."""
