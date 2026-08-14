"""The inference service: bytes in, prediction out.

One object, built **once per worker process**, holding the preprocessing
pipeline and both models. Constructing it per task is the classic performance
bug in this kind of system — loading a ResNet18 checkpoint costs a second or
more, which would dwarf the inference it exists to perform.

The order inside :meth:`InferenceService.run` matters:

1. **Preprocess and gate first.** A rejected frame never reaches the model. Not
   only to save the forward pass — a classifier handed a blurry, dark, or
   truck-obscured frame does not decline to answer. It answers confidently and
   wrongly, and that answer flows into a percentage somebody may act on.
2. **Classify.** This is the number that matters.
3. **Detect, and treat failure as non-fatal.** Detection corroborates; it does
   not decide. A detector that throws must not cost the project its stage
   reading — the prediction is still saved, with no boxes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ai.inference.schemas import InferenceResult, ServiceStatus
from ai.models.base import ObjectDetector, StageClassifier
from ai.models.stub import StubClassifier, StubDetector
from ai.preprocessing.pipeline import PreprocessingPipeline
from ai.preprocessing.types import CalibrationContext

__all__ = ["InferenceService", "PreprocessingMismatchError", "build_service"]

logger = logging.getLogger(__name__)


class PreprocessingMismatchError(RuntimeError):
    """The model was trained through a different preprocessing pipeline.

    Raised at **load** time, never at predict time, so the process fails to start
    rather than serving quietly degraded predictions. This is the failure mode
    Module 06's fingerprint exists to catch (ADR-025): a config edit after
    training costs accuracy silently, and nothing else in the system would ever
    report it.
    """


@dataclass(slots=True)
class InferenceService:
    """Loads the models once and runs the full image → prediction path."""

    classifier: StageClassifier
    detector: ObjectDetector | None = None
    pipeline: PreprocessingPipeline = field(default_factory=PreprocessingPipeline.from_config)
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _total_ms: float = field(default=0.0, repr=False)
    _count: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        """Verify the model matches the live preprocessing pipeline."""
        self._verify_fingerprint()

    # -- the critical path --------------------------------------------------

    def run(
        self, image_bytes: bytes, calibration: CalibrationContext | None = None
    ) -> InferenceResult:
        """Take raw image bytes through preprocessing, classification, detection.

        Args:
            image_bytes: The stored original, as uploaded.
            calibration: The device's homography and ROI, if it has been
                calibrated.

        Returns:
            The classification (or ``None`` if the frame was rejected), the
            quality report, any detections, and timings.

        Raises:
            DecodeError: If the bytes are not a decodable image. Deterministic,
                so the caller must **not** retry — a corrupt file will be just as
                corrupt in thirty seconds.
        """
        started = time.perf_counter()

        preprocess_started = time.perf_counter()
        processed = self.pipeline.run_bytes(image_bytes, calibration)
        preprocessing_ms = int((time.perf_counter() - preprocess_started) * 1000)

        if not processed.quality.passed:
            logger.info("image rejected by quality gate: %s", processed.quality.reason)
            return InferenceResult(
                classification=None,
                quality=processed.quality,
                preprocessing_ms=preprocessing_ms,
                total_ms=int((time.perf_counter() - started) * 1000),
                preprocessing_fingerprint=processed.fingerprint,
            )

        classification = self.classifier.predict(processed.image)
        detections = self._detect(processed.image)

        total_ms = int((time.perf_counter() - started) * 1000)
        self._record(total_ms)

        return InferenceResult(
            classification=classification,
            quality=processed.quality,
            detections=detections,
            preprocessing_ms=preprocessing_ms,
            total_ms=total_ms,
            preprocessing_fingerprint=processed.fingerprint,
        )

    def _detect(self, image):  # type: ignore[no-untyped-def]
        """Run the detector, swallowing failure.

        Detection corroborates the classifier; it does not decide. Letting a
        detector fault fail the whole task would mean an optional signal could
        cost the project its stage reading — and the retry would fail
        identically.
        """
        from ai.models.base import DetectionResult

        if self.detector is None:
            return DetectionResult()
        try:
            return self.detector.detect(image)
        except Exception:
            logger.exception("detector failed; continuing without detections")
            return DetectionResult()

    # -- lifecycle ----------------------------------------------------------

    def warm_up(self) -> None:
        """Run one throwaway inference through every model.

        Called from Celery's ``worker_process_init``. The first forward pass
        allocates buffers and resolves kernels; paying that on a real upload
        makes the first capture after every deploy look pathologically slow.
        """
        self.classifier.warm_up()
        if self.detector is not None:
            self.detector.warm_up()
        logger.info(
            "inference service ready: classifier=%s detector=%s preprocessing=%s%s",
            self.classifier.info.version,
            self.detector.info.version if self.detector else "none",
            self.pipeline.fingerprint,
            " [STUB MODELS]" if self.status().using_stubs else "",
        )

    def status(self) -> ServiceStatus:
        """Snapshot for ``GET /model/status``."""
        return ServiceStatus(
            classifier=self.classifier.info,
            detector=self.detector.info if self.detector else None,
            preprocessing_fingerprint=self.pipeline.fingerprint,
            loaded_at=self.loaded_at.isoformat(),
            mean_latency_ms=round(self._total_ms / self._count, 2) if self._count else 0.0,
            images_processed=self._count,
        )

    # -- internals ----------------------------------------------------------

    def _record(self, total_ms: int) -> None:
        """Accumulate the rolling latency figure."""
        self._total_ms += total_ms
        self._count += 1

    def _verify_fingerprint(self) -> None:
        """Refuse to serve a model trained through a different pipeline.

        Raises:
            PreprocessingMismatchError: On a mismatch.
        """
        expected = self.classifier.info.preprocessing_fingerprint
        actual = self.pipeline.fingerprint

        if expected is None:
            # No recorded fingerprint: a stub, or a checkpoint predating the
            # convention. Warn rather than refuse - failing here would make the
            # stub path unusable, which is the path the whole system currently
            # runs on.
            logger.warning(
                "classifier %s records no preprocessing fingerprint; "
                "train/serve skew cannot be verified",
                self.classifier.info.name,
            )
            return

        if expected != actual:
            msg = (
                f"preprocessing mismatch: {self.classifier.info.name} was trained "
                f"through pipeline {expected}, but {self.pipeline.source} produces "
                f"{actual}. Serving would silently degrade accuracy. Restore the "
                f"training-time config or retrain (ADR-025)."
            )
            raise PreprocessingMismatchError(msg)


def build_service(
    *,
    use_stubs: bool = True,
    classifier_weights: str | None = None,
    detector_weights: str | None = None,
    config_path: str | None = None,
    fixed_class_index: int | None = None,
) -> InferenceService:
    """Construct the service from configuration.

    Args:
        use_stubs: Use the deterministic placeholders. Default while the dataset
            is being collected; set ``GV_USE_STUB_MODELS=false`` once weights
            exist.
        classifier_weights: Path to a trained classifier checkpoint.
        detector_weights: Path to trained detector weights.
        config_path: Preprocessing config override.
        fixed_class_index: Stub only — always predict this class, for driving a
            specific scenario such as the approval flow at the ceiling.

    Returns:
        A service ready to :meth:`InferenceService.warm_up`.

    Raises:
        NotImplementedError: If real weights are requested. Modules 07 and 08
            produce them; until then this is an honest failure rather than a
            silent fallback to stubs, which would let a deployment believe it was
            serving a trained model.
    """
    pipeline = PreprocessingPipeline.from_config(config_path)

    if not use_stubs:
        msg = (
            "Real model backends arrive with Modules 07 (classifier) and 08 "
            "(detector). Set GV_USE_STUB_MODELS=true until then."
        )
        raise NotImplementedError(msg)

    _ = classifier_weights, detector_weights
    return InferenceService(
        classifier=StubClassifier(
            fixed_class_index=fixed_class_index,
            preprocessing_fingerprint=pipeline.fingerprint,
        ),
        detector=StubDetector(),
        pipeline=pipeline,
    )
