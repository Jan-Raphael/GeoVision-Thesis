"""The backend's one and only door into ``ai/``.

Everything the worker needs from the AI package passes through here, for a
reason that is enforced rather than merely intended: ``ai`` pulls in torch and
OpenCV, and the API process must never load either (ADR-011). Confining the
import to a single infrastructure module makes the boundary greppable — if this
file is the only one importing ``ai``, the rule holds by inspection.

The service is a **module-level singleton**, built once in Celery's
``worker_process_init``. Constructing it per task is the classic performance bug
in this kind of system: loading a checkpoint costs a second or more, which would
dwarf the inference it exists to perform.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai.inference.schemas import InferenceResult, ServiceStatus
    from ai.inference.service import InferenceService

    from app.core.config import Settings
    from app.domain.entities import Device

__all__ = [
    "InferenceAdapter",
    "get_inference_service",
    "reset_inference_service",
]

logger = logging.getLogger(__name__)

_service: InferenceService | None = None


def get_inference_service(settings: Settings) -> InferenceService:
    """Return the process-wide inference service, building it on first use.

    Imports ``ai`` lazily. Even inside infrastructure, a module-level import
    would make ``import app.infrastructure.ai.adapter`` drag torch in — and that
    import can happen by accident from a test collector or an ``__init__``
    re-export long before anyone intends to run inference.
    """
    global _service
    if _service is None:
        from ai.inference.service import build_service

        _service = build_service(
            use_stubs=settings.use_stub_models,
            classifier_weights=_resolve_weights(settings.model_dir, settings.classifier_weights),
            detector_weights=_resolve_weights(settings.model_dir, settings.detector_weights),
            config_path=None,
            device=settings.inference_device,
        )
        _service.warm_up()
    return _service


def _resolve_weights(model_dir: Path, weights: str) -> str | None:
    """Turn a configured weights path into an absolute one, or ``None`` if unset.

    ``GV_CLASSIFIER_WEIGHTS``/``GV_DETECTOR_WEIGHTS`` may name a path relative
    to ``GV_MODEL_DIR`` (the common case — a checkpoint copied into
    ``models/classifier/resnet18/v1/best.pt``) or an absolute one.
    """
    if not weights:
        return None
    path = Path(weights)
    if not path.is_absolute():
        path = model_dir / path
    return str(path)


def reset_inference_service() -> None:
    """Drop the cached service. Tests call this after changing settings."""
    global _service
    _service = None


class InferenceAdapter:
    """Runs one image through the AI package and returns plain data.

    Nothing torch-shaped or numpy-shaped crosses back out — the result carries
    only the frozen dataclasses from :mod:`ai.inference.schemas`, so a caller
    that receives one has not, by that act, acquired a dependency on torch.
    """

    def __init__(self, service: InferenceService) -> None:
        """Wrap a loaded service."""
        self._service = service

    def run(self, image_bytes: bytes, device: Device | None = None) -> InferenceResult:
        """Preprocess, gate, classify, and detect.

        Args:
            image_bytes: The stored original.
            device: The capturing device, for its calibration. ``None`` for a
                manual upload or an uncalibrated camera, in which case
                rectification and occlusion detection are no-ops.

        Returns:
            The classification (``None`` if the frame was rejected), quality
            report, detections, and timings.
        """
        return self._service.run(image_bytes, _calibration_for(device))

    def status(self) -> ServiceStatus:
        """Snapshot for ``GET /model/status``."""
        return self._service.status()

    @property
    def preprocessing_fingerprint(self) -> str:
        """Which preprocessing pipeline this service is serving (ADR-025)."""
        return str(self._service.pipeline.fingerprint)


def _calibration_for(device: Device | None) -> Any:
    """Adapt a device's stored calibration into the AI package's context type.

    Returns an empty context on anything unusable rather than raising. A camera
    with a corrupt homography should degrade to "no rectification", not stop its
    captures being processed — the photographs are still evidence.
    """
    import numpy as np
    from ai.preprocessing.calibration import homography_from_json
    from ai.preprocessing.types import CalibrationContext

    if device is None:
        return CalibrationContext()

    polygon = None
    raw_polygon = getattr(device, "roi_polygon", None)
    if raw_polygon:
        try:
            points = raw_polygon.get("points") if isinstance(raw_polygon, dict) else raw_polygon
            candidate = np.asarray(points, dtype=np.int32)
            if candidate.ndim == 2 and candidate.shape[1] == 2 and len(candidate) >= 3:
                polygon = candidate
        except (TypeError, ValueError):
            logger.warning("device %s has an unusable roi_polygon; ignoring", device.id)

    return CalibrationContext(
        homography=homography_from_json(getattr(device, "homography", None)),
        roi_polygon=polygon,
        device_name=getattr(device, "device_name", None),
    )
