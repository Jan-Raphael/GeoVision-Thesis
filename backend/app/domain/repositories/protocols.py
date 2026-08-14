"""Repository interfaces, one per aggregate.

Concrete implementations live in ``app.infrastructure.repositories``. Use cases
depend only on what is declared here, so a test can inject an in-memory fake
without a database.

.. important::
   The visibility-scoped methods (``list_public_feed``, ``get_public_by_code``,
   ``get_public_profile``) exist because privacy is enforced **in SQL**, not by
   filtering after the fact. A public endpoint calls one of these and therefore
   *cannot* select a private row, even if a later refactor forgets a check. See
   ``Domain-Model.md`` §Visibility enforcement.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    AIModel,
    ContactMessage,
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
from app.domain.enums import (
    CameraFace,
    ImageStatus,
    MembershipRole,
    ModelKind,
    ProjectStatus,
)
from app.domain.repositories.base import Page
from app.domain.value_objects import ProjectCode

__all__ = [
    "AIModelRepository",
    "ContactMessageRepository",
    "DeviceRepository",
    "ImageRepository",
    "NotificationRepository",
    "PairingTokenRepository",
    "PredictionRepository",
    "ProjectMemberRepository",
    "ProjectRepository",
    "ReferenceAssetRepository",
    "RefreshTokenRepository",
    "RemarkRepository",
    "ReportRepository",
    "SnapshotRepository",
    "UserRepository",
]


class UserRepository(Protocol):
    """Accounts and profiles."""

    async def get(self, user_id: UUID) -> User | None:
        """Return a user by id."""
        ...

    async def get_by_username(self, username: str) -> User | None:
        """Return a user by username (case-insensitive)."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by email (case-insensitive)."""
        ...

    async def get_by_identifier(self, identifier: str) -> User | None:
        """Return a user by username **or** email — the login form's single field."""
        ...

    async def get_public_profile(self, username: str) -> User | None:
        """Return a user only if their profile is public and active.

        Returns ``None`` for a private account, so the caller renders the
        "this account is private" state without ever holding private data.
        """
        ...

    async def username_exists(self, username: str) -> bool:
        """Whether a username is taken — drives the live registration check."""
        ...

    async def email_exists(self, email: str) -> bool:
        """Whether an email is already registered."""
        ...

    async def search(self, query: str, *, limit: int = 20) -> tuple[User, ...]:
        """Fuzzy search public profiles by username or full name."""
        ...

    async def add(self, user: User, password_hash: str) -> User:
        """Create a new account."""
        ...

    async def update(self, user: User) -> User:
        """Persist profile changes."""
        ...

    async def get_password_hash(self, user_id: UUID) -> str | None:
        """Return the stored password hash.

        Deliberately separate from :class:`~app.domain.entities.User`, which
        carries no credential material — an entity that cannot hold a hash
        cannot accidentally serialise one.
        """
        ...

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None:
        """Replace the stored password hash.

        Used to transparently upgrade a hash made with weaker Argon2
        parameters, so raising the cost never forces a password reset.
        """
        ...


