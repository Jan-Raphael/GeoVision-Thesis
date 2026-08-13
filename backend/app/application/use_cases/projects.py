"""Project use cases: create, read, edit, publish, archive, approve.

The centre of the dashboard spec. Two things here carry more weight than the
rest:

* :class:`GetProjectFolder` assembles the whole folder page in one pass,
  including a ``permissions`` block so the UI renders controls from server
  truth instead of re-deriving authority in the browser.
* :class:`ApproveProject` is the human sign-off that awards the final 20 %
  (ADR-007). It is the most consequential action in the system and the only
  path to 100 %.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.core.clock import SYSTEM_CLOCK, Clock
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.domain.entities import Project, ProjectMember
from app.domain.enums import (
    ApprovalState,
    MembershipRole,
    MembershipStatus,
    NotificationType,
    ProjectStatus,
    Visibility,
)
from app.domain.services.authorization import AccessContext
from app.domain.services.status import ProjectSignals, derive_status, explain_status
from app.domain.value_objects import (
    DomainValidationError,
    GeoPoint,
    ProgressPct,
    ProjectCode,
)

if TYPE_CHECKING:
    from app.domain.entities import (
        Device,
        Image,
        ProgressSnapshot,
        ReferenceAsset,
        Remark,
        User,
    )
    from app.domain.repositories import (
        DeviceRepository,
        ImageRepository,
        NotificationRepository,
        ProjectMemberRepository,
        ProjectRepository,
        ReferenceAssetRepository,
        RemarkRepository,
        SnapshotRepository,
        UserRepository,
    )

__all__ = [
    "ApproveProject",
    "ArchiveProject",
    "CreateProject",
    "GetProjectFolder",
    "ProjectFolder",
    "SetVisibility",
    "UpdateProject",
]


@dataclass(frozen=True, slots=True)
class ProjectFolder:
    """Everything the project folder page renders.

    Assembled in one use case so the page is one round trip, and so the
    ``permissions`` block is guaranteed consistent with the data beside it.
    """

    project: Project
    owner: User | None
    status_reason: str
    members: tuple[ProjectMember, ...] = ()
    devices: tuple[Device, ...] = ()
    recent_images: tuple[Image, ...] = ()
    remarks: tuple[Remark, ...] = ()
    assets: tuple[ReferenceAsset, ...] = ()
    timeline: tuple[ProgressSnapshot, ...] = ()
    access: AccessContext | None = None


class CreateProject:
    """Create a project folder and make the creator its owner."""

    def __init__(
        self,
        projects: ProjectRepository,
        members: ProjectMemberRepository,
        *,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._projects = projects
        self._members = members
        self._clock = clock

    async def execute(
        self,
        *,
        owner_id: UUID,
        name: str,
        code_initials: str,
        project_number: int,
        location_label: str,
        latitude: float,
        longitude: float,
        start_date: date,
        deadline_date: date,
        visibility: Visibility,
        intended_use: str | None = None,
        description: str | None = None,
        worker_count: int | None = None,
        timezone: str = "Asia/Manila",
    ) -> Project:
        """Create the project.

        Args:
            owner_id: The creator, who becomes the owner.
            name: Display name, e.g. "Jollibee Naga Branch".
            code_initials: 2-5 letters chosen by the owner.
            project_number: 0-99 counter.
            location_label: Human-readable address.
            latitude: WGS-84 latitude.
            longitude: WGS-84 longitude.
            start_date: When work begins.
            deadline_date: Contract or estimated deadline.
            visibility: Whether the project appears on the public feed.
            intended_use: What the building is for (shown publicly).
            description: Free text.
            worker_count: Optional; the form allows skipping it.
            timezone: IANA zone used for capture windows and reports.

        Returns:
            The created project.

        Raises:
            ValidationFailedError: If the code parts or dates are invalid.
            ConflictError: If the project code is taken, with suggestions.
        """
        try:
            code = ProjectCode.build(code_initials, project_number)
            location = GeoPoint(latitude=latitude, longitude=longitude)
        except DomainValidationError as exc:
            raise ValidationFailedError(str(exc)) from exc

        if await self._projects.code_exists(code):
            # Only offer codes that are actually free - suggesting a taken one
            # would just move the collision one click further along.
            suggestions = await self._free_suggestions(code)
            raise ConflictError(
                f"Project code {code.value} is already in use.",
                code="PROJECT_CODE_TAKEN",
                details={"project_code": code.value, "suggestions": suggestions},
            )

        try:
            project = Project(
                id=uuid4(),
                owner_id=owner_id,
                name=name,
                code=code,
                location_label=location_label,
                location=location,
                start_date=start_date,
                deadline_date=deadline_date,
                visibility=visibility,
                status=ProjectStatus.ACTIVE,
                intended_use=intended_use,
                description=description,
                worker_count=worker_count,
                timezone=timezone,
            )
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc

        created = await self._projects.add(project)

        # The owner is a member too, so every authority check has exactly one
        # source of truth instead of a special case for "is this the owner?".
        await self._members.add(
            ProjectMember(
                id=uuid4(),
                project_id=created.id,
                user_id=owner_id,
                membership_role=MembershipRole.OWNER,
                membership_status=MembershipStatus.ACCEPTED,
                responded_at=self._clock.now(),
            )
        )
        return created

    async def _free_suggestions(self, code: ProjectCode, count: int = 3) -> list[str]:
        """Return codes that are syntactically valid *and* currently unused."""
        free: list[str] = []
        for candidate in code.suggest_alternatives(count * 3):
            try:
                parsed = ProjectCode(candidate)
            except DomainValidationError:
                continue
            if not await self._projects.code_exists(parsed):
                free.append(candidate)
            if len(free) == count:
                break
        return free


class GetProjectFolder:
    """Assemble the full project folder page."""

    #: How many recent captures the folder shows before "see all".
    RECENT_IMAGE_LIMIT = 12
    #: Roughly a quarter of daily snapshots - enough for a readable chart.
    TIMELINE_LIMIT = 90

    def __init__(
        self,
        projects: ProjectRepository,
        members: ProjectMemberRepository,
        devices: DeviceRepository,
        images: ImageRepository,
        remarks: RemarkRepository,
        assets: ReferenceAssetRepository,
        snapshots: SnapshotRepository,
        users: UserRepository,
        *,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._projects = projects
        self._members = members
        self._devices = devices
        self._images = images
        self._remarks = remarks
        self._assets = assets
        self._snapshots = snapshots
        self._users = users
        self._clock = clock

    async def execute(self, access: AccessContext, *, public_only: bool = False) -> ProjectFolder:
        """Build the folder for one caller.

        Args:
            access: The caller's resolved authority, from the API guard. Passed
                in rather than recomputed, so the whole response is built from
                one consistent authority snapshot.
            public_only: Restrict remarks and assets to those marked public.
                Set for anonymous callers.

        Returns:
            The assembled folder.

        Raises:
            NotFoundError: If the project vanished between the guard and here.
        """
        project = await self._projects.get(access.project_id)
        if project is None:
            msg = "Project not found."
            raise NotFoundError(msg)

        project = await self._refresh_status(project)
        signals = _signals_for(project)
        now = self._clock.now()

        recent = await self._images.list_for_project(project.id, limit=self.RECENT_IMAGE_LIMIT)
        return ProjectFolder(
            project=project,
            owner=await self._users.get(project.owner_id),
            status_reason=explain_status(signals, now),
            members=await self._members.list_for_project(project.id),
            devices=await self._devices.list_for_project(project.id),
            recent_images=recent.items,
            remarks=await self._remarks.list_for_project(project.id, public_only=public_only),
            assets=await self._assets.list_for_project(project.id, public_only=public_only),
            timeline=(await self._snapshots.list_series(project.id))[-self.TIMELINE_LIMIT :],
            access=access,
        )

    async def _refresh_status(self, project: Project) -> Project:
        """Recompute the derived status, persisting it only if it changed.

        The stored column exists so project *lists* stay cheap. Recomputing on
        folder read keeps it honest between runs of the Module 10 beat job,
        without writing on every request.
        """
        current = derive_status(_signals_for(project), self._clock.now())
        if current is project.status:
            return project
        return await self._projects.update(replace(project, status=current))


class UpdateProject:
    """Edit a project's editable fields."""

    def __init__(self, projects: ProjectRepository) -> None:
        """Wire the use case to its collaborators."""
        self._projects = projects

    async def execute(
        self,
        project_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        intended_use: str | None = None,
        location_label: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        start_date: date | None = None,
        deadline_date: date | None = None,
        worker_count: int | None = None,
        timezone: str | None = None,
    ) -> Project:
        """Apply a partial update.

        ``project_code`` is deliberately absent: it is embedded in every device
        name and image filename, so changing it would orphan the project's whole
        capture history.

        Raises:
            NotFoundError: If the project does not exist.
            ValidationFailedError: If the result would be invalid.
        """
        project = await self._projects.get(project_id)
        if project is None:
            msg = "Project not found."
            raise NotFoundError(msg)

        location = project.location
        if latitude is not None or longitude is not None:
            try:
                location = GeoPoint(
                    latitude=latitude if latitude is not None else project.location.latitude,
                    longitude=(longitude if longitude is not None else project.location.longitude),
                )
            except DomainValidationError as exc:
                raise ValidationFailedError(str(exc)) from exc

        try:
            updated = replace(
                project,
                name=name if name is not None else project.name,
                description=description if description is not None else project.description,
                intended_use=(intended_use if intended_use is not None else project.intended_use),
                location_label=(
                    location_label if location_label is not None else project.location_label
                ),
                location=location,
                start_date=start_date if start_date is not None else project.start_date,
                deadline_date=(
                    deadline_date if deadline_date is not None else project.deadline_date
                ),
                worker_count=(worker_count if worker_count is not None else project.worker_count),
                timezone=timezone if timezone is not None else project.timezone,
            )
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc

        return await self._projects.update(updated)


