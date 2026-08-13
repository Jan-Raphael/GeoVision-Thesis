"""Collaboration use cases (dashboard spec B.6).

Two owners handling one build, an engineer who may pair cameras but not
approve, a viewer who may only look. The rules that keep this safe:

* an invitation grants **nothing** until accepted;
* a project must always have at least one owner, so the last one cannot be
  removed or demoted;
* nobody can grant authority they do not hold themselves.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.core.clock import SYSTEM_CLOCK, Clock
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.domain.entities import Notification, ProjectMember
from app.domain.enums import MembershipRole, MembershipStatus, NotificationType

if TYPE_CHECKING:
    from app.domain.repositories import (
        NotificationRepository,
        ProjectMemberRepository,
        ProjectRepository,
        UserRepository,
    )

__all__ = [
    "ChangeMemberRole",
    "InviteMember",
    "RemoveMember",
    "RespondToInvitation",
]


class InviteMember:
    """Invite a user to collaborate on a project."""

    def __init__(
        self,
        members: ProjectMemberRepository,
        users: UserRepository,
        projects: ProjectRepository,
        notifications: NotificationRepository,
        *,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._members = members
        self._users = users
        self._projects = projects
        self._notifications = notifications
        self._clock = clock

    async def execute(
        self,
        project_id: UUID,
        *,
        identifier: str,
        membership_role: MembershipRole,
        invited_by: UUID,
    ) -> ProjectMember:
        """Create a pending invitation.

        Args:
            project_id: The project.
            identifier: Username or email of the person to invite. Exact match
                only — a fuzzy search here could invite the wrong person.
            membership_role: What they may do once they accept.
            invited_by: Who is inviting.

        Returns:
            The pending membership.

        Raises:
            NotFoundError: If no such user exists.
            ConflictError: If they are already a member or already invited.
            ForbiddenError: If the invite would create a second owner.
        """
        if membership_role is MembershipRole.OWNER:
            # Ownership is transferred deliberately, not handed out by
            # invitation. Two owners with equal authority to delete the project
            # is a governance problem, not a feature.
            msg = (
                "Ownership cannot be granted by invitation. Transfer ownership explicitly instead."
            )
            raise ForbiddenError(msg, code="OWNER_NOT_INVITABLE")

        invitee = await self._users.get_by_identifier(identifier.strip())
        if invitee is None or not invitee.is_active:
            # Deliberately explicit: the inviter typed a specific handle and
            # needs to know it was wrong. Usernames are public anyway.
            raise NotFoundError(
                f"No active account found for {identifier!r}.",
                code="USER_NOT_FOUND",
            )

        existing = await self._members.get_membership(project_id, invitee.id)
        if existing is not None and existing.membership_status is not MembershipStatus.REVOKED:
            state = (
                "already a member"
                if existing.membership_status is MembershipStatus.ACCEPTED
                else "already invited"
            )
            raise ConflictError(
                f"{invitee.username} is {state} on this project.",
                code="ALREADY_MEMBER",
            )

        now = self._clock.now()
        if existing is not None:
            # Re-inviting somebody previously removed: reuse the row, because
            # (project_id, user_id) is unique.
            member = await self._members.update(
                replace(
                    existing,
                    membership_role=membership_role,
                    membership_status=MembershipStatus.PENDING,
                    invited_by=invited_by,
                    invited_at=now,
                    responded_at=None,
                )
            )
        else:
            member = await self._members.add(
                ProjectMember(
                    id=uuid4(),
                    project_id=project_id,
                    user_id=invitee.id,
                    membership_role=membership_role,
                    membership_status=MembershipStatus.PENDING,
                    invited_by=invited_by,
                    invited_at=now,
                )
            )

        project = await self._projects.get(project_id)
        await self._notifications.add(
            Notification(
                id=uuid4(),
                user_id=invitee.id,
                project_id=project_id,
                notification_type=NotificationType.COLLAB_INVITE,
                title="You have been invited to a project",
                body=(
                    f"You were invited to join "
                    f"{project.name if project else 'a project'} "
                    f"as {membership_role.value}."
                ),
            )
        )
        return member


class RespondToInvitation:
    """Accept or decline an invitation."""

    def __init__(self, members: ProjectMemberRepository, *, clock: Clock = SYSTEM_CLOCK) -> None:
        """Wire the use case to its collaborators."""
        self._members = members
        self._clock = clock

    async def execute(
        self, membership_id: UUID, *, user_id: UUID, accept: bool
    ) -> ProjectMember | None:
        """Respond to an invitation.

        Args:
            membership_id: The invitation.
            user_id: The caller — must be the invitee.
            accept: True to accept, False to decline.

        Returns:
            The accepted membership, or ``None`` if declined.

        Raises:
            NotFoundError: If the invitation does not exist, or belongs to
                somebody else. Returning 404 rather than 403 keeps one user
                from probing another's invitations.
            ConflictError: If it has already been answered.
        """
        member = await self._members.get(membership_id)
        if member is None or member.user_id != user_id:
            msg = "Invitation not found."
            raise NotFoundError(msg)
        if member.membership_status is not MembershipStatus.PENDING:
            raise ConflictError(
                "That invitation has already been answered.",
                code="INVITATION_ANSWERED",
            )

        if not accept:
            await self._members.delete(membership_id)
            return None

        return await self._members.update(
            replace(
                member,
                membership_status=MembershipStatus.ACCEPTED,
                responded_at=self._clock.now(),
            )
        )


class ChangeMemberRole:
    """Change what an existing member may do."""

    def __init__(self, members: ProjectMemberRepository) -> None:
        """Wire the use case to its collaborators."""
        self._members = members

    async def execute(
        self, project_id: UUID, *, member_id: UUID, membership_role: MembershipRole
    ) -> ProjectMember:
        """Set a member's role.

        Raises:
            NotFoundError: If the membership does not belong to this project.
            ForbiddenError: If the change would leave the project ownerless, or
                would create an owner by promotion.
        """
        member = await self._members.get(member_id)
        if member is None or member.project_id != project_id:
            msg = "Member not found."
            raise NotFoundError(msg)

        if membership_role is MembershipRole.OWNER:
            msg = "Ownership must be transferred explicitly, not granted by promotion."
            raise ForbiddenError(msg, code="OWNER_NOT_GRANTABLE")

        if member.membership_role is MembershipRole.OWNER:
            await self._require_another_owner(project_id)

        return await self._members.update(replace(member, membership_role=membership_role))

    async def _require_another_owner(self, project_id: UUID) -> None:
        """Refuse to demote the last owner."""
        owners = await self._members.count_by_role(project_id, MembershipRole.OWNER)
        if owners <= 1:
            msg = (
                "This is the project's only owner. Promote another owner first, "
                "or the project would be left with nobody who can administer it."
            )
            raise ForbiddenError(msg, code="LAST_OWNER")


class RemoveMember:
    """Remove somebody from a project."""

    def __init__(self, members: ProjectMemberRepository) -> None:
        """Wire the use case to its collaborators."""
        self._members = members

    async def execute(self, project_id: UUID, *, member_id: UUID, actor_id: UUID) -> bool:
        """Remove a membership.

        Raises:
            NotFoundError: If the membership does not belong to this project.
            ForbiddenError: If removing the last owner, or removing yourself.
        """
        member = await self._members.get(member_id)
        if member is None or member.project_id != project_id:
            msg = "Member not found."
            raise NotFoundError(msg)

        if member.user_id == actor_id:
            # Self-removal by an owner would strand the project; for others it
            # is simply confusing next to a "leave project" action.
            msg = "You cannot remove yourself from a project."
            raise ForbiddenError(msg, code="CANNOT_REMOVE_SELF")

        if member.membership_role is MembershipRole.OWNER:
            owners = await self._members.count_by_role(project_id, MembershipRole.OWNER)
            if owners <= 1:
                msg = "This is the project's only owner and cannot be removed."
                raise ForbiddenError(msg, code="LAST_OWNER")

        return await self._members.delete(member_id)