class RefreshTokenRepository(Protocol):
    """Rotating refresh tokens."""

    async def add(self, token: RefreshToken) -> RefreshToken:
        """Store a new token (hash only)."""
        ...

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Look up a token by its hash."""
        ...

    async def revoke(self, token_id: UUID, *, revoked_at: datetime) -> bool:
        """Revoke a single token. Used to burn a token on rotation."""
        ...

    async def revoke_family(self, family_id: UUID) -> int:
        """Revoke every token in a family; returns how many were revoked.

        Called when a rotated token is presented again, which indicates theft.
        """
        ...

    async def delete_expired(self, before: datetime) -> int:
        """Purge expired tokens; returns how many were removed."""
        ...


class ProjectRepository(Protocol):
    """Projects — including the visibility-scoped public reads."""

    async def get(self, project_id: UUID) -> Project | None:
        """Return a project by id, regardless of visibility."""
        ...

    async def get_by_code(self, code: ProjectCode) -> Project | None:
        """Return a project by its code, regardless of visibility."""
        ...

    async def get_public_by_code(self, code: ProjectCode) -> Project | None:
        """Return a project **only if it is public and not archived**.

        Anonymous project reads must go through this. Returning ``None`` lets
        the API answer 404 rather than 403, so the existence of a private
        project is never disclosed.
        """
        ...

    async def list_public_feed(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        stage: str | None = None,
        status: ProjectStatus | None = None,
        query: str | None = None,
    ) -> Page[Project]:
        """Homepage feed — public, non-archived projects only."""
        ...

    async def list_for_user(
        self, user_id: UUID, *, status: ProjectStatus | None = None
    ) -> tuple[Project, ...]:
        """Projects the user owns or is an accepted member of."""
        ...

    async def list_public_for_user(self, user_id: UUID) -> tuple[Project, ...]:
        """Public projects shown on a user's public profile."""
        ...

    async def code_exists(self, code: ProjectCode) -> bool:
        """Whether a project code is already taken (globally unique)."""
        ...

    async def search(self, query: str, *, limit: int = 20) -> tuple[Project, ...]:
        """Fuzzy search public projects by name or location."""
        ...

    async def add(self, project: Project) -> Project:
        """Create a project."""
        ...

    async def update(self, project: Project) -> Project:
        """Persist project changes."""
        ...

    async def delete(self, project_id: UUID) -> bool:
        """Delete a project and everything it owns."""
        ...


class ProjectMemberRepository(Protocol):
    """Collaboration membership (spec B.6)."""

    async def get(self, member_id: UUID) -> ProjectMember | None:
        """Return a membership row by id."""
        ...

    async def get_membership(self, project_id: UUID, user_id: UUID) -> ProjectMember | None:
        """Return a user's membership of a project, if any.

        The authorization layer's primary query: a caller with no accepted
        membership has no permissions on the project.
        """
        ...

    async def list_for_project(self, project_id: UUID) -> tuple[ProjectMember, ...]:
        """All memberships of a project, including pending invitations."""
        ...

    async def list_pending_for_user(self, user_id: UUID) -> tuple[ProjectMember, ...]:
        """Invitations awaiting the user's response."""
        ...

    async def add(self, member: ProjectMember) -> ProjectMember:
        """Create a membership or invitation."""
        ...

    async def update(self, member: ProjectMember) -> ProjectMember:
        """Change a membership's role or status."""
        ...

    async def delete(self, member_id: UUID) -> bool:
        """Remove a membership."""
        ...

    async def count_by_role(self, project_id: UUID, role: MembershipRole) -> int:
        """How many members hold *role* — used to stop removing the last owner."""
        ...


class DeviceRepository(Protocol):
    """Paired ESP32-CAM nodes."""

    async def get(self, device_id: UUID) -> Device | None:
        """Return a device by id."""
        ...

    async def get_by_name(self, device_name: str) -> Device | None:
        """Return a device by its derived name, e.g. ``ESP_NG_00_FD``."""
        ...

    async def list_for_project(self, project_id: UUID) -> tuple[Device, ...]:
        """Every device paired to a project."""
        ...

    async def face_taken(self, project_id: UUID, face: CameraFace) -> bool:
        """Whether a project already has a camera on *face*."""
        ...

    async def get_secret(self, device_id: UUID, encryption_key: str) -> str | None:
        """Return the device's decrypted HMAC secret, or ``None``.

        Encrypted rather than hashed at rest: verifying an HMAC requires the key
        itself, not a digest of it (ADR-020).
        """
        ...

    async def list_stale(self, since: datetime) -> tuple[Device, ...]:
        """Devices not seen since *since* — drives the offline sweep."""
        ...

    async def add(self, device: Device, secret_encrypted: str) -> Device:
        """Create a device at pairing time."""
        ...

    async def update(self, device: Device) -> Device:
        """Persist device settings or telemetry."""
        ...

    async def record_heartbeat(
        self,
        device_id: UUID,
        *,
        seen_at: datetime,
        battery_mv: int | None = None,
        rssi_dbm: int | None = None,
    ) -> None:
        """Update liveness fields without loading the whole entity."""
        ...

    async def revoke(self, device_id: UUID, revoked_at: datetime) -> bool:
        """Unpair a device: mark it revoked and wipe its stored secret.

        Historical images are deliberately kept - swapping failed hardware must
        not rewrite a project's progress history.
        """
        ...


