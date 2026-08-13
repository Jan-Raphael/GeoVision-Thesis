"""SQLAlchemy ORM models — the physical schema.

Mirrors ``GeoVision-Vault/02-Domain/Domain-Model.md``. Enum *values* come from
``app.domain.enums`` so the database labels and the Python members can never
drift apart.

Conventions applied throughout:

* UUID v4 primary keys, generated server-side by ``gen_random_uuid()``.
* ``TIMESTAMPTZ`` everywhere; the application never stores naive datetimes.
* Percentages ``numeric(5,2)`` in 0-100; confidences ``numeric(4,3)`` in 0-1.
* ``ondelete="CASCADE"`` from a project to everything it owns; ``RESTRICT``
  from users, because a user with projects is deactivated rather than deleted.
* Check constraints encode invariants the application also enforces. Belt and
  braces: application code has bugs, and a database that permits a 300 %
  progress value will eventually contain one.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain import enums
from app.infrastructure.db.base import Base, TimestampMixin, uuid_pk

# ---------------------------------------------------------------------------
# Enum type factory
#
# native_enum=True gives real PostgreSQL enum types (self-documenting in psql,
# and a typo becomes a database error rather than a silently stored string).
# values_callable persists the StrEnum *values* ("front_diagonal"), not the
# Python member names ("FRONT_DIAGONAL") - the values are the wire format.
# ---------------------------------------------------------------------------


def pg_enum(enum_cls: type, name: str) -> SAEnum:
    """Build a native PostgreSQL enum type from a Python enum."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        create_type=True,
        values_callable=lambda e: [member.value for member in e],
    )


# ---------------------------------------------------------------------------
# Users & sessions
# ---------------------------------------------------------------------------


class UserModel(Base, TimestampMixin):
    """A registered account."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    professional_role: Mapped[enums.ProfessionalRole] = mapped_column(
        pg_enum(enums.ProfessionalRole, "professional_role"), nullable=False
    )
    profile_visibility: Mapped[enums.Visibility] = mapped_column(
        pg_enum(enums.Visibility, "visibility"),
        nullable=False,
        server_default=enums.Visibility.PUBLIC.value,
    )
    company: Mapped[str | None] = mapped_column(String(160))
    bio: Mapped[str | None] = mapped_column(Text)
    avatar_key: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owned_projects: Mapped[list[ProjectModel]] = relationship(
        back_populates="owner", foreign_keys="ProjectModel.owner_id"
    )
    memberships: Mapped[list[ProjectMemberModel]] = relationship(
        back_populates="user",
        foreign_keys="ProjectMemberModel.user_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("char_length(username) BETWEEN 3 AND 30", name="username_length"),
        CheckConstraint("position('@' in email) > 1", name="email_shape"),
        # Trigram index powering the public user search.
        Index(
            "ix_users_username_trgm",
            "username",
            postgresql_using="gin",
            postgresql_ops={"username": "gin_trgm_ops"},
        ),
        Index(
            "ix_users_full_name_trgm",
            "full_name",
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
    )


class RefreshTokenModel(Base):
    """A rotating refresh token; only the hash is stored."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Reusing a rotated token revokes the whole family, on the assumption the
    # token was stolen.
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_refresh_tokens_user_id_family_id", "user_id", "family_id"),
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