class SetVisibility:
    """Publish a project to the homepage feed, or withdraw it."""

    def __init__(self, projects: ProjectRepository) -> None:
        """Wire the use case to its collaborators."""
        self._projects = projects

    async def execute(self, project_id: UUID, visibility: Visibility) -> Project:
        """Set the visibility flag.

        Raises:
            NotFoundError: If the project does not exist.
        """
        project = await self._projects.get(project_id)
        if project is None:
            msg = "Project not found."
            raise NotFoundError(msg)
        return await self._projects.update(replace(project, visibility=visibility))


class ArchiveProject:
    """Retire a project without destroying its history."""

    def __init__(self, projects: ProjectRepository, *, clock: Clock = SYSTEM_CLOCK) -> None:
        """Wire the use case to its collaborators."""
        self._projects = projects
        self._clock = clock

    async def execute(self, project_id: UUID) -> Project:
        """Archive the project.

        Archiving rather than deleting: the images, predictions, and progress
        history are the thesis's evidence. Deletion exists as a separate,
        owner-only action.

        Raises:
            NotFoundError: If the project does not exist.
        """
        project = await self._projects.get(project_id)
        if project is None:
            msg = "Project not found."
            raise NotFoundError(msg)
        now = self._clock.now()
        return await self._projects.update(
            replace(project, archived_at=now, status=ProjectStatus.ARCHIVED)
        )


