"""Project, membership, remark, and reference-asset entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from app.domain.enums import (
    ApprovalState,
    AssetKind,
    MacroStage,
    MembershipRole,
    MembershipStatus,
    ProjectStatus,
    RemarkType,
    Severity,
    Visibility,
)
from app.domain.value_objects import GeoPoint, ProgressPct, ProjectCode

__all__ = ["Project", "ProjectMember", "ReferenceAsset", "Remark", "StageBreakdown"]


@dataclass(frozen=True, slots=True)
class Project:
    """A construction project — the "project folder" of the dashboard spec.

    Attributes:
        code: Immutable after creation; embedded in device names and image
            filenames.
        visibility: ``PUBLIC`` projects appear on the homepage feed and are
            readable by anonymous visitors.
        progress_pct: Denormalised copy of the latest snapshot's displayed
            value, so project lists render without touching the snapshot table.
        approval_state: Gates the final 20 % — see ADR-007.
    """

    id: UUID
    owner_id: UUID
    name: str
    code: ProjectCode
    location_label: str
    location: GeoPoint
    start_date: date
    deadline_date: date
    visibility: Visibility = Visibility.PRIVATE
    status: ProjectStatus = ProjectStatus.ACTIVE
    approval_state: ApprovalState = ApprovalState.NOT_READY
    progress_pct: ProgressPct = field(default_factory=ProgressPct.zero)
    macro_stage: MacroStage | None = None
    description: str | None = None
    intended_use: str | None = None
    worker_count: int | None = None
    window_mode: str = "daily"
    timezone: str = "Asia/Manila"
    last_capture_at: datetime | None = None
    completed_at: datetime | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    inspection_notes: str | None = None
    archived_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Check invariants that must hold for any project."""
        if self.deadline_date < self.start_date:
            msg = f"deadline ({self.deadline_date}) cannot precede start date ({self.start_date})"
            raise ValueError(msg)
        if self.worker_count is not None and self.worker_count < 0:
            msg = f"worker_count cannot be negative, got {self.worker_count}"
            raise ValueError(msg)

    @property
    def is_public(self) -> bool:
        """Whether anonymous visitors may read this project."""
        return self.visibility is Visibility.PUBLIC and self.archived_at is None

    @property
    def awaits_inspection(self) -> bool:
        """Whether the AI has finished and the owner must now inspect."""
        return self.approval_state is ApprovalState.AWAITING_INSPECTION

    @property
    def planned_duration_days(self) -> int:
        """Contracted duration, at least one day."""
        return max((self.deadline_date - self.start_date).days, 1)

    def expected_pct_at(self, moment: date) -> ProgressPct:
        """Progress a linear schedule would predict by *moment*.

        Used to decide whether a project is ``DELAYED``. The curve is linear up
        to the 80 % machine ceiling, because the final 20 % is a human action
        that cannot be scheduled. See ``Project-Status-Rules.md``.
        """
        elapsed = (moment - self.start_date).days
        ratio = min(max(elapsed / self.planned_duration_days, 0.0), 1.0)
        return ProgressPct.from_float(ratio * 80.0)

    def stage_breakdown(self) -> StageBreakdown:
        """Split the headline percentage into the five UI bars."""
        return StageBreakdown.from_progress(self.progress_pct)


@dataclass(frozen=True, slots=True)
class StageBreakdown:
    """Per-stage completion, as rendered by the five bars in the project folder.

    Each stage occupies a 20-point band; its bar shows how far through its own
    band the project has travelled.
    """

    foundation_pct: float
    framing_pct: float
    roofing_pct: float
    finishing_pct: float
    approval_pct: float

    @classmethod
    def from_progress(cls, progress: ProgressPct) -> StageBreakdown:
        """Derive the five bars from an overall percentage."""
        total = progress.as_float()

        def band(stage: MacroStage) -> float:
            span = stage.ceiling_pct - stage.floor_pct
            return min(max((total - stage.floor_pct) / span * 100.0, 0.0), 100.0)

        return cls(
            foundation_pct=band(MacroStage.FOUNDATION),
            framing_pct=band(MacroStage.FRAMING),
            roofing_pct=band(MacroStage.ROOFING),
            finishing_pct=band(MacroStage.FINISHING),
            approval_pct=band(MacroStage.APPROVAL),
        )


@dataclass(frozen=True, slots=True)
class ProjectMember:
    """A user's authority on one project (spec B.6 collaboration).

    A ``PENDING`` invitation grants nothing; only ``ACCEPTED`` membership does.
    """

    id: UUID
    project_id: UUID
    user_id: UUID
    membership_role: MembershipRole
    membership_status: MembershipStatus = MembershipStatus.PENDING
    invited_by: UUID | None = None
    invited_at: datetime | None = None
    responded_at: datetime | None = None
    created_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Whether this membership currently confers any permission."""
        return self.membership_status is MembershipStatus.ACCEPTED

    @property
    def is_owner(self) -> bool:
        """Whether this member owns the project."""
        return self.membership_role is MembershipRole.OWNER and self.is_active


@dataclass(frozen=True, slots=True)
class Remark:
    """A note on a project — system-generated or written by a member.

    ``author_id is None`` means the system wrote it (delay detected, camera
    offline, inspection required...).
    """

    id: UUID
    project_id: UUID
    remark_type: RemarkType
    severity: Severity
    message: str
    author_id: UUID | None = None
    is_public: bool = False
    effective_from: date | None = None
    effective_to: date | None = None
    created_at: datetime | None = None

    @property
    def is_system_generated(self) -> bool:
        """Whether this remark was written by the system rather than a person."""
        return self.author_id is None

    def is_in_effect_on(self, day: date) -> bool:
        """Whether a dated remark (e.g. a typhoon window) covers *day*."""
        if self.effective_from and day < self.effective_from:
            return False
        return not (self.effective_to and day > self.effective_to)


@dataclass(frozen=True, slots=True)
class ReferenceAsset:
    """A blueprint, 3-D render, or reference document uploaded by a member.

    Stored, displayed, and included in reports. **Not consumed by the model in
    v1** — see ADR-010.
    """

    id: UUID
    project_id: UUID
    uploaded_by: UUID
    kind: AssetKind
    storage_key: str
    original_filename: str
    mime_type: str
    size_bytes: int
    notes: str | None = None
    is_public: bool = False
    created_at: datetime | None = None
