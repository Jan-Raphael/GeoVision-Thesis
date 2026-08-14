"""Request/response schemas for projects, members, assets, and remarks."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.domain.enums import (
    ApprovalState,
    AssetKind,
    CameraFace,
    DeviceStatus,
    MacroStage,
    MembershipRole,
    MembershipStatus,
    ProfessionalRole,
    ProjectStatus,
    RemarkType,
    Severity,
    Visibility,
)

__all__ = [
    "ApproveProjectRequest",
    "AssetResponse",
    "ContactRequest",
    "CreateProjectRequest",
    "CreateRemarkRequest",
    "InviteMemberRequest",
    "MemberResponse",
    "ProjectFolderResponse",
    "ProjectSummaryResponse",
    "PublicProjectResponse",
    "RemarkResponse",
    "UpdateProjectRequest",
    "VisibilityRequest",
]


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    """The Create Project form from the dashboard spec."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[str, Field(min_length=2, max_length=160, examples=["Jollibee Naga Branch"])]
    code_initials: Annotated[str, Field(min_length=2, max_length=5, examples=["NG"])]
    project_number: Annotated[int, Field(ge=0, le=99, examples=[0])]
    location_label: Annotated[str, Field(min_length=3, max_length=240)]
    latitude: Annotated[float, Field(ge=-90, le=90, examples=[13.6218])]
    longitude: Annotated[float, Field(ge=-180, le=180, examples=[123.1948])]
    start_date: date
    deadline_date: date
    visibility: Visibility = Visibility.PRIVATE
    intended_use: Annotated[str | None, Field(default=None, max_length=160)]
    description: Annotated[str | None, Field(default=None, max_length=4000)]
    # Skippable at creation and editable later, exactly as the spec describes.
    worker_count: Annotated[int | None, Field(default=None, ge=0, le=10_000)]
    timezone: Annotated[str, Field(default="Asia/Manila", max_length=64)]

    @model_validator(mode="after")
    def _deadline_after_start(self) -> Self:
        """Reject an impossible schedule at the edge rather than in the database."""
        if self.deadline_date < self.start_date:
            msg = "The deadline cannot be earlier than the start date."
            raise ValueError(msg)
        return self


class UpdateProjectRequest(BaseModel):
    """Partial project update. ``project_code`` is deliberately absent."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[str | None, Field(default=None, min_length=2, max_length=160)]
    description: Annotated[str | None, Field(default=None, max_length=4000)]
    intended_use: Annotated[str | None, Field(default=None, max_length=160)]
    location_label: Annotated[str | None, Field(default=None, min_length=3, max_length=240)]
    latitude: Annotated[float | None, Field(default=None, ge=-90, le=90)]
    longitude: Annotated[float | None, Field(default=None, ge=-180, le=180)]
    start_date: date | None = None
    deadline_date: date | None = None
    worker_count: Annotated[int | None, Field(default=None, ge=0, le=10_000)]
    timezone: Annotated[str | None, Field(default=None, max_length=64)]


class VisibilityRequest(BaseModel):
    """Publish a project to the public feed, or withdraw it."""

    model_config = ConfigDict(extra="forbid")

    visibility: Visibility


class ApproveProjectRequest(BaseModel):
    """The human sign-off that awards the final 20 % (ADR-007)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    inspection_notes: Annotated[
        str,
        Field(
            min_length=10,
            max_length=4000,
            description="What was found on site. Recorded against your name.",
        ),
    ]


class InviteMemberRequest(BaseModel):
    """Invite somebody to collaborate (spec B.6)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    identifier: Annotated[str, Field(min_length=3, max_length=254, description="Username or email")]
    membership_role: MembershipRole


class ChangeMemberRoleRequest(BaseModel):
    """Change what an existing member may do."""

    model_config = ConfigDict(extra="forbid")

    membership_role: MembershipRole


class InvitationResponseRequest(BaseModel):
    """Accept or decline an invitation."""

    model_config = ConfigDict(extra="forbid")

    accept: bool


class CreateRemarkRequest(BaseModel):
    """Write a note on a project."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    message: Annotated[str, Field(min_length=1, max_length=4000)]
    remark_type: RemarkType = RemarkType.MANUAL
    severity: Severity = Severity.INFO
    is_public: bool = False
    effective_from: date | None = None
    effective_to: date | None = None


class UpdateRemarkRequest(BaseModel):
    """Edit a remark."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    message: Annotated[str | None, Field(default=None, min_length=1, max_length=4000)]
    severity: Severity | None = None
    is_public: bool | None = None


class ContactRequest(BaseModel):
    """The public Contact Us form."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[str, Field(min_length=2, max_length=120)]
    email: EmailStr
    subject: Annotated[str, Field(min_length=3, max_length=200)]
    message: Annotated[str, Field(min_length=10, max_length=4000)]


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class StageBreakdownResponse(BaseModel):
    """The five bars on the project folder page."""

    foundation_pct: float
    framing_pct: float
    roofing_pct: float
    finishing_pct: float
    approval_pct: float