class ProjectModel(Base, TimestampMixin):
    """A construction project — the dashboard's "project folder"."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # Immutable after creation: embedded in device names and image filenames.
    project_code: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    intended_use: Mapped[str | None] = mapped_column(String(160))
    location_label: Mapped[str] = mapped_column(String(240), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    deadline_date: Mapped[date] = mapped_column(Date, nullable=False)
    worker_count: Mapped[int | None] = mapped_column(Integer)
    visibility: Mapped[enums.Visibility] = mapped_column(
        pg_enum(enums.Visibility, "visibility"),
        nullable=False,
        server_default=enums.Visibility.PRIVATE.value,
    )
    status: Mapped[enums.ProjectStatus] = mapped_column(
        pg_enum(enums.ProjectStatus, "project_status"),
        nullable=False,
        server_default=enums.ProjectStatus.ACTIVE.value,
    )
    approval_state: Mapped[enums.ApprovalState] = mapped_column(
        pg_enum(enums.ApprovalState, "approval_state"),
        nullable=False,
        server_default=enums.ApprovalState.NOT_READY.value,
    )
    # Denormalised copy of the newest snapshot, so project lists render without
    # touching project_progress_snapshots.
    progress_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    macro_stage: Mapped[enums.MacroStage | None] = mapped_column(
        pg_enum(enums.MacroStage, "macro_stage")
    )
    window_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="daily")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Manila")
    last_capture_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inspection_notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[UserModel] = relationship(
        back_populates="owned_projects", foreign_keys=[owner_id]
    )
    members: Mapped[list[ProjectMemberModel]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    devices: Mapped[list[DeviceModel]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    images: Mapped[list[ImageModel]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("project_code ~ '^[A-Z]{2,5}_[0-9]{2}$'", name="project_code_format"),
        CheckConstraint("deadline_date >= start_date", name="deadline_after_start"),
        CheckConstraint("progress_pct BETWEEN 0 AND 100", name="progress_range"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        CheckConstraint(
            "worker_count IS NULL OR worker_count >= 0", name="worker_count_non_negative"
        ),
        CheckConstraint("window_mode IN ('daily','weekly')", name="window_mode_valid"),
        # A project is only 100% complete once a human approved it (ADR-007).
        CheckConstraint(
            "progress_pct <= 80 OR approval_state = 'approved'",
            name="machine_ceiling_requires_approval",
        ),
        Index("ix_projects_visibility_status", "visibility", "status"),
        Index("ix_projects_owner_id", "owner_id"),
        Index("ix_projects_latitude_longitude", "latitude", "longitude"),
        Index(
            "ix_projects_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_projects_location_label_trgm",
            "location_label",
            postgresql_using="gin",
            postgresql_ops={"location_label": "gin_trgm_ops"},
        ),
    )


class ProjectMemberModel(Base):
    """A user's authority on one project (collaboration, spec B.6)."""

    __tablename__ = "project_members"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    membership_role: Mapped[enums.MembershipRole] = mapped_column(
        pg_enum(enums.MembershipRole, "membership_role"), nullable=False
    )
    membership_status: Mapped[enums.MembershipStatus] = mapped_column(
        pg_enum(enums.MembershipStatus, "membership_status"),
        nullable=False,
        server_default=enums.MembershipStatus.PENDING.value,
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    project: Mapped[ProjectModel] = relationship(back_populates="members")
    user: Mapped[UserModel] = relationship(back_populates="memberships", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        Index("ix_project_members_user_id_status", "user_id", "membership_status"),
    )


class RemarkModel(Base):
    """A note on a project; ``author_id IS NULL`` means system-generated."""

    __tablename__ = "remarks"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    remark_type: Mapped[enums.RemarkType] = mapped_column(
        pg_enum(enums.RemarkType, "remark_type"), nullable=False
    )
    severity: Mapped[enums.Severity] = mapped_column(
        pg_enum(enums.Severity, "severity"),
        nullable=False,
        server_default=enums.Severity.INFO.value,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="effective_range_valid",
        ),
        Index("ix_remarks_project_id_created_at", "project_id", "created_at"),
    )


