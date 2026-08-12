"""Report, AI model registry, notification, and audit-log entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from app.domain.enums import (
    ModelKind,
    NotificationType,
    ReportFormat,
    ReportKind,
    ReportStatus,
)

__all__ = ["AIModel", "AuditLog", "Notification", "Report"]


@dataclass(frozen=True, slots=True)
class Report:
    """An asynchronously generated PDF or CSV export (spec B.4).

    Reports are immutable once ``READY``; regenerating produces a new row, so
    there is an audit trail of what was reported when.
    """

    id: UUID
    project_id: UUID
    requested_by: UUID
    kind: ReportKind
    report_format: ReportFormat
    period_start: date
    period_end: date
    status: ReportStatus = ReportStatus.QUEUED
    storage_key: str | None = None
    error: str | None = None
    requested_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the reporting period."""
        if self.period_end < self.period_start:
            msg = (
                f"report period end ({self.period_end}) cannot precede start ({self.period_start})"
            )
            raise ValueError(msg)

    @property
    def is_downloadable(self) -> bool:
        """Whether the file exists and may be served."""
        return self.status is ReportStatus.READY and self.storage_key is not None


@dataclass(frozen=True, slots=True)
class AIModel:
    """A registered trained model, powering ``GET /model/status``.

    Exactly one model per :class:`~app.domain.enums.ModelKind` may be active at
    a time; the database enforces this with a partial unique index.

    Attributes:
        metrics: Evaluation results — accuracy, macro-F1, mAP, latency. Kept
            here so the thesis comparison table can be produced from the
            registry rather than from notes.
    """

    id: UUID
    name: str
    kind: ModelKind
    architecture: str
    version: str
    framework: str = "pytorch"
    weights_key: str | None = None
    class_names: tuple[str, ...] = ()
    input_size: int | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    is_active: bool = False
    trained_at: datetime | None = None
    created_at: datetime | None = None

    @property
    def is_stub(self) -> bool:
        """Whether this entry is the deterministic stand-in used before training.

        The stub satisfies the same interface as a real checkpoint, which is
        what lets Modules 09-14 be built before any dataset exists.
        """
        return self.weights_key is None


@dataclass(frozen=True, slots=True)
class Notification:
    """An in-app message to a user."""

    id: UUID
    user_id: UUID
    notification_type: NotificationType
    title: str
    body: str
    project_id: UUID | None = None
    read_at: datetime | None = None
    created_at: datetime | None = None

    @property
    def is_read(self) -> bool:
        """Whether the recipient has seen this notification."""
        return self.read_at is not None


@dataclass(frozen=True, slots=True)
class AuditLog:
    """A security-relevant action, retained for accountability.

    Written for pairing, unpairing, project approval, visibility changes, and
    membership changes. Approving a project awards the final 20 % of a
    building's recorded progress, so it must be attributable to a named person
    at a known time.
    """

    id: UUID
    action: str
    entity_type: str
    entity_id: UUID
    actor_user_id: UUID | None = None
    actor_device_id: UUID | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    ip_address: str | None = None
    created_at: datetime | None = None
