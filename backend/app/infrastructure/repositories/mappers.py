"""Translation between ORM rows and domain entities.

Kept in one place so the conversion rules are auditable. Two of them matter
more than they look:

* **Decimal ↔ value object.** The database stores ``numeric``; the domain uses
  :class:`~app.domain.value_objects.ProgressPct` and
  :class:`~app.domain.value_objects.Confidence`. Converting here means no other
  module has to remember which scale a number is on.
* **Nullable coordinates → ``GeoPoint | None``.** Latitude and longitude are
  two nullable columns but one conceptual value; a row with only one of them
  set is meaningless, so it maps to ``None``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from app.domain.entities import (
    AIModel,
    BoundingBox,
    CaptureSchedule,
    ContactMessage,
    Detection,
    DetectionSummary,
    Device,
    Image,
    Notification,
    PairingToken,
    Prediction,
    ProgressSnapshot,
    Project,
    ProjectMember,
    ReferenceAsset,
    RefreshToken,
    Remark,
    Report,
    User,
)
from app.domain.value_objects import Confidence, GeoPoint, ProgressPct, ProjectCode

if TYPE_CHECKING:
    from app.infrastructure.db import models

__all__ = [
    "to_ai_model",
    "to_contact_message",
    "to_device",
    "to_image",
    "to_notification",
    "to_pairing_token",
    "to_prediction",
    "to_project",
    "to_project_member",
    "to_reference_asset",
    "to_refresh_token",
    "to_remark",
    "to_report",
    "to_snapshot",
    "to_user",
]


def _geo(latitude: Decimal | None, longitude: Decimal | None) -> GeoPoint | None:
    """Combine two nullable numeric columns into an optional coordinate."""
    if latitude is None or longitude is None:
        return None
    return GeoPoint(latitude=float(latitude), longitude=float(longitude))


def to_user(row: models.UserModel) -> User:
    """Map a ``users`` row to a :class:`User`."""
    return User(
        id=row.id,
        username=row.username,
        email=row.email,
        full_name=row.full_name,
        professional_role=row.professional_role,
        profile_visibility=row.profile_visibility,
        company=row.company,
        bio=row.bio,
        avatar_key=row.avatar_key,
        is_active=row.is_active,
        email_verified_at=row.email_verified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_refresh_token(row: models.RefreshTokenModel) -> RefreshToken:
    """Map a ``refresh_tokens`` row."""
    return RefreshToken(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        family_id=row.family_id,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        user_agent=row.user_agent,
        ip_address=row.ip_address,
        created_at=row.created_at,
    )


def to_project(row: models.ProjectModel) -> Project:
    """Map a ``projects`` row to a :class:`Project`."""
    location = _geo(row.latitude, row.longitude)
    if location is None:  # pragma: no cover - both columns are NOT NULL
        msg = f"project {row.id} is missing coordinates"
        raise ValueError(msg)
    return Project(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        code=ProjectCode(row.project_code),
        location_label=row.location_label,
        location=location,
        start_date=row.start_date,
        deadline_date=row.deadline_date,
        visibility=row.visibility,
        status=row.status,
        approval_state=row.approval_state,
        progress_pct=ProgressPct(row.progress_pct),
        macro_stage=row.macro_stage,
        description=row.description,
        intended_use=row.intended_use,
        worker_count=row.worker_count,
        window_mode=row.window_mode,
        timezone=row.timezone,
        last_capture_at=row.last_capture_at,
        completed_at=row.completed_at,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        inspection_notes=row.inspection_notes,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_project_member(row: models.ProjectMemberModel) -> ProjectMember:
    """Map a ``project_members`` row."""
    return ProjectMember(
        id=row.id,
        project_id=row.project_id,
        user_id=row.user_id,
        membership_role=row.membership_role,
        membership_status=row.membership_status,
        invited_by=row.invited_by,
        invited_at=row.invited_at,
        responded_at=row.responded_at,
        created_at=row.created_at,
    )


def to_device(row: models.DeviceModel) -> Device:
    """Map a ``devices`` row, rebuilding the capture schedule from JSONB."""
    schedule_data = row.capture_schedule or {}
    schedule = CaptureSchedule(
        times=tuple(schedule_data.get("times", ("07:00", "16:00"))),
        timezone=str(schedule_data.get("timezone", "Asia/Manila")),
        jitter_seconds=int(schedule_data.get("jitter_seconds", 120)),
        enabled=bool(schedule_data.get("enabled", True)),
    )
    return Device(
        id=row.id,
        project_id=row.project_id,
        device_name=row.device_name,
        face=row.face,
        weight=float(row.weight),
        status=row.status,
        firmware_version=row.firmware_version,
        hardware_id=row.hardware_id,
        capture_schedule=schedule,
        homography=row.homography,
        roi_polygon=row.roi_polygon,
        last_seen_at=row.last_seen_at,
        last_battery_mv=row.last_battery_mv,
        last_rssi_dbm=row.last_rssi_dbm,
        paired_at=row.paired_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_pairing_token(row: models.PairingTokenModel) -> PairingToken:
    """Map a ``pairing_tokens`` row."""
    return PairingToken(
        id=row.id,
        project_id=row.project_id,
        face=row.face,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        created_by=row.created_by,
        used_at=row.used_at,
        used_by_device_id=row.used_by_device_id,
        created_at=row.created_at,
    )


def to_image(row: models.ImageModel) -> Image:
    """Map an ``images`` row."""
    return Image(
        id=row.id,
        project_id=row.project_id,
        filename=row.filename,
        storage_key=row.storage_key,
        captured_at=row.captured_at,
        sha256=row.sha256,
        source=row.source,
        status=row.status,
        device_id=row.device_id,
        preprocessed_key=row.preprocessed_key,
        thumb_key=row.thumb_key,
        uploaded_at=row.uploaded_at,
        seq_number=row.seq_number,
        location=_geo(row.latitude, row.longitude),
        gps_accuracy_m=float(row.gps_accuracy_m) if row.gps_accuracy_m is not None else None,
        altitude_m=float(row.altitude_m) if row.altitude_m is not None else None,
        satellites=row.satellites,
        width=row.width,
        height=row.height,
        size_bytes=row.size_bytes,
        exif=dict(row.exif or {}),
        quality_flags=dict(row.quality_flags or {}),
        rejected_reason=row.rejected_reason,
        created_at=row.created_at,
    )


def to_prediction(row: models.PredictionModel) -> Prediction:
    """Map a ``predictions`` row."""
    return Prediction(
        id=row.id,
        image_id=row.image_id,
        model_id=row.model_id,
        fine_class_index=row.fine_class_index,
        fine_class=row.fine_class,
        confidence=Confidence(row.confidence),
        macro_stage=row.macro_stage,
        raw_progress_pct=ProgressPct(row.raw_progress_pct),
        class_probabilities=dict(row.class_probabilities or {}),
        inference_ms=row.inference_ms,
        created_at=row.created_at,
    )


def to_snapshot(row: models.ProgressSnapshotModel) -> ProgressSnapshot:
    """Map a ``project_progress_snapshots`` row."""
    return ProgressSnapshot(
        id=row.id,
        project_id=row.project_id,
        window_start=row.window_start,
        window_end=row.window_end,
        raw_pct=ProgressPct(row.raw_pct),
        ema_pct=ProgressPct(row.ema_pct),
        displayed_pct=ProgressPct(row.displayed_pct),
        macro_stage=row.macro_stage,
        foundation_pct=float(row.foundation_pct),
        framing_pct=float(row.framing_pct),
        roofing_pct=float(row.roofing_pct),
        finishing_pct=float(row.finishing_pct),
        approval_pct=float(row.approval_pct),
        eligible_image_count=row.eligible_image_count,
        contributing_image_ids=tuple(row.contributing_image_ids or ()),
        device_weights=dict(row.device_weights or {}),
        algorithm_version=row.algorithm_version,
        created_at=row.created_at,
    )


def to_remark(row: models.RemarkModel) -> Remark:
    """Map a ``remarks`` row."""
    return Remark(
        id=row.id,
        project_id=row.project_id,
        remark_type=row.remark_type,
        severity=row.severity,
        message=row.message,
        author_id=row.author_id,
        is_public=row.is_public,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        created_at=row.created_at,
    )


def to_reference_asset(row: models.ReferenceAssetModel) -> ReferenceAsset:
    """Map a ``reference_assets`` row."""
    return ReferenceAsset(
        id=row.id,
        project_id=row.project_id,
        uploaded_by=row.uploaded_by,
        kind=row.kind,
        storage_key=row.storage_key,
        original_filename=row.original_filename,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        notes=row.notes,
        is_public=row.is_public,
        created_at=row.created_at,
    )


def to_report(row: models.ReportModel) -> Report:
    """Map a ``reports`` row."""
    return Report(
        id=row.id,
        project_id=row.project_id,
        requested_by=row.requested_by,
        kind=row.kind,
        report_format=row.report_format,
        period_start=row.period_start,
        period_end=row.period_end,
        status=row.status,
        storage_key=row.storage_key,
        error=row.error,
        requested_at=row.requested_at,
        completed_at=row.completed_at,
    )


def to_ai_model(row: models.AIModelModel) -> AIModel:
    """Map an ``ai_models`` row."""
    class_names: list[str] = list(row.class_names or [])
    return AIModel(
        id=row.id,
        name=row.name,
        kind=row.kind,
        architecture=row.architecture,
        version=row.version,
        framework=row.framework,
        weights_key=row.weights_key,
        class_names=tuple(class_names),
        input_size=row.input_size,
        metrics=dict(row.metrics or {}),
        is_active=row.is_active,
        trained_at=row.trained_at,
        created_at=row.created_at,
    )


def to_notification(row: models.NotificationModel) -> Notification:
    """Map a ``notifications`` row."""
    return Notification(
        id=row.id,
        user_id=row.user_id,
        notification_type=row.notification_type,
        title=row.title,
        body=row.body,
        project_id=row.project_id,
        read_at=row.read_at,
        created_at=row.created_at,
    )


def to_contact_message(row: models.ContactMessageModel) -> ContactMessage:
    """Map a ``contact_messages`` row."""
    return ContactMessage(
        id=row.id,
        name=row.name,
        email=row.email,
        subject=row.subject,
        message=row.message,
        ip_address=row.ip_address,
        user_agent=row.user_agent,
        handled_at=row.handled_at,
        created_at=row.created_at,
    )


def to_detection(row: models.DetectionModel) -> Detection:
    """Map a ``detections`` row."""
    return Detection(
        id=row.id,
        image_id=row.image_id,
        model_id=row.model_id,
        class_name=row.class_name,
        confidence=Confidence(row.confidence),
        bbox=BoundingBox(
            x=float(row.bbox_x),
            y=float(row.bbox_y),
            width=float(row.bbox_w),
            height=float(row.bbox_h),
        ),
        created_at=row.created_at,
    )


def to_detection_summary(row: models.DetectionSummaryModel) -> DetectionSummary:
    """Map a ``detection_summaries`` row."""
    return DetectionSummary(
        id=row.id,
        image_id=row.image_id,
        counts=dict(row.counts or {}),
        total_objects=row.total_objects,
        inference_ms=row.inference_ms,
        created_at=row.created_at,
    )