class ReferenceAssetModel(Base):
    """Blueprint / 3-D render / reference document (stored, not modelled)."""

    __tablename__ = "reference_assets"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[enums.AssetKind] = mapped_column(
        pg_enum(enums.AssetKind, "asset_kind"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_reference_assets_project_id", "project_id"),
    )


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


class DeviceModel(Base, TimestampMixin):
    """A paired ESP32-CAM node."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_name: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    face: Mapped[enums.CameraFace] = mapped_column(
        pg_enum(enums.CameraFace, "camera_face"), nullable=False
    )
    weight: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, server_default=text("1.0")
    )
    # Only the hash: the plaintext secret is shown once, at pairing.
    secret_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[enums.DeviceStatus] = mapped_column(
        pg_enum(enums.DeviceStatus, "device_status"),
        nullable=False,
        server_default=enums.DeviceStatus.PAIRED.value,
    )
    firmware_version: Mapped[str | None] = mapped_column(String(32))
    hardware_id: Mapped[str | None] = mapped_column(String(64))
    capture_schedule: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text('\'{"times": ["07:00", "16:00"], "timezone": "Asia/Manila"}\'::jsonb'),
    )
    homography: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    roi_polygon: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_battery_mv: Mapped[int | None] = mapped_column(Integer)
    last_rssi_dbm: Mapped[int | None] = mapped_column(Integer)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[ProjectModel] = relationship(back_populates="devices")
    images: Mapped[list[ImageModel]] = relationship(back_populates="device")

    __table_args__ = (
        # One camera per face; a second one requires an explicit override.
        UniqueConstraint("project_id", "face", name="uq_devices_project_face"),
        CheckConstraint("weight > 0 AND weight <= 5", name="weight_range"),
        CheckConstraint(
            "device_name ~ '^ESP_[A-Z]{2,5}_[0-9]{2}_(F|FD|B|BD)[0-9]?$'",
            name="device_name_format",
        ),
        Index("ix_devices_project_id", "project_id"),
        Index("ix_devices_status_last_seen_at", "status", "last_seen_at"),
    )


class PairingTokenModel(Base):
    """A single-use, 15-minute code that binds a camera to a project."""

    __tablename__ = "pairing_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    face: Mapped[enums.CameraFace] = mapped_column(
        pg_enum(enums.CameraFace, "camera_face"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_device_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_pairing_tokens_project_id_expires_at", "project_id", "expires_at"),)


class DeviceEventModel(Base):
    """Device telemetry: boot, heartbeat, upload, error, sleep."""

    __tablename__ = "device_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    device_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    battery_mv: Mapped[int | None] = mapped_column(Integer)
    rssi_dbm: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_device_events_device_id_created_at", "device_id", "created_at"),)


# ---------------------------------------------------------------------------
# Images, predictions, detections
# ---------------------------------------------------------------------------


class ImageModel(Base):
    """One captured frame."""

    __tablename__ = "images"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    preprocessed_key: Mapped[str | None] = mapped_column(Text)
    thumb_key: Mapped[str | None] = mapped_column(Text)
    source: Mapped[enums.ImageSource] = mapped_column(
        pg_enum(enums.ImageSource, "image_source"),
        nullable=False,
        server_default=enums.ImageSource.DEVICE.value,
    )
    status: Mapped[enums.ImageStatus] = mapped_column(
        pg_enum(enums.ImageStatus, "image_status"),
        nullable=False,
        server_default=enums.ImageStatus.PENDING.value,
    )
    # Device clock (GPS/RTC). Aggregation windows key on this, so a backlog
    # upload lands in the window it was taken in.
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    seq_number: Mapped[int | None] = mapped_column(Integer)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    gps_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    altitude_m: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    satellites: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    exif: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    quality_flags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    project: Mapped[ProjectModel] = relationship(back_populates="images")
    device: Mapped[DeviceModel | None] = relationship(back_populates="images")
    prediction: Mapped[PredictionModel | None] = relationship(
        back_populates="image", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        # Ingest idempotency: a re-delivered upload after a lost ACK must not
        # create a second row.
        UniqueConstraint("project_id", "sha256", name="uq_images_project_sha256"),
        CheckConstraint("char_length(sha256) = 64", name="sha256_length"),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name="longitude_range"
        ),
        Index("ix_images_project_id_captured_at", "project_id", "captured_at"),
        Index("ix_images_device_id_captured_at", "device_id", "captured_at"),
        Index("ix_images_status", "status"),
    )


class PredictionModel(Base):
    """The classifier's verdict on one image."""

    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = uuid_pk()
    image_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ai_models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    fine_class_index: Mapped[int] = mapped_column(Integer, nullable=False)
    fine_class: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    macro_stage: Mapped[enums.MacroStage] = mapped_column(
        pg_enum(enums.MacroStage, "macro_stage"), nullable=False
    )
    raw_progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    is_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    low_confidence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    class_probabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    inference_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    image: Mapped[ImageModel] = relationship(back_populates="prediction")

    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("raw_progress_pct BETWEEN 0 AND 100", name="progress_range"),
        CheckConstraint("fine_class_index BETWEEN 0 AND 9", name="fine_class_index_range"),
        Index("ix_predictions_macro_stage", "macro_stage"),
    )


