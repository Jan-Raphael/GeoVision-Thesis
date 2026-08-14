"""Entity → response mapping for the AI surface.

Kept beside ``presenters.py`` rather than inside it: that module is already the
project-folder mapper and would otherwise become the place every module adds a
function to. Same job, same rules — no I/O, no repositories, no branching on
permissions. A presenter that has to make a decision is a use case wearing the
wrong hat.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.api.schemas.predictions import (
    AdHocPredictionResponse,
    BoundingBoxResponse,
    DetectionResponse,
    HistoryEntryResponse,
    ImageDetailResponse,
    LiveModelResponse,
    ModelStatusResponse,
    PredictionResponse,
    ProgressResponse,
    QualityResponse,
    RegisteredModelResponse,
    SnapshotPointResponse,
    StageBarsResponse,
    TimelineResponse,
)
from app.api.v1.presenters import map_url_for

if TYPE_CHECKING:
    from app.application.ports.inference_gateway import AdHocPrediction, WorkerModelInfo
    from app.application.use_cases.models import ModelStatus
    from app.application.use_cases.predictions import HistoryEntry, ImageDetail
    from app.application.use_cases.progress import CurrentProgress
    from app.domain.entities import AIModel, Detection, Prediction, ProgressSnapshot

__all__ = [
    "present_adhoc",
    "present_history_entry",
    "present_image_detail",
    "present_model",
    "present_model_status",
    "present_prediction",
    "present_progress",
    "present_timeline",
]


def _box(bbox: object) -> BoundingBoxResponse:
    """Map any normalised box — domain entity or port dataclass — to the wire."""
    return BoundingBoxResponse(
        x=getattr(bbox, "x", 0.0),
        y=getattr(bbox, "y", 0.0),
        width=getattr(bbox, "width", 0.0),
        height=getattr(bbox, "height", 0.0),
    )


def present_prediction(prediction: Prediction) -> PredictionResponse:
    """Map a stored prediction."""
    return PredictionResponse(
        id=prediction.id,
        image_id=prediction.image_id,
        model_id=prediction.model_id,
        stage=prediction.fine_class,
        class_index=prediction.fine_class_index,
        confidence=prediction.confidence.as_float(),
        macro_stage=prediction.macro_stage,
        raw_progress_pct=prediction.raw_progress_pct.as_float(),
        is_eligible=prediction.is_eligible,
        low_confidence=prediction.low_confidence,
        class_probabilities=dict(prediction.class_probabilities),
        inference_ms=prediction.inference_ms,
        created_at=prediction.created_at,
    )


def _detection(detection: Detection) -> DetectionResponse:
    """Map one stored detection box."""
    return DetectionResponse(
        class_name=detection.class_name,
        confidence=detection.confidence.as_float(),
        bbox=_box(detection.bbox),
    )


def present_image_detail(detail: ImageDetail) -> ImageDetailResponse:
    """Map the full image detail view."""
    image = detail.image
    location = image.location
    return ImageDetailResponse(
        id=image.id,
        project_id=image.project_id,
        device_id=image.device_id,
        filename=image.filename,
        status=image.status,
        captured_at=image.captured_at,
        uploaded_at=image.uploaded_at,
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
        gps_accuracy_m=image.gps_accuracy_m,
        altitude_m=image.altitude_m,
        width=image.width,
        height=image.height,
        size_bytes=image.size_bytes,
        sha256=image.sha256,
        map_url=map_url_for(location.latitude, location.longitude) if location else None,
        rejected_reason=image.rejected_reason,
        quality_flags=dict(image.quality_flags),
        prediction=present_prediction(detail.prediction) if detail.prediction else None,
        detections=[_detection(found) for found in detail.detections],
        counts=dict(detail.summary.counts) if detail.summary else {},
        original_url=detail.original_url,
        preprocessed_url=detail.preprocessed_url,
        thumb_url=detail.thumb_url,
    )


def present_history_entry(entry: HistoryEntry) -> HistoryEntryResponse:
    """Map one history row, prediction or not."""
    image = entry.image
    location = image.location
    prediction = entry.prediction
    return HistoryEntryResponse(
        image_id=image.id,
        filename=image.filename,
        captured_at=image.captured_at,
        status=image.status,
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
        thumb_url=image.thumb_key,
        device_id=image.device_id,
        stage=prediction.fine_class if prediction else None,
        confidence=prediction.confidence.as_float() if prediction else None,
        macro_stage=prediction.macro_stage if prediction else None,
        raw_progress_pct=prediction.raw_progress_pct.as_float() if prediction else None,
        is_eligible=prediction.is_eligible if prediction else None,
    )


def present_adhoc(result: AdHocPrediction) -> AdHocPredictionResponse:
    """Map the stateless prediction, stamped as not persisted."""
    return AdHocPredictionResponse(
        rejected=result.rejected,
        persisted=False,
        stage=result.stage,
        class_index=result.class_index,
        confidence=result.confidence,
        macro_stage=result.macro_stage,
        progress=result.progress_pct,
        probabilities=dict(result.probabilities),
        detections=[
            DetectionResponse(
                class_name=found.class_name,
                confidence=found.confidence,
                bbox=_box(found.bbox),
            )
            for found in result.detections
        ],
        counts=dict(result.counts),
        quality=QualityResponse(
            passed=result.quality.passed,
            flags=list(result.quality.flags),
            blur_score=result.quality.blur_score,
            brightness=result.quality.brightness,
            occlusion_ratio=result.quality.occlusion_ratio,
        ),
        rejection_reason=result.rejection_reason,
        preprocessing_ms=result.preprocessing_ms,
        inference_ms=result.inference_ms,
        total_ms=result.total_ms,
        model_name=result.model_name,
        model_version=result.model_version,
        model_is_stub=result.model_is_stub,
        preprocessing_fingerprint=result.preprocessing_fingerprint,
    )


def present_progress(progress: CurrentProgress) -> ProgressResponse:
    """Map the current progress reading."""
    return ProgressResponse(
        displayed_pct=progress.displayed_pct,
        macro_stage=progress.macro_stage,
        stages=StageBarsResponse(
            foundation_pct=progress.stages.foundation_pct,
            framing_pct=progress.stages.framing_pct,
            roofing_pct=progress.stages.roofing_pct,
            finishing_pct=progress.stages.finishing_pct,
            approval_pct=progress.stages.approval_pct,
        ),
        updated_at=progress.updated_at,
        algorithm_version=progress.algorithm_version,
        eligible_image_count=progress.eligible_image_count,
        devices_reporting=progress.devices_reporting,
        has_data=progress.has_data,
    )


def present_timeline(snapshots: tuple[ProgressSnapshot, ...]) -> TimelineResponse:
    """Map the snapshot series behind the chart."""
    points = [
        SnapshotPointResponse(
            window_start=snapshot.window_start,
            window_end=snapshot.window_end,
            displayed_pct=snapshot.displayed_pct.as_float(),
            raw_pct=snapshot.raw_pct.as_float(),
            ema_pct=snapshot.ema_pct.as_float(),
            macro_stage=snapshot.macro_stage,
            eligible_image_count=snapshot.eligible_image_count,
            devices_reporting=snapshot.devices_reporting,
            algorithm_version=snapshot.algorithm_version,
        )
        for snapshot in snapshots
    ]
    return TimelineResponse(
        points=points,
        # The series' version, not a hard-coded one: after an algorithm change
        # a chart may legitimately span two, and reporting only the newest would
        # misattribute the older half of the curve.
        algorithm_version=points[-1].algorithm_version if points else "progress-v1",
    )


def present_model(model: AIModel) -> RegisteredModelResponse:
    """Map one registry row."""
    return RegisteredModelResponse(
        id=model.id,
        name=model.name,
        kind=model.kind,
        architecture=model.architecture,
        version=model.version,
        class_names=list(model.class_names),
        input_size=model.input_size,
        is_active=model.is_active,
        is_stub=model.is_stub,
        metrics=dict(model.metrics),
        trained_at=model.trained_at,
    )


def _live_model(info: WorkerModelInfo) -> LiveModelResponse:
    """Map what a worker currently has in memory."""
    return LiveModelResponse(
        name=info.name,
        architecture=info.architecture,
        version=info.version,
        class_names=list(info.class_names),
        input_size=info.input_size,
        device=info.device,
        is_stub=info.is_stub,
        preprocessing_fingerprint=info.preprocessing_fingerprint,
    )


def present_model_status(status: ModelStatus) -> ModelStatusResponse:
    """Map the reconciled registry-plus-worker view."""
    live = status.live
    return ModelStatusResponse(
        worker_reachable=status.worker_reachable,
        using_stubs=status.using_stubs,
        classifier=present_model(status.classifier) if status.classifier else None,
        detector=present_model(status.detector) if status.detector else None,
        live_classifier=_live_model(live.classifier) if live else None,
        live_detector=_live_model(live.detector) if live and live.detector else None,
        preprocessing_fingerprint=live.preprocessing_fingerprint if live else None,
        preprocessing_matches=status.preprocessing_matches,
        loaded_at=live.loaded_at if live else None,
        mean_latency_ms=live.mean_latency_ms if live else None,
        images_processed=live.images_processed if live else None,
        queue_depth=dict(status.queue_depth),
    )
