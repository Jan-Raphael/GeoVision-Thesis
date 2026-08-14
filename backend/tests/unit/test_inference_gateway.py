"""The worker↔API contract for ad-hoc prediction and model status.

These two sides talk over JSON through Redis, so nothing type-checks the join:
the worker builds a mapping in ``app.worker.inference`` and the gateway rebuilds
a dataclass from it in ``app.infrastructure.ai.gateway``. A renamed key would
pass every other test in the suite and fail during a live demo. So the payload
is built by the **real** producer here and handed to the **real** consumer, with
no hand-written fixture in between to drift away from either of them.
"""

from __future__ import annotations

import pytest

from app.application.ports.inference_gateway import WorkerStatus
from app.application.use_cases.models import _fingerprints_agree
from app.infrastructure.ai.gateway import (
    TASK_PREDICT_ADHOC,
    TASK_SERVICE_STATUS,
    _to_prediction,
    _to_status,
)

pytestmark = pytest.mark.unit


class _Adapter:
    """The slice of ``InferenceAdapter`` that the payload builder touches."""

    def __init__(self, info: object) -> None:
        self._info = info

    def status(self) -> object:
        from ai.inference.schemas import ServiceStatus

        return ServiceStatus(
            classifier=self._info,  # type: ignore[arg-type]
            detector=None,
            preprocessing_fingerprint="fp-abc",
            loaded_at="2026-08-14T12:00:00Z",
            mean_latency_ms=180.0,
            images_processed=3,
        )


def _model_info(*, fingerprint: str | None = "fp-abc") -> object:
    """A loaded stub classifier's provenance."""
    from ai.models.base import ModelInfo

    return ModelInfo(
        name="stub-classifier",
        architecture="stub",
        version="stub-v1",
        class_names=("footings", "walls"),
        input_size=224,
        device="cpu",
        is_stub=True,
        preprocessing_fingerprint=fingerprint,
    )


def _result(*, rejected: bool) -> object:
    """A real ``InferenceResult``, passed or rejected."""
    from ai.inference.schemas import InferenceResult
    from ai.models.base import (
        BoundingBox,
        Classification,
        DetectedObject,
        DetectionResult,
    )
    from ai.preprocessing.quality import QualityFlag, QualityReport

    if rejected:
        return InferenceResult(
            classification=None,
            quality=QualityReport(
                passed=False,
                flags=(QualityFlag.BLURRY,),
                blur_score=8.0,
                brightness=0.4,
                occlusion_ratio=0.0,
            ),
            preprocessing_ms=40,
            total_ms=45,
            preprocessing_fingerprint="fp-abc",
        )
    return InferenceResult(
        classification=Classification(
            class_index=6,
            class_name="walls",
            confidence=0.94,
            probabilities={"walls": 0.94, "footings": 0.06},
            inference_ms=150,
        ),
        quality=QualityReport(
            passed=True, flags=(), blur_score=142.0, brightness=0.51, occlusion_ratio=0.01
        ),
        detections=DetectionResult(
            objects=(
                DetectedObject(
                    class_name="wall",
                    confidence=0.88,
                    bbox=BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4),
                ),
            ),
            inference_ms=30,
        ),
        preprocessing_ms=88,
        total_ms=268,
        preprocessing_fingerprint="fp-abc",
    )


class TestTaskNames:
    """The gateway and the worker must agree on what to call."""

    def test_predict_task_name_matches_the_registered_task(self) -> None:
        from app.worker.inference import predict_adhoc

        assert predict_adhoc.name == TASK_PREDICT_ADHOC

    def test_status_task_name_matches_the_registered_task(self) -> None:
        from app.worker.inference import service_status

        assert service_status.name == TASK_SERVICE_STATUS

    def test_interactive_tasks_are_routed_off_the_image_queue(self) -> None:
        """Otherwise a live request queues behind the whole capture backlog."""
        from app.infrastructure.celery import celery_app

        routes = celery_app.conf.task_routes
        assert routes[TASK_PREDICT_ADHOC]["queue"] == "interactive"
        assert routes[TASK_SERVICE_STATUS]["queue"] == "interactive"


class TestAdHocRoundTrip:
    """What the worker sends is what the gateway reads."""

    def test_a_scored_frame_survives_the_wire(self) -> None:
        from app.worker.inference import _as_adhoc_payload

        payload = _as_adhoc_payload(_result(rejected=False), _Adapter(_model_info()))
        prediction = _to_prediction(payload)

        assert prediction.rejected is False
        assert prediction.stage == "walls"
        assert prediction.class_index == 6
        assert prediction.confidence == pytest.approx(0.94)
        # Resolved through the canonical class table in `ai`, not hard-coded.
        assert prediction.macro_stage == "framing"
        assert prediction.progress_pct == pytest.approx(40.0)
        assert prediction.quality.passed is True
        assert prediction.quality.blur_score == pytest.approx(142.0)
        assert prediction.detections[0].class_name == "wall"
        assert prediction.detections[0].bbox.width == pytest.approx(0.3)
        assert prediction.counts == {"wall": 1}
        assert prediction.model_is_stub is True
        assert prediction.preprocessing_fingerprint == "fp-abc"

    def test_a_rejected_frame_carries_its_reason_and_no_stage(self) -> None:
        from app.worker.inference import _as_adhoc_payload

        payload = _as_adhoc_payload(_result(rejected=True), _Adapter(_model_info()))
        prediction = _to_prediction(payload)

        assert prediction.rejected is True
        assert prediction.stage is None
        assert prediction.confidence is None
        assert prediction.quality.passed is False
        assert prediction.rejection_reason  # the flag names, not an empty string
        assert "blur" in prediction.rejection_reason


class TestStatusRoundTrip:
    """The status probe's payload survives the wire too."""

    def test_worker_status_is_rebuilt(self) -> None:
        from app.worker.inference import _as_model_payload

        info = _model_info()
        payload = {
            "classifier": _as_model_payload(info),
            "detector": None,
            "preprocessing_fingerprint": "fp-abc",
            "loaded_at": "2026-08-14T12:00:00Z",
            "mean_latency_ms": 180.0,
            "images_processed": 3,
        }
        status = _to_status(payload)

        assert status.classifier.name == "stub-classifier"
        assert status.classifier.class_names == ("footings", "walls")
        assert status.classifier.device == "cpu"
        assert status.detector is None
        assert status.using_stubs is True
        assert status.images_processed == 3


class TestFingerprintReconciliation:
    """Unknown and mismatched are different answers (ADR-025)."""

    def _status(self, *, trained: str | None, running: str) -> WorkerStatus:
        from app.infrastructure.ai.gateway import _to_model_info
        from app.worker.inference import _as_model_payload

        return WorkerStatus(
            classifier=_to_model_info(_as_model_payload(_model_info(fingerprint=trained))),
            detector=None,
            preprocessing_fingerprint=running,
            loaded_at="2026-08-14T12:00:00Z",
        )

    def test_matching_fingerprints_agree(self) -> None:
        assert _fingerprints_agree(self._status(trained="fp-abc", running="fp-abc")) is True

    def test_a_changed_pipeline_is_reported_as_a_mismatch(self) -> None:
        """The failure this exists to catch: silently degraded accuracy."""
        assert _fingerprints_agree(self._status(trained="fp-abc", running="fp-xyz")) is False

    def test_an_unstamped_model_is_unknown_not_mismatched(self) -> None:
        """Otherwise every stub run would cry wolf."""
        assert _fingerprints_agree(self._status(trained=None, running="fp-abc")) is None
