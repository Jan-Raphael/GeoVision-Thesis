"""Collaboration endpoints (dashboard spec B.6)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import (
    AccessContextDep,
    AuditDep,
    ClientIPDep,
    ClockDep,
    CurrentUser,
    MemberRepoDep,
    NotificationRepoDep,
    ProjectRepoDep,
    UserRepoDep,
    require_permission,
)
from app.api.schemas.common import MessageResponse
from app.api.schemas.projects import (
    ChangeMemberRoleRequest,
    InvitationResponseRequest,
    InviteMemberRequest,
    MemberResponse,
)
from app.api.v1.presenters import present_member
from app.application.use_cases.members import (
    ChangeMemberRole,
    InviteMember,
    RemoveMember,
    RespondToInvitation,
)
from app.domain.enums import Permission
from app.domain.services.authorization import AccessContext
from app.infrastructure.audit import AuditAction

router = APIRouter(tags=["members"])

ProjectId = Annotated[UUID, Path(description="Project id")]
MemberId = Annotated[UUID, Path(description="Membership id")]


@router.get(
    "/projects/{project_id}/members",
    summary="List collaborators",
    response_model=list[MemberResponse],
)
async def list_members(
    project_id: ProjectId,
    access: AccessContextDep,
    members: MemberRepoDep,
    users: UserRepoDep,
) -> list[MemberResponse]:
    """Everyone on the project, including pending invitations."""
    _ = access
    found = await members.list_for_project(project_id)
    return [present_member(member, await users.get(member.user_id)) for member in found]


@router.post(
    "/projects/{project_id}/members",
    status_code=status.HTTP_201_CREATED,
    summary="Invite a collaborator",
    response_model=MemberResponse,
)
async def invite_member(
    project_id: ProjectId,
    payload: InviteMemberRequest,
    access: Annotated[AccessContext, Depends(require_permission(Permission.MEMBER_MANAGE))],
    members: MemberRepoDep,
    users: UserRepoDep,
    projects: ProjectRepoDep,
    notifications: NotificationRepoDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
    clock: ClockDep,
) -> MemberResponse:
    """Invite somebody by username or email.

    The invitation is **pending** and confers no authority until accepted, so
    an invitee can see they were invited without gaining any access to the
    project in the meantime.
    """
    _ = access
    member = await InviteMember(members, users, projects, notifications, clock=clock).execute(
        project_id,
        identifier=payload.identifier,
        membership_role=payload.membership_role,
        invited_by=user.id,
    )
    await audit.record(
        AuditAction.MEMBER_INVITED,
        entity_type="project",
        entity_id=project_id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={"role": payload.membership_role.value},
    )
    return present_member(member, await users.get(member.user_id))


@router.patch(
    "/projects/{project_id}/members/{member_id}",
    summary="Change a collaborator's role",
    response_model=MemberResponse,
)
async def change_member_role(
    project_id: ProjectId,
    member_id: MemberId,
    payload: ChangeMemberRoleRequest,
    access: Annotated[AccessContext, Depends(require_permission(Permission.MEMBER_MANAGE))],
    members: MemberRepoDep,
    users: UserRepoDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
) -> MemberResponse:
    """Set a member's role.

    Refuses to demote the project's last owner: a project with nobody able to
    administer it cannot be recovered through the UI.
    """
    _ = access
    member = await ChangeMemberRole(members).execute(
        project_id, member_id=member_id, membership_role=payload.membership_role
    )
    await audit.record(
        AuditAction.MEMBER_ROLE_CHANGED,
        entity_type="project",
        entity_id=project_id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={"member_id": str(member_id), "role": payload.membership_role.value},
    )
    return present_member(member, await users.get(member.user_id))


@router.delete(
    "/projects/{project_id}/members/{member_id}",
    summary="Remove a collaborator",
    response_model=MessageResponse,
)
async def remove_member(
    project_id: ProjectId,
    member_id: MemberId,
    access: Annotated[AccessContext, Depends(require_permission(Permission.MEMBER_MANAGE))],
    members: MemberRepoDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
) -> MessageResponse:
    """Remove somebody from the project."""
    _ = access
    await RemoveMember(members).execute(project_id, member_id=member_id, actor_id=user.id)
    await audit.record(
        AuditAction.MEMBER_REMOVED,
        entity_type="project",
        entity_id=project_id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={"member_id": str(member_id)},
    )
    return MessageResponse(message="Collaborator removed.")


@router.get(
    "/invitations",
    summary="My pending invitations",
    response_model=list[MemberResponse],
)
async def my_invitations(
    user: CurrentUser,
    members: MemberRepoDep,
    users: UserRepoDep,
) -> list[MemberResponse]:
    """Invitations awaiting the caller's response."""
    pending = await members.list_pending_for_user(user.id)
    return [present_member(member, await users.get(member.user_id)) for member in pending]


@router.post(
    "/invitations/{member_id}",
    summary="Accept or decline an invitation",
    response_model=MessageResponse,
)
async def respond_to_invitation(
    member_id: MemberId,
    payload: InvitationResponseRequest,
    user: CurrentUser,
    members: MemberRepoDep,
    clock: ClockDep,
) -> MessageResponse:
    """Respond to an invitation addressed to the caller.

    An invitation belonging to somebody else returns **404**, not 403 — one
    user must not be able to probe another's invitations.
    """
    await RespondToInvitation(members, clock=clock).execute(
        member_id, user_id=user.id, accept=payload.accept
    )
    return MessageResponse(
        message="Invitation accepted." if payload.accept else "Invitation declined."
    )
