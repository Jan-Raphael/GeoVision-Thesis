"""Project endpoints: create, read the folder, edit, publish, archive, approve."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import (
    AccessContextDep,
    AssetRepoDep,
    AuditDep,
    ClientIPDep,
    ClockDep,
    CurrentUser,
    DeviceRepoDep,
    ImageRepoDep,
    MemberRepoDep,
    NotificationRepoDep,
    ProjectRepoDep,
    RemarkRepoDep,
    SnapshotRepoDep,
    StorageDep,
    UserRepoDep,
    require_permission,
)
from app.api.route import TransactionalRoute
from app.api.schemas.common import MessageResponse
from app.api.schemas.projects import (
    ApproveProjectRequest,
    CreateProjectRequest,
    ProjectFolderResponse,
    ProjectSummaryResponse,
    UpdateProjectRequest,
    VisibilityRequest,
)
from app.api.v1.presenters import present_folder, present_summary, sign_thumbnails
from app.application.use_cases.projects import (
    ApproveProject,
    ArchiveProject,
    CreateProject,
    GetProjectFolder,
    SetVisibility,
    UpdateProject,
)
from app.domain.enums import Permission
from app.domain.services.authorization import AccessContext
from app.infrastructure.audit import AuditAction

router = APIRouter(prefix="/projects", tags=["projects"], route_class=TransactionalRoute)

ProjectId = Annotated[UUID, Path(description="Project id")]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a project folder",
    response_model=ProjectSummaryResponse,
)
async def create_project(
    payload: CreateProjectRequest,
    user: CurrentUser,
    projects: ProjectRepoDep,
    members: MemberRepoDep,
    audit: AuditDep,
    client_ip: ClientIPDep,
    clock: ClockDep,
) -> ProjectSummaryResponse:
    """Create a project and make the caller its owner.

    A duplicate code returns **409** with three *verified-free* alternatives, so
    the suggestion the user clicks cannot collide in turn.
    """
    created = await CreateProject(projects, members, clock=clock).execute(
        owner_id=user.id,
        name=payload.name,
        code_initials=payload.code_initials,
        project_number=payload.project_number,
        location_label=payload.location_label,
        latitude=payload.latitude,
        longitude=payload.longitude,
        start_date=payload.start_date,
        deadline_date=payload.deadline_date,
        visibility=payload.visibility,
        intended_use=payload.intended_use,
        description=payload.description,
        worker_count=payload.worker_count,
        timezone=payload.timezone,
    )
    await audit.record(
        AuditAction.PROJECT_CREATED,
        entity_type="project",
        entity_id=created.id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={"project_code": created.code.value},
    )
    return present_summary(created)


@router.get("", summary="My projects", response_model=list[ProjectSummaryResponse])
async def list_my_projects(
    user: CurrentUser,
    projects: ProjectRepoDep,
) -> list[ProjectSummaryResponse]:
    """Projects the caller owns or is an accepted member of."""
    found = await projects.list_for_user(user.id)
    return [present_summary(project) for project in found]


@router.get(
    "/{project_id}",
    summary="Project folder",
    response_model=ProjectFolderResponse,
    responses={404: {"description": "No such project, or not visible to you"}},
)
async def get_project_folder(
    project_id: ProjectId,
    access: AccessContextDep,
    projects: ProjectRepoDep,
    members: MemberRepoDep,
    devices: DeviceRepoDep,
    images: ImageRepoDep,
    remarks: RemarkRepoDep,
    assets: AssetRepoDep,
    snapshots: SnapshotRepoDep,
    users: UserRepoDep,
    storage: StorageDep,
    clock: ClockDep,
) -> ProjectFolderResponse:
    """The whole folder page in one request.

    Includes a ``permissions`` block describing what *this* caller may do, so
    the dashboard renders its controls from server truth. A caller who may not
    see the project at all already received a **404** from the access guard —
    never a 403, which would confirm the project exists.
    """
    folder = await GetProjectFolder(
        projects, members, devices, images, remarks, assets, snapshots, users, clock=clock
    ).execute(access)

    member_users = {}
    for member in folder.members:
        found = await users.get(member.user_id)
        if found is not None:
            member_users[str(member.user_id)] = found

    asset_urls = {
        str(asset.id): await storage.signed_url(asset.storage_key) for asset in folder.assets
    }

    return present_folder(
        folder,
        now=clock.now(),
        member_users=member_users,
        asset_urls=asset_urls,
        thumb_urls=await sign_thumbnails(storage, folder.recent_images),
    )


@router.patch(
    "/{project_id}",
    summary="Edit a project",
    response_model=ProjectSummaryResponse,
)
async def update_project(
    project_id: ProjectId,
    payload: UpdateProjectRequest,
    access: Annotated[AccessContext, Depends(require_permission(Permission.PROJECT_EDIT))],
    projects: ProjectRepoDep,
) -> ProjectSummaryResponse:
    """Apply a partial update.

    ``project_code`` cannot be changed: it is embedded in every device name and
    image filename, so editing it would orphan the capture history.
    """
    _ = access
    updated = await UpdateProject(projects).execute(
        project_id,
        name=payload.name,
        description=payload.description,
        intended_use=payload.intended_use,
        location_label=payload.location_label,
        latitude=payload.latitude,
        longitude=payload.longitude,
        start_date=payload.start_date,
        deadline_date=payload.deadline_date,
        worker_count=payload.worker_count,
        timezone=payload.timezone,
    )
    return present_summary(updated)


@router.patch(
    "/{project_id}/visibility",
    summary="Publish or unpublish",
    response_model=ProjectSummaryResponse,
)
async def set_visibility(
    project_id: ProjectId,
    payload: VisibilityRequest,
    access: Annotated[AccessContext, Depends(require_permission(Permission.PROJECT_VISIBILITY))],
    projects: ProjectRepoDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
) -> ProjectSummaryResponse:
    """Move a project on or off the public feed. Owner only."""
    _ = access
    updated = await SetVisibility(projects).execute(project_id, payload.visibility)
    await audit.record(
        AuditAction.PROJECT_VISIBILITY_CHANGED,
        entity_type="project",
        entity_id=project_id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={"visibility": payload.visibility.value},
    )
    return present_summary(updated)


@router.post(
    "/{project_id}/approve",
    summary="Mark as inspected and complete",
    response_model=ProjectSummaryResponse,
)
async def approve_project(
    project_id: ProjectId,
    payload: ApproveProjectRequest,
    access: Annotated[AccessContext, Depends(require_permission(Permission.PROJECT_APPROVE))],
    projects: ProjectRepoDep,
    members: MemberRepoDep,
    notifications: NotificationRepoDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
    clock: ClockDep,
) -> ProjectSummaryResponse:
    """Award the final 20 % after a physical inspection (ADR-007).

    The AI stops at 80 %. This is the only route to 100 %, it requires
    inspection notes, and it is recorded against the approver's name — because
    declaring a building complete is a claim somebody has to stand behind.
    """
    _ = access
    completed = await ApproveProject(projects, members, notifications, clock=clock).execute(
        project_id, approved_by=user.id, inspection_notes=payload.inspection_notes
    )
    await audit.record(
        AuditAction.PROJECT_APPROVED,
        entity_type="project",
        entity_id=project_id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={"notes_length": len(payload.inspection_notes)},
    )
    return present_summary(completed)


@router.post(
    "/{project_id}/archive",
    summary="Archive a project",
    response_model=MessageResponse,
)
async def archive_project(
    project_id: ProjectId,
    access: Annotated[AccessContext, Depends(require_permission(Permission.PROJECT_DELETE))],
    projects: ProjectRepoDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
    clock: ClockDep,
) -> MessageResponse:
    """Retire a project while keeping its history.

    Archiving rather than deleting: the images and progress record are the
    project's evidence. Deletion is a separate, deliberate action.
    """
    _ = access
    await ArchiveProject(projects, clock=clock).execute(project_id)
    await audit.record(
        AuditAction.PROJECT_ARCHIVED,
        entity_type="project",
        entity_id=project_id,
        actor_user_id=user.id,
        ip_address=client_ip,
    )
    return MessageResponse(message="Project archived.")
