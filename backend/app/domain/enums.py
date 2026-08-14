"""Every enumeration in the GeoVision domain.

**This is the single definition site.** SQLAlchemy models, Pydantic schemas, the
Alembic migration, and the frontend's generated types all derive from here. An
enum defined twice is an enum that will eventually disagree with itself.

Values are lowercase ``snake_case`` strings, matching the wire format in
``GeoVision-Vault/04-API/API-Contract.md`` and the PostgreSQL native enum
labels. Because these are :class:`~enum.StrEnum`, a member compares equal to its
string value, so serialisation is free.

.. warning::
   Enum **values** are persisted in the database. Renaming one requires a data
   migration. Adding a member requires ``ALTER TYPE ... ADD VALUE``. Reordering
   is meaningless to PostgreSQL but breaks nothing; changing a spelling breaks
   everything.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ApprovalState",
    "AssetKind",
    "CameraFace",
    "DeviceStatus",
    "ImageSource",
    "ImageStatus",
    "MacroStage",
    "MembershipRole",
    "MembershipStatus",
    "ModelKind",
    "NotificationType",
    "Permission",
    "ProfessionalRole",
    "ProjectStatus",
    "RemarkType",
    "ReportFormat",
    "ReportKind",
    "ReportStatus",
    "Severity",
    "Visibility",
]


class ProfessionalRole(StrEnum):
    """What a user *is*, declared at registration.

    Descriptive only — it grants no permissions. Authorization comes from
    :class:`MembershipRole` on a specific project. See
    ``GeoVision-Vault/02-Domain/Roles-and-Permissions.md``.
    """

    MANAGER = "manager"
    PROJECT_HANDLER = "project_handler"
    ENGINEER = "engineer"
    ARCHITECT = "architect"
    FOREMAN = "foreman"
    CONTRACTOR = "contractor"
    SURVEYOR = "surveyor"
    HOME_OWNER = "home_owner"
    STUDENT = "student"
    OTHER = "other"


class Visibility(StrEnum):
    """Public/private flag for a project or a user profile."""

    PUBLIC = "public"
    PRIVATE = "private"


class ProjectStatus(StrEnum):
    """Derived project state — never set by hand except ``ARCHIVED``.

    Derivation rules: ``GeoVision-Vault/02-Domain/Project-Status-Rules.md``.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    DELAYED = "delayed"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ApprovalState(StrEnum):
    """Progress of the human inspection that awards the final 20 % (ADR-007)."""

    NOT_READY = "not_ready"
    AWAITING_INSPECTION = "awaiting_inspection"
    APPROVED = "approved"


class MembershipRole(StrEnum):
    """A user's authority **on one project**. This is what grants permissions.

    Ordered loosely from most to least privileged, though authority is defined
    by :data:`~app.domain.services.authorization.ROLE_PERMISSIONS`, not by
    ordering.
    """

    OWNER = "owner"
    MANAGER = "manager"
    ENGINEER = "engineer"
    EDITOR = "editor"
    COLLABORATOR = "collaborator"
    EMPLOYEE = "employee"
    VIEWER = "viewer"