class PairingTokenRepository(Protocol):
    """Single-use pairing codes."""

    async def add(self, token: PairingToken) -> PairingToken:
        """Issue a token (hash only is stored)."""
        ...

    async def get_by_hash(self, token_hash: str) -> PairingToken | None:
        """Look up a token by the hash of its display code."""
        ...

    async def mark_used(self, token_id: UUID, device_id: UUID, used_at: datetime) -> None:
        """Consume the token, binding it to the device that claimed it."""
        ...

    async def delete_expired(self, before: datetime) -> int:
        """Purge expired, unused tokens."""
        ...


class ImageRepository(Protocol):
    """Captured frames."""

    async def get(self, image_id: UUID) -> Image | None:
        """Return an image by id."""
        ...

    async def get_by_hash(self, project_id: UUID, sha256: str) -> Image | None:
        """Look up by content hash — the ingest idempotency check."""
        ...

    async def list_for_project(
        self,
        project_id: UUID,
        *,
        limit: int = 50,
        cursor: str | None = None,
        device_id: UUID | None = None,
        status: ImageStatus | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Page[Image]:
        """Paginated image feed for a project."""
        ...

    async def list_in_window(
        self, project_id: UUID, start: datetime, end: datetime
    ) -> tuple[Image, ...]:
        """Images captured in ``[start, end)`` — the aggregation input."""
        ...

    async def latest_for_project(self, project_id: UUID) -> Image | None:
        """The most recent capture, shown on the public feed card."""
        ...

    async def next_sequence_number(self, project_id: UUID, day: date) -> int:
        """Allocate the next daily sequence number for a filename.

        Implementations must be race-free — concurrent uploads from several
        cameras must not receive the same number.
        """
        ...

    async def add(self, image: Image) -> Image:
        """Record an ingested image."""
        ...

    async def update(self, image: Image) -> Image:
        """Persist status or derived-key changes."""
        ...

    async def delete(self, image_id: UUID) -> bool:
        """Delete an image and its prediction/detections."""
        ...


class PredictionRepository(Protocol):
    """Classifier outputs."""

    async def get_for_image(self, image_id: UUID) -> Prediction | None:
        """Return the prediction for an image."""
        ...

    async def add(self, prediction: Prediction) -> Prediction:
        """Store a prediction."""
        ...

    async def list_eligible_in_window(
        self, project_id: UUID, start: datetime, end: datetime
    ) -> tuple[Prediction, ...]:
        """Confidence-passing predictions in a window, for aggregation."""
        ...


class SnapshotRepository(Protocol):
    """Progress snapshots — the timeline graph's source of truth."""

    async def get_for_window(
        self, project_id: UUID, window_start: datetime
    ) -> ProgressSnapshot | None:
        """Return one window's snapshot."""
        ...

    async def latest(self, project_id: UUID) -> ProgressSnapshot | None:
        """The most recent snapshot, i.e. the project's current progress."""
        ...

    async def list_series(
        self,
        project_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[ProgressSnapshot, ...]:
        """Ordered series for the timeline chart."""
        ...

    async def upsert(self, snapshot: ProgressSnapshot) -> ProgressSnapshot:
        """Insert or replace a window's snapshot.

        Upsert rather than insert because recomputation must be idempotent:
        re-running aggregation for a window replaces its row instead of
        accumulating duplicates.
        """
        ...

    async def delete_for_project(self, project_id: UUID) -> int:
        """Remove every snapshot, for a full timeline recompute."""
        ...


class RemarkRepository(Protocol):
    """Project remarks, system-generated and manual."""

    async def get(self, remark_id: UUID) -> Remark | None:
        """Return a remark by id."""
        ...

    async def list_for_project(
        self, project_id: UUID, *, public_only: bool = False, limit: int = 50
    ) -> tuple[Remark, ...]:
        """Remarks newest first; ``public_only`` for anonymous callers."""
        ...

    async def recent_of_type(
        self, project_id: UUID, remark_type: str, since: datetime
    ) -> Remark | None:
        """Most recent remark of a type — used to deduplicate system remarks."""
        ...

    async def add(self, remark: Remark) -> Remark:
        """Create a remark."""
        ...

    async def update(self, remark: Remark) -> Remark:
        """Edit a remark."""
        ...

    async def delete(self, remark_id: UUID) -> bool:
        """Delete a remark."""
        ...


class ReferenceAssetRepository(Protocol):
    """Blueprints, renders, and reference documents."""

    async def get(self, asset_id: UUID) -> ReferenceAsset | None:
        """Return an asset by id."""
        ...

    async def list_for_project(
        self, project_id: UUID, *, public_only: bool = False
    ) -> tuple[ReferenceAsset, ...]:
        """Assets attached to a project."""
        ...

    async def add(self, asset: ReferenceAsset) -> ReferenceAsset:
        """Record an uploaded asset."""
        ...

    async def delete(self, asset_id: UUID) -> bool:
        """Delete an asset."""
        ...


class ReportRepository(Protocol):
    """Generated PDF/CSV exports."""

    async def get(self, report_id: UUID) -> Report | None:
        """Return a report by id."""
        ...

    async def list_for_project(self, project_id: UUID, *, limit: int = 20) -> tuple[Report, ...]:
        """Reports for a project, newest first."""
        ...

    async def add(self, report: Report) -> Report:
        """Queue a report."""
        ...

    async def update(self, report: Report) -> Report:
        """Update job status or attach the finished file."""
        ...


class AIModelRepository(Protocol):
    """The trained-model registry behind ``GET /model/status``."""

    async def get(self, model_id: UUID) -> AIModel | None:
        """Return a model by id."""
        ...

    async def get_active(self, kind: ModelKind) -> AIModel | None:
        """The currently serving model of a kind, if any."""
        ...

    async def list_all(self) -> tuple[AIModel, ...]:
        """Every registered model — the thesis comparison table."""
        ...

    async def add(self, model: AIModel) -> AIModel:
        """Register a model."""
        ...

    async def set_active(self, model_id: UUID) -> AIModel:
        """Activate a model, deactivating the previous one of the same kind.

        Must be atomic: a partial unique index permits only one active model
        per kind, so deactivate-then-activate has to happen in one transaction.
        """
        ...


class NotificationRepository(Protocol):
    """In-app notifications."""

    async def list_for_user(
        self, user_id: UUID, *, unread_only: bool = False, limit: int = 50
    ) -> tuple[Notification, ...]:
        """Notifications for a user, newest first."""
        ...

    async def count_unread(self, user_id: UUID) -> int:
        """Unread count for the bell badge."""
        ...

    async def add(self, notification: Notification) -> Notification:
        """Create a notification."""
        ...

    async def mark_read(self, notification_id: UUID, read_at: datetime) -> bool:
        """Mark one notification read."""
        ...


class ContactMessageRepository(Protocol):
    """Messages from the public Contact Us form."""

    async def add(self, message: ContactMessage) -> ContactMessage:
        """Store a submitted message."""
        ...

    async def list_unhandled(self, *, limit: int = 50) -> tuple[ContactMessage, ...]:
        """Messages nobody has dealt with yet, oldest first."""
        ...