class DetectionModel(Base):
    """One object found by the detector; coordinates are normalised."""

    __tablename__ = "detections"

    id: Mapped[uuid.UUID] = uuid_pk()
    image_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ai_models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    class_name: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    bbox_x: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    bbox_y: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    bbox_w: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    bbox_h: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint(
            "bbox_x BETWEEN 0 AND 1 AND bbox_y BETWEEN 0 AND 1 "
            "AND bbox_w > 0 AND bbox_w <= 1 AND bbox_h > 0 AND bbox_h <= 1",
            name="bbox_normalised",
        ),
        Index("ix_detections_image_id", "image_id"),
        Index("ix_detections_class_name", "class_name"),
    )


class DetectionSummaryModel(Base):
    """Aggregate object counts for one image."""

    __tablename__ = "detection_summaries"

    id: Mapped[uuid.UUID] = uuid_pk()
    image_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    total_objects: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    inference_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (CheckConstraint("total_objects >= 0", name="total_objects_non_negative"),)


class ProgressSnapshotModel(Base):
    """Aggregated progress for one project over one window.

    **This table is the timeline graph.**
    """

    __tablename__ = "project_progress_snapshots"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    ema_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    displayed_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    macro_stage: Mapped[enums.MacroStage] = mapped_column(
        pg_enum(enums.MacroStage, "macro_stage"), nullable=False
    )
    foundation_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    framing_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    roofing_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    finishing_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    approval_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    eligible_image_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    contributing_image_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    )
    device_weights: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Records which version of the aggregation rules produced this row, so the
    # timeline stays reproducible after the algorithm changes.
    algorithm_version: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="progress-v1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("project_id", "window_start", name="uq_snapshots_project_window"),
        CheckConstraint("window_end > window_start", name="window_ordered"),
        CheckConstraint(
            "raw_pct BETWEEN 0 AND 100 AND ema_pct BETWEEN 0 AND 100 "
            "AND displayed_pct BETWEEN 0 AND 100",
            name="percentages_range",
        ),
        Index(
            "ix_snapshots_project_id_window_start",
            "project_id",
            "window_start",
        ),
    )


# ---------------------------------------------------------------------------
# Reports, models, notifications, audit
# ---------------------------------------------------------------------------


class ReportModel(Base):
    """An asynchronously generated PDF/CSV export."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[enums.ReportKind] = mapped_column(
        pg_enum(enums.ReportKind, "report_kind"), nullable=False
    )
    report_format: Mapped[enums.ReportFormat] = mapped_column(
        pg_enum(enums.ReportFormat, "report_format"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[enums.ReportStatus] = mapped_column(
        pg_enum(enums.ReportStatus, "report_status"),
        nullable=False,
        server_default=enums.ReportStatus.QUEUED.value,
    )
    storage_key: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("period_end >= period_start", name="period_ordered"),
        Index("ix_reports_project_id_requested_at", "project_id", "requested_at"),
    )


class AIModelModel(Base):
    """A registered trained model, powering ``GET /model/status``."""

    __tablename__ = "ai_models"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[enums.ModelKind] = mapped_column(
        pg_enum(enums.ModelKind, "model_kind"), nullable=False
    )
    architecture: Mapped[str] = mapped_column(String(48), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    framework: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pytorch")
    weights_key: Mapped[str | None] = mapped_column(Text)
    class_names: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    input_size: Mapped[int | None] = mapped_column(Integer)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_ai_models_name_version"),
        # Exactly one active model per kind, enforced by a partial unique index.
        Index(
            "uq_ai_models_active_per_kind",
            "kind",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


class NotificationModel(Base):
    """An in-app message to a user."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    notification_type: Mapped[enums.NotificationType] = mapped_column(
        pg_enum(enums.NotificationType, "notification_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_notifications_user_id_read_at", "user_id", "read_at"),)


class ContactMessageModel(Base):
    """A message from the public Contact Us form.

    Persisted rather than emailed: v1 has no mail delivery (see
    ``Open-Questions``), and a contact form that drops messages on the floor is
    a broken feature, not a deferred one. The owner reads them from the
    database until delivery exists.
    """

    __tablename__ = "contact_messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Recorded for abuse triage; the form is public and rate-limited.
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("char_length(message) >= 10", name="message_min_length"),
        Index("ix_contact_messages_created_at_handled_at", "created_at", "handled_at"),
    )


class AuditLogModel(Base):
    """A security-relevant action, retained for accountability."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_device_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    audit_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_audit_logs_entity_type_entity_id", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor_user_id_created_at", "actor_user_id", "created_at"),
    )