class ApproveProject:
    """The human inspection that awards the final 20 % (ADR-007).

    The AI stops at 80 %. Only a named person, on record, having physically
    inspected the site, can declare a building complete. That is a deliberate
    accountability property, and this use case is the only path to 100 %.
    """

    def __init__(
        self,
        projects: ProjectRepository,
        members: ProjectMemberRepository,
        notifications: NotificationRepository,
        *,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._projects = projects
        self._members = members
        self._notifications = notifications
        self._clock = clock

    async def execute(
        self, project_id: UUID, *, approved_by: UUID, inspection_notes: str
    ) -> Project:
        """Record the sign-off and set the project to 100 % complete.

        Args:
            project_id: The project being approved.
            approved_by: The person taking responsibility.
            inspection_notes: What they found. Required — an unexplained
                approval is not an inspection record.

        Returns:
            The completed project.

        Raises:
            NotFoundError: If the project does not exist.
            ConflictError: If it is not awaiting inspection, or already approved.
            ValidationFailedError: If the notes are missing.
        """
        project = await self._projects.get(project_id)
        if project is None:
            msg = "Project not found."
            raise NotFoundError(msg)

        if project.approval_state is ApprovalState.APPROVED:
            raise ConflictError(
                "This project has already been approved.",
                code="ALREADY_APPROVED",
            )
        if project.approval_state is not ApprovalState.AWAITING_INSPECTION:
            raise ConflictError(
                "This project is not ready for inspection yet. The AI must "
                "first confirm all four exterior stages are complete.",
                code="NOT_AWAITING_INSPECTION",
                details={"progress_pct": project.progress_pct.as_float()},
            )
        if not inspection_notes.strip():
            msg = "Inspection notes are required to approve a project."
            raise ValidationFailedError(msg)

        now = self._clock.now()
        completed = await self._projects.update(
            replace(
                project,
                approval_state=ApprovalState.APPROVED,
                status=ProjectStatus.COMPLETED,
                progress_pct=ProgressPct(Decimal("100.00")),
                approved_by=approved_by,
                approved_at=now,
                inspection_notes=inspection_notes.strip(),
                completed_at=now,
            )
        )

        await self._notify_members(completed, approved_by)
        return completed

    async def _notify_members(self, project: Project, actor_id: UUID) -> None:
        """Tell everyone on the project that it is finished."""
        from app.domain.entities import Notification

        for member in await self._members.list_for_project(project.id):
            if not member.is_active or member.user_id == actor_id:
                continue
            await self._notifications.add(
                Notification(
                    id=uuid4(),
                    user_id=member.user_id,
                    project_id=project.id,
                    notification_type=NotificationType.INSPECTION_REQUIRED,
                    title=f"{project.name} is complete",
                    body=("The project has been inspected and marked complete at 100%."),
                )
            )


def _signals_for(project: Project) -> ProjectSignals:
    """Extract the inputs the status rules need from a project."""
    return ProjectSignals(
        start_date=project.start_date,
        deadline_date=project.deadline_date,
        displayed_pct=project.progress_pct.as_float(),
        approval_state=project.approval_state,
        last_capture_at=project.last_capture_at,
        archived_at=project.archived_at,
    )


def status_of(project: Project, now: datetime) -> ProjectStatus:
    """Public helper: the project's status right now.

    Used by the feed and search results, where reading is cheap but writing is
    not.
    """
    return derive_status(_signals_for(project), now)
