"""The worker tasks: image → prediction → progress.

This is the path the whole system exists for. An ESP32 uploads a photograph;
some seconds later a number on a dashboard has moved, and a person can see why.

Retry policy is the part worth reading. **Transient failures retry; deterministic
ones do not.** A storage timeout is worth trying again in thirty seconds. A
corrupt JPEG will be exactly as corrupt in thirty seconds, and retrying it three
times only delays the moment somebody sees ``status='failed'`` with a reason
attached.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from celery import shared_task

from app.core.config import get_settings
from app.domain.entities import (
    BoundingBox,
    Detection,
    DetectionSummary,
    Prediction,
)
from app.domain.enums import ImageStatus, MacroStage, RemarkType, Severity
from app.domain.value_objects import Confidence, ProgressPct

__all__ = ["process_image", "recompute_window"]

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="inference.process_image",
    max_retries=3,
    default_retry_delay=30,
    queue="inference",
)
def process_image(self: Any, image_id: str) -> dict[str, Any]:
    """Classify one ingested image and update its project's progress.

    Args:
        self: The bound Celery task, used to schedule retries.
        image_id: The image row to process.

    Returns:
        A small summary, useful when inspecting the result backend by hand.
    """
    return asyncio.run(_process_image(self, UUID(image_id)))


@shared_task(
    bind=True,
    name="progress.recompute_window",
    max_retries=3,
    default_retry_delay=30,
    queue="inference",
)
def recompute_window(
    self: Any,
    project_id: str,
    window_start: str | None = None,
) -> dict[str, Any]:
    """Rebuild a project's progress timeline from its stored predictions."""
    moment = datetime.fromisoformat(window_start) if window_start else None
    return asyncio.run(_recompute(self, UUID(project_id), moment))


# ---------------------------------------------------------------------------
# implementations
# ---------------------------------------------------------------------------


async def _process_image(task: Any, image_id: UUID) -> dict[str, Any]:
    """Do the work, inside an event loop."""
    from ai.preprocessing.errors import DecodeError

    from app.infrastructure.ai.adapter import InferenceAdapter, get_inference_service
    from app.infrastructure.db.session import session_scope
    from app.infrastructure.repositories import (
        SqlAlchemyDeviceRepository,
        SqlAlchemyImageRepository,
        SqlAlchemyPredictionRepository,
    )
    from app.infrastructure.storage import get_storage

    settings = get_settings()
    adapter = InferenceAdapter(get_inference_service(settings))

    async with session_scope() as session:
        images = SqlAlchemyImageRepository(session)
        image = await images.get(image_id)
        if image is None:
            # Deleted between enqueue and execution. Not an error, and retrying
            # will not bring it back.
            logger.info("image %s no longer exists; nothing to do", image_id)
            return {"image_id": str(image_id), "status": "gone"}

        if image.status is ImageStatus.INFERRED:
            # Already scored. Redelivery after a worker restart is expected with
            # `acks_late`, and re-scoring would produce a second prediction row
            # for one photograph.
            logger.info("image %s already inferred; skipping", image_id)
            return {"image_id": str(image_id), "status": "already_inferred"}

        devices = SqlAlchemyDeviceRepository(session)
        device = await devices.get(image.device_id) if image.device_id else None

        try:
            payload = await get_storage(settings).get(image.storage_key)
        except Exception as exc:
            # Transient: the object store may simply be unreachable. The bytes
            # are still there.
            logger.warning("storage read failed for %s: %s", image_id, exc)
            raise task.retry(exc=exc) from exc

        try:
            result = adapter.run(payload, device)
        except DecodeError as exc:
            # Deterministic. Retrying three times only delays the moment somebody
            # sees why this image failed.
            logger.warning("image %s is undecodable: %s", image_id, exc)
            await images.update(_with_status(image, ImageStatus.FAILED))
            await session.commit()
            return {"image_id": str(image_id), "status": "failed", "reason": str(exc)}

        if result.rejected:
            await images.update(_with_status(image, ImageStatus.REJECTED))
            await session.commit()
            logger.info("image %s rejected: %s", image_id, result.quality.reason)
            return {
                "image_id": str(image_id),
                "status": "rejected",
                "reason": result.quality.reason,
            }

        classification = result.classification
        assert classification is not None  # noqa: S101 - guarded by `rejected` above

        model_id = await _active_model_id(session, adapter)
        stage = _stage_for(classification.class_index)

        predictions = SqlAlchemyPredictionRepository(session)
        await predictions.add(
            Prediction(
                id=uuid4(),
                image_id=image.id,
                model_id=model_id,
                fine_class_index=classification.class_index,
                fine_class=classification.class_name,
                confidence=Confidence.from_float(classification.confidence),
                macro_stage=stage.macro,
                raw_progress_pct=ProgressPct.from_float(stage.nominal_pct),
                class_probabilities=dict(classification.probabilities),
                inference_ms=result.inference_ms,
            )
        )

        await _store_detections(session, image.id, model_id, result)
        await images.update(_with_status(image, ImageStatus.INFERRED))
        await session.commit()

    # Aggregation runs as its own task so that a failure to recompute never
    # costs us the prediction we just stored - and so that several images
    # landing at once collapse into one recompute rather than N.
    recompute_window.delay(str(image.project_id), image.captured_at.isoformat())

    return {
        "image_id": str(image_id),
        "status": "inferred",
        "stage": classification.class_name,
        "confidence": round(classification.confidence, 4),
        "inference_ms": result.inference_ms,
    }