class MembershipStatus(StrEnum):
    """Lifecycle of a collaboration invitation.

    A ``PENDING`` member has **no** permissions until they accept.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class CameraFace(StrEnum):
    """Which face(s) of the building a camera observes.

    Diagonal placements see two façades and therefore carry a higher default
    aggregation weight — see ``Progress-Calculation.md``.
    """

    FRONT = "front"
    FRONT_DIAGONAL = "front_diagonal"
    BACK = "back"
    BACK_DIAGONAL = "back_diagonal"

    @property
    def code(self) -> str:
        """Short token used in the device name, e.g. ``ESP_NG_00_FD``."""
        return {
            CameraFace.FRONT: "F",
            CameraFace.FRONT_DIAGONAL: "FD",
            CameraFace.BACK: "B",
            CameraFace.BACK_DIAGONAL: "BD",
        }[self]

    @property
    def faces_observed(self) -> int:
        """Number of building façades visible from this placement."""
        return 2 if self in {CameraFace.FRONT_DIAGONAL, CameraFace.BACK_DIAGONAL} else 1

    @property
    def default_weight(self) -> float:
        """Default aggregation weight, proportional to façades observed."""
        return 1.5 if self.faces_observed == 2 else 1.0


class DeviceStatus(StrEnum):
    """Lifecycle and liveness of a paired ESP32-CAM node."""

    UNPAIRED = "unpaired"
    PAIRED = "paired"
    ONLINE = "online"
    OFFLINE = "offline"
    REVOKED = "revoked"


class ImageSource(StrEnum):
    """How an image entered the system."""

    DEVICE = "device"
    MANUAL_UPLOAD = "manual_upload"
    BACKFILL = "backfill"


class ImageStatus(StrEnum):
    """Position of an image in the processing pipeline."""

    PENDING = "pending"
    PREPROCESSED = "preprocessed"
    INFERRED = "inferred"
    REJECTED = "rejected"
    FAILED = "failed"


class MacroStage(StrEnum):
    """The five stages shown in the UI (ADR-001).

    The classifier predicts ten *fine* classes; this is the coarse business
    view. ``APPROVAL`` is never predicted — it is reached only by human
    sign-off.
    """

    FOUNDATION = "foundation"
    FRAMING = "framing"
    ROOFING = "roofing"
    FINISHING = "finishing"
    APPROVAL = "approval"

    @property
    def floor_pct(self) -> float:
        """Lower bound of this stage's progress band."""
        return {
            MacroStage.FOUNDATION: 0.0,
            MacroStage.FRAMING: 20.0,
            MacroStage.ROOFING: 40.0,
            MacroStage.FINISHING: 60.0,
            MacroStage.APPROVAL: 80.0,
        }[self]

    @property
    def ceiling_pct(self) -> float:
        """Upper bound of this stage's progress band."""
        return self.floor_pct + 20.0

    @property
    def order(self) -> int:
        """Zero-based position in the construction sequence."""
        return int(self.floor_pct // 20)


class AssetKind(StrEnum):
    """Type of a user-uploaded reference file.

    In v1 these are stored and displayed but **not** consumed by the model
    (ADR-010).
    """

    BLUEPRINT = "blueprint"
    RENDER_3D = "render_3d"
    REFERENCE_PHOTO = "reference_photo"
    DOCUMENT = "document"
    INSPECTION_PHOTO = "inspection_photo"


class RemarkType(StrEnum):
    """Origin/category of a project remark."""

    SYSTEM = "system"
    WEATHER = "weather"
    DELAY = "delay"
    INACTIVITY = "inactivity"
    MANUAL = "manual"
    REGRESSION = "regression"


class Severity(StrEnum):
    """How loudly a remark or notification should present itself."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ReportKind(StrEnum):
    """Reporting period."""

    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class ReportFormat(StrEnum):
    """Output format of a generated report."""

    PDF = "pdf"
    CSV = "csv"


class ReportStatus(StrEnum):
    """Lifecycle of an asynchronous report job."""

    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ModelKind(StrEnum):
    """Category of a registered AI model."""

    CLASSIFIER = "classifier"
    DETECTOR = "detector"


class NotificationType(StrEnum):
    """Why a user is being notified."""

    INSPECTION_REQUIRED = "inspection_required"
    DELAY = "delay"
    DEVICE_OFFLINE = "device_offline"
    COLLAB_INVITE = "collab_invite"
    REPORT_READY = "report_ready"
    REGRESSION = "regression"
    LOW_BATTERY = "low_battery"


class Permission(StrEnum):
    """Named capabilities checked by the authorization layer (Module 03).

    Defined here so the domain has one vocabulary for authority, and so the
    permission matrix in ``Roles-and-Permissions.md`` maps one-to-one onto code.
    """

    PROJECT_VIEW = "project:view"
    PROJECT_EDIT = "project:edit"
    PROJECT_DELETE = "project:delete"
    PROJECT_VISIBILITY = "project:visibility"
    PROJECT_APPROVE = "project:approve"
    MEMBER_MANAGE = "member:manage"
    DEVICE_MANAGE = "device:manage"
    ASSET_UPLOAD = "asset:upload"
    IMAGE_UPLOAD = "image:upload"
    REMARK_WRITE = "remark:write"
    REPORT_GENERATE = "report:generate"
    #: Re-run the AI over already-stored data: reprocess one image, or rebuild a
    #: project's whole progress timeline. Separate from ``PROJECT_EDIT`` because
    #: it rewrites the headline figure the project is judged on rather than its
    #: descriptive fields, and the API contract puts it at manager+ (ADR-026).
    PROGRESS_RECOMPUTE = "progress:recompute"
