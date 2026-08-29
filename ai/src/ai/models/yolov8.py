"""YOLOv8 detector wrapper.

The only file in this codebase allowed to import `ultralytics` (`Module-08-YOLO-Detection.md`'s
explicit rule). Everything downstream depends on `ai.models.base.ObjectDetector`, so swapping
the backend later never touches another file.

`ultralytics` is an optional dependency (`ai/pyproject.toml`'s `[detect]` extra) — the base
install stays lean for anything that never needs detection, matching how the classifier's
`torch`/`torchvision` are required but `ultralytics` is not.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import torch

from ai.models.base import BoundingBox, DetectedObject, DetectionResult, Image, ModelInfo

__all__ = ["YOLOv8Detector"]


@dataclass(slots=True)
class YOLOv8Detector:
    """A trained YOLOv8 checkpoint, satisfying `ai.models.base.ObjectDetector`.

    Args:
        weights_path: A `.pt` file written by `ai/training/train_detector.py` (or any
            ultralytics-compatible checkpoint, for experimentation).
        device: `"cuda"`, `"cpu"`, or `"auto"`.
        conf_threshold: Confidence floor for a detection to be kept (recipe default 0.35).
        iou_threshold: Non-max-suppression IoU threshold (recipe default 0.45).
        max_detections: Caps stored detections per image (Module 08: "a crowded frame
            shouldn't bloat the DB").
    """

    weights_path: str
    device: str = "auto"
    conf_threshold: float = 0.35
    iou_threshold: float = 0.45
    max_detections: int = 50
    _model: Any = field(init=False, repr=False)
    _classes: tuple[str, ...] = field(init=False, repr=False)
    _resolved_device: str = field(init=False)

    def __post_init__(self) -> None:
        """Resolve the device and load the checkpoint."""
        from ultralytics import YOLO

        self._resolved_device = (
            "cuda" if (self.device == "auto" and torch.cuda.is_available()) else self.device
        )
        if self._resolved_device == "auto":
            self._resolved_device = "cpu"

        self._model = YOLO(self.weights_path)
        self._classes = tuple(self._model.names[i] for i in sorted(self._model.names))

    @property
    def info(self) -> ModelInfo:
        """Provenance for `GET /model/status`."""
        return ModelInfo(
            name="yolov8-detector",
            architecture="yolov8",
            version=self.weights_path,
            class_names=self._classes,
            input_size=640,
            device=self._resolved_device,
            is_stub=False,
            weights_path=self.weights_path,
        )

    def detect(self, image: Image) -> DetectionResult:
        """Find objects in one preprocessed frame."""
        started = time.perf_counter()
        height, width = image.shape[:2]

        results = self._model.predict(
            image,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            device=self._resolved_device,
            verbose=False,
        )[0]

        objects: list[DetectedObject] = []
        for box in results.boxes[: self.max_detections]:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            objects.append(
                DetectedObject(
                    class_name=self._classes[int(box.cls[0])],
                    confidence=float(box.conf[0]),
                    # Normalised (Module 08: "so boxes render on any thumbnail size") —
                    # ultralytics returns absolute pixel coordinates on the input frame.
                    bbox=BoundingBox(
                        x=max(0.0, x1 / width),
                        y=max(0.0, y1 / height),
                        width=min(1.0, (x2 - x1) / width),
                        height=min(1.0, (y2 - y1) / height),
                    ),
                )
            )

        return DetectionResult(
            objects=tuple(objects), inference_ms=int((time.perf_counter() - started) * 1000)
        )

    def warm_up(self) -> None:
        """One throwaway inference, so the first real upload after a deploy isn't the slow one."""
        self.detect(np.zeros((640, 640, 3), dtype=np.uint8))