async def _recompute(
    task: Any,
    project_id: UUID,
    window_start: datetime | None,
) -> dict[str, Any]:
    """Rebuild the timeline and reflect it on the project."""
    from app.application.use_cases.recompute import (
        INSPECTION_REMARK,
        REGRESSION_REMARK,
        RecomputeProgress,
    )
    from app.infrastructure.db.session import session_scope
    from app.infrastructure.repositories import (
        SqlAlchemyDeviceRepository,
        SqlAlchemyImageRepository,
        SqlAlchemyPredictionRepository,
        SqlAlchemyProjectRepository,
        SqlAlchemyRemarkRepository,
        SqlAlchemySnapshotRepository,
    )

    _ = task
    async with session_scope() as session:
        outcome = await RecomputeProgress(
            SqlAlchemyProjectRepository(session),
            SqlAlchemyPredictionRepository(session),
            SqlAlchemyImageRepository(session),
            SqlAlchemyDeviceRepository(session),
            SqlAlchemySnapshotRepository(session),
        ).execute(project_id, window_start=window_start)

        if outcome is None:
            await session.commit()
            return {"project_id": str(project_id), "status": "no_eligible_predictions"}

        # Remarks are written here rather than inside the use case so the
        # aggregator's caller stays the only thing doing I/O - the algorithm
        # reports *that* a regression happened; the system decides what to say
        # about it.
        remarks = SqlAlchemyRemarkRepository(session)
        if outcome.regressed:
            await _system_remark(remarks, project_id, REGRESSION_REMARK, Severity.WARNING)
        if outcome.reached_ceiling:
            await _system_remark(remarks, project_id, INSPECTION_REMARK, Severity.INFO)

        await session.commit()

        return {
            "project_id": str(project_id),
            "status": "recomputed",
            "windows": outcome.windows_computed,
            "displayed_pct": float(outcome.snapshot.displayed_pct.value),
            "macro_stage": outcome.snapshot.macro_stage.value,
            "regressed": outcome.regressed,
            "awaiting_inspection": outcome.reached_ceiling,
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _Stage:
    """Nominal progress and macro stage for one class index."""

    __slots__ = ("macro", "nominal_pct")

    def __init__(self, macro: MacroStage, nominal_pct: float) -> None:
        self.macro = macro
        self.nominal_pct = nominal_pct


def _stage_for(class_index: int) -> _Stage:
    """Resolve a class index through the canonical table in ``ai/``."""
    from ai.progress.mapping import reference_for

    reference = reference_for(class_index)
    return _Stage(MacroStage(reference.macro_stage.value), reference.nominal_progress_pct)


def _with_status(image: Any, status: ImageStatus) -> Any:
    """Return *image* with a new status."""
    from dataclasses import replace

    return replace(image, status=status)


async def _store_detections(
    session: Any,
    image_id: UUID,
    model_id: UUID,
    result: Any,
) -> None:
    """Persist detection boxes and their summary counts.

    A malformed box is skipped rather than allowed to fail the task. Detection
    corroborates the classifier; it does not decide, and losing a stage reading
    because one box had a negative width would be a poor trade.
    """
    from app.infrastructure.repositories import SqlAlchemyDetectionRepository

    detections = SqlAlchemyDetectionRepository(session)
    stored = 0
    for found in result.detections.objects:
        try:
            box = BoundingBox(
                x=found.bbox.x,
                y=found.bbox.y,
                width=found.bbox.width,
                height=found.bbox.height,
            )
        except ValueError:
            logger.warning("skipping malformed detection box on image %s", image_id)
            continue

        await detections.add(
            Detection(
                id=uuid4(),
                image_id=image_id,
                model_id=model_id,
                class_name=found.class_name,
                confidence=Confidence.from_float(found.confidence),
                bbox=box,
            )
        )
        stored += 1

    await detections.add_summary(
        DetectionSummary(
            id=uuid4(),
            image_id=image_id,
            counts=result.detections.counts,
            total_objects=stored,
            inference_ms=result.detections.inference_ms,
        )
    )


async def _active_model_id(session: Any, adapter: Any) -> UUID:
    """Find (or register) the model row this prediction belongs to.

    Predictions carry a ``model_id`` so that "which model said this?" is always
    answerable — including after a retrain, when two predictions on the same
    image may legitimately disagree. A stub is registered like any other model,
    flagged in its name, so the provenance chain has no gap in it.
    """
    from app.domain.entities import AIModel
    from app.domain.enums import ModelKind
    from app.infrastructure.repositories import SqlAlchemyAIModelRepository

    models = SqlAlchemyAIModelRepository(session)
    active = await models.get_active(ModelKind.CLASSIFIER)
    if active is not None:
        return active.id

    info = adapter.status().classifier
    registered = await models.add(
        AIModel(
            id=uuid4(),
            name=info.name,
            kind=ModelKind.CLASSIFIER,
            architecture=info.architecture,
            version=info.version,
            class_names=tuple(info.class_names),
            input_size=info.input_size,
            is_active=True,
            # `weights_key=None` is what makes `AIModel.is_stub` true, so the
            # stub is identifiable without stuffing a non-numeric value into
            # `metrics`, which is typed dict[str, float] for the thesis
            # comparison table.
            weights_key=info.weights_path,
            metrics={},
            trained_at=datetime.now(UTC),
        )
    )
    return registered.id


async def _system_remark(
    remarks: Any,
    project_id: UUID,
    body: str,
    severity: Severity,
) -> None:
    """Write a system-authored remark onto the project."""
    from app.domain.entities import Remark

    await remarks.add(
        Remark(
            id=uuid4(),
            project_id=project_id,
            author_id=None,
            remark_type=RemarkType.SYSTEM,
            severity=severity,
            message=body,
            is_public=True,
        )
    )