class ProjectSummaryResponse(BaseModel):
    """A project card, used in lists and on profiles."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_code: str
    name: str
    intended_use: str | None = None
    location_label: str
    latitude: float
    longitude: float
    progress_pct: float
    macro_stage: MacroStage | None = None
    status: ProjectStatus
    visibility: Visibility
    deadline_date: date
    last_capture_at: datetime | None = None
    map_url: str


class MemberResponse(BaseModel):
    """One collaborator."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    username: str | None = None
    full_name: str | None = None
    professional_role: ProfessionalRole | None = None
    membership_role: MembershipRole
    membership_status: MembershipStatus
    invited_at: datetime | None = None
    responded_at: datetime | None = None


class DeviceSummaryResponse(BaseModel):
    """A paired camera, as shown in the folder's Devices panel."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_name: str
    face: CameraFace
    status: DeviceStatus
    weight: float
    last_seen_at: datetime | None = None
    last_battery_mv: int | None = None
    last_rssi_dbm: int | None = None


class ImageSummaryResponse(BaseModel):
    """A recent capture with its geotag."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    captured_at: datetime
    latitude: float | None = None
    longitude: float | None = None
    thumb_key: str | None = None
    #: A signed, time-limited URL for the thumbnail. `thumb_key` alone is a
    #: storage key, which no browser can render — every image surface needs
    #: this, so it is produced at the presenter rather than by each caller.
    thumb_url: str | None = None
    device_id: UUID | None = None
    status: str
    map_url: str | None = None


class RemarkResponse(BaseModel):
    """A note on the project."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    remark_type: RemarkType
    severity: Severity
    message: str
    author_id: UUID | None = None
    is_system_generated: bool = False
    is_public: bool = False
    effective_from: date | None = None
    effective_to: date | None = None
    created_at: datetime | None = None


class AssetResponse(BaseModel):
    """A blueprint, render, or reference document."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: AssetKind
    original_filename: str
    mime_type: str
    size_bytes: int
    notes: str | None = None
    is_public: bool = False
    created_at: datetime | None = None
    download_url: str | None = None


class TimelinePointResponse(BaseModel):
    """One point on the progress chart."""

    window_start: datetime
    displayed_pct: float
    macro_stage: MacroStage


class ProjectFolderResponse(BaseModel):
    """Everything the project folder page renders."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_code: str
    name: str
    intended_use: str | None = None
    description: str | None = None
    location_label: str
    latitude: float
    longitude: float
    map_url: str
    osm_url: str

    start_date: date
    deadline_date: date
    days_remaining: int
    worker_count: int | None = None
    timezone: str

    visibility: Visibility
    status: ProjectStatus
    status_reason: str
    approval_state: ApprovalState
    progress_pct: float
    expected_pct: float
    macro_stage: MacroStage | None = None
    stages: StageBreakdownResponse

    owner: MemberResponse | None = None
    members: list[MemberResponse] = Field(default_factory=list)
    devices: list[DeviceSummaryResponse] = Field(default_factory=list)
    recent_images: list[ImageSummaryResponse] = Field(default_factory=list)
    remarks: list[RemarkResponse] = Field(default_factory=list)
    assets: list[AssetResponse] = Field(default_factory=list)
    timeline: list[TimelinePointResponse] = Field(default_factory=list)

    last_capture_at: datetime | None = None
    completed_at: datetime | None = None
    approved_at: datetime | None = None
    inspection_notes: str | None = None

    #: What *this caller* may do. The dashboard shows and hides controls from
    #: this rather than re-deriving authority client-side. Hiding a button is
    #: presentation, not security: the API enforces the same rules regardless.
    permissions: dict[str, bool] = Field(default_factory=dict)


class PublicProjectResponse(BaseModel):
    """The anonymous view of a project folder.

    A separate model from :class:`ProjectFolderResponse` on purpose: anything
    not listed here physically cannot reach an anonymous caller, even if a
    future field is added to the internal one.
    """

    model_config = ConfigDict(from_attributes=True)

    project_code: str
    name: str
    intended_use: str | None = None
    description: str | None = None
    location_label: str
    latitude: float
    longitude: float
    map_url: str
    osm_url: str

    start_date: date
    deadline_date: date
    status: ProjectStatus
    status_reason: str
    progress_pct: float
    macro_stage: MacroStage | None = None
    stages: StageBreakdownResponse

    handler_username: str | None = None
    handler_name: str | None = None
    handler_is_public: bool = False

    recent_images: list[ImageSummaryResponse] = Field(default_factory=list)
    remarks: list[RemarkResponse] = Field(default_factory=list)
    timeline: list[TimelinePointResponse] = Field(default_factory=list)
    last_capture_at: datetime | None = None
