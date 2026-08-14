"""Stub models and the inference service.

The determinism tests are the important ones. Module 09's headline properties —
idempotent reprocessing and replayable history — are only demonstrable if the
same image yields the same prediction every time, in every process. A stub that
drifted would make those tests pass for the wrong reason.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import cv2
import pytest

from ai.inference.service import (
    InferenceService,
    PreprocessingMismatchError,
    build_service,
)
from ai.models.base import ObjectDetector, StageClassifier
from ai.models.stub import StubClassifier, StubDetector
from ai.preprocessing.pipeline import PreprocessingPipeline
from ai.preprocessing.types import Image
from ai.progress.constants import MIN_CONFIDENCE
from ai.progress.mapping import class_names


@pytest.fixture(autouse=True)
def _quiet_stub_warnings() -> None:
    """The stubs warn on construction by design; do not spam the test log."""
    logging.disable(logging.WARNING)


@pytest.fixture
def frame(site_photo: Image) -> Image:
    """A preprocessed-shaped frame."""
    return cv2.resize(site_photo, (224, 224), interpolation=cv2.INTER_AREA)


class TestStubClassifier:
    """A placeholder that must behave itself."""

    def test_it_satisfies_the_protocol(self) -> None:
        """So swapping in a real ResNet18 is a config change, not a rewrite."""
        assert isinstance(StubClassifier(), StageClassifier)

    def test_the_same_image_always_yields_the_same_prediction(self, frame: Image) -> None:
        """Without this, idempotency and replay tests prove nothing."""
        first = StubClassifier().predict(frame)
        second = StubClassifier().predict(frame)

        assert first.class_index == second.class_index
        assert first.confidence == second.confidence

    def test_different_images_can_yield_different_predictions(
        self, make_site_photo: Callable[..., Image]
    ) -> None:
        seen = set()
        for seed in range(40):
            photo = cv2.resize(make_site_photo(seed=seed), (224, 224))
            seen.add(StubClassifier().predict(photo).class_index)

        assert len(seen) > 1

    def test_probabilities_form_a_distribution(self, frame: Image) -> None:
        result = StubClassifier().predict(frame)

        assert len(result.probabilities) == len(class_names())
        assert sum(result.probabilities.values()) == pytest.approx(1.0, abs=1e-3)
        assert all(0.0 <= value <= 1.0 for value in result.probabilities.values())

    def test_the_winner_holds_the_most_mass(self, frame: Image) -> None:
        result = StubClassifier().predict(frame)

        assert result.probabilities[result.class_name] == max(result.probabilities.values())
        assert result.confidence == result.probabilities[result.class_name]

    def test_mass_concentrates_on_ordinal_neighbours(self, frame: Image) -> None:
        """How the real model will fail: the classes are a construction sequence,
        so Footings/Foundation confusion is far likelier than Footings/Roof."""
        result = StubClassifier(fixed_class_index=5).predict(frame)
        names = class_names()

        assert result.probabilities[names[4]] > result.probabilities[names[0]]
        assert result.probabilities[names[6]] > result.probabilities[names[9]]

    def test_confidence_is_plausible(self, frame: Image) -> None:
        """High enough to be eligible, never a suspicious 1.0."""
        result = StubClassifier().predict(frame)

        assert MIN_CONFIDENCE <= result.confidence < 1.0

    def test_a_fixed_class_can_be_forced(self, frame: Image) -> None:
        """How the approval flow at the ceiling gets driven in a test."""
        result = StubClassifier(fixed_class_index=9).predict(frame)

        assert result.class_name == "Completed"

    def test_it_declares_itself_a_stub(self) -> None:
        """In three places, so a demo cannot be mistaken for a result."""
        info = StubClassifier().info

        assert info.is_stub
        assert "stub" in info.version
        assert "stub" in info.architecture

    def test_class_names_come_from_the_canonical_table(self) -> None:
        assert StubClassifier().info.class_names == class_names()


class TestStubDetector:
    """Plumbing for the detection path."""

    def test_it_satisfies_the_protocol(self) -> None:
        assert isinstance(StubDetector(), ObjectDetector)

    def test_it_is_deterministic(self, frame: Image) -> None:
        first = StubDetector().detect(frame)
        second = StubDetector().detect(frame)

        assert first.counts == second.counts

    def test_boxes_are_normalised_and_in_bounds(
        self, make_site_photo: Callable[..., Image]
    ) -> None:
        """The backend's BoundingBox validates this and would reject an
        out-of-range box on insert, where it is far harder to diagnose."""
        detector = StubDetector()
        for seed in range(30):
            photo = cv2.resize(make_site_photo(seed=seed), (224, 224))
            for found in detector.detect(photo).objects:
                box = found.bbox
                assert 0.0 <= box.x <= 1.0
                assert 0.0 <= box.y <= 1.0
                assert 0.0 < box.width <= 1.0
                assert 0.0 < box.height <= 1.0
                assert box.x + box.width <= 1.0001
                assert box.y + box.height <= 1.0001
                assert 0.0 <= found.confidence <= 1.0

    def test_counts_match_the_objects(self, frame: Image) -> None:
        result = StubDetector().detect(frame)

        assert sum(result.counts.values()) == result.total


class TestInferenceService:
    """The critical path, end to end within `ai/`."""

    @staticmethod
    def _encode(image: Image) -> bytes:
        ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        assert ok
        return bytes(buffer)

    def test_a_good_image_produces_a_classification(self, site_photo: Image) -> None:
        result = build_service().run(self._encode(site_photo))

        assert result.quality.passed
        assert result.classification is not None
        assert not result.rejected

    def test_a_rejected_frame_never_reaches_the_model(self, site_photo: Image) -> None:
        """Not merely to save the forward pass.

        A classifier handed a blurry frame does not decline to answer — it
        answers confidently and wrongly, and that answer becomes a percentage
        somebody may act on.
        """
        blurred = cv2.GaussianBlur(site_photo, (31, 31), 0)
        result = build_service().run(self._encode(blurred))

        assert result.rejected
        assert result.classification is None
        assert not result.quality.passed
        assert result.quality.reason is not None

    def test_a_detector_failure_does_not_lose_the_prediction(self, site_photo: Image) -> None:
        """Detection corroborates; it does not decide.

        Letting a detector fault fail the task would mean an optional signal
        costs the project its stage reading — and the retry would fail the same
        way.
        """

        class ExplodingDetector:
            @property
            def info(self):  # type: ignore[no-untyped-def]
                return StubDetector().info

            def detect(self, image):  # type: ignore[no-untyped-def]
                msg = "CUDA out of memory"
                raise RuntimeError(msg)

            def warm_up(self) -> None:
                pass

        service = InferenceService(
            classifier=StubClassifier(),
            detector=ExplodingDetector(),  # type: ignore[arg-type]
        )
        result = service.run(self._encode(site_photo))

        assert result.classification is not None
        assert result.detections.total == 0

    def test_undecodable_bytes_raise(self) -> None:
        """Deterministic, so the caller must not retry."""
        from ai.preprocessing.errors import DecodeError

        with pytest.raises(DecodeError):
            build_service().run(b"not an image at all")

    def test_timings_are_reported(self, site_photo: Image) -> None:
        result = build_service().run(self._encode(site_photo))

        assert result.preprocessing_ms >= 0
        assert result.total_ms >= result.preprocessing_ms

    def test_the_result_carries_the_pipeline_fingerprint(self, site_photo: Image) -> None:
        service = build_service()
        result = service.run(self._encode(site_photo))

        assert result.preprocessing_fingerprint == service.pipeline.fingerprint

    def test_reprocessing_the_same_bytes_is_identical(self, site_photo: Image) -> None:
        """Module 09 reprocesses images; doing so must not change history."""
        payload = self._encode(site_photo)
        service = build_service()

        first = service.run(payload)
        second = service.run(payload)

        assert first.classification is not None
        assert second.classification is not None
        assert first.classification.class_index == second.classification.class_index
        assert first.detections.counts == second.detections.counts


class TestSkewDetection:
    """ADR-025 — the failure Module 06 exists to catch."""

    def test_a_mismatched_fingerprint_refuses_to_load(self) -> None:
        """At load, not at predict: the process must fail to start rather than
        serve quietly degraded predictions."""
        with pytest.raises(PreprocessingMismatchError, match="preprocessing mismatch"):
            InferenceService(classifier=StubClassifier(preprocessing_fingerprint="0" * 16))

    def test_a_matching_fingerprint_loads(self) -> None:
        pipeline = PreprocessingPipeline.from_config()
        service = InferenceService(
            classifier=StubClassifier(preprocessing_fingerprint=pipeline.fingerprint),
            pipeline=pipeline,
        )

        assert service.status().preprocessing_fingerprint == pipeline.fingerprint

    def test_an_unrecorded_fingerprint_warns_but_loads(self) -> None:
        """A checkpoint predating the convention must still be usable."""
        service = InferenceService(classifier=StubClassifier(preprocessing_fingerprint=None))

        assert service.classifier.info.preprocessing_fingerprint is None

    def test_the_error_names_the_remedy(self) -> None:
        """An operator reading this at 3 a.m. needs to know what to do."""
        with pytest.raises(PreprocessingMismatchError) as caught:
            InferenceService(classifier=StubClassifier(preprocessing_fingerprint="0" * 16))

        assert "retrain" in str(caught.value).lower()


class TestServiceStatus:
    """What `GET /model/status` reports."""

    def test_stub_usage_is_surfaced(self) -> None:
        """So a demo can never be mistaken for a result."""
        assert build_service().status().using_stubs

    def test_latency_accumulates(self, site_photo: Image) -> None:
        service = build_service()
        payload = TestInferenceService._encode(site_photo)

        service.run(payload)
        service.run(payload)

        assert service.status().images_processed == 2
        assert service.status().mean_latency_ms > 0

    def test_real_weights_are_refused_until_modules_07_and_08(self) -> None:
        """An honest failure, not a silent fallback to stubs.

        Falling back would let a deployment believe it was serving a trained
        model while reporting placeholder numbers.
        """
        with pytest.raises(NotImplementedError, match="Modules 07"):
            build_service(use_stubs=False)
