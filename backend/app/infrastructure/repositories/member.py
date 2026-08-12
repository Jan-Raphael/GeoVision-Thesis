"""SQLAlchemy implementation of the project-membership repository."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from app.domain.entities import ProjectMember
from app.domain.enums import MembershipRole, MembershipStatus
from app.infrastructure.db import models
from app.infrastructure.repositories.mappers import to_project_member

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["SqlAlchemyProjectMemberRepository"]


class SqlAlchemyProjectMemberRepository:
    """Collaboration membership, backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def get(self, member_id: UUID) -> ProjectMember | None:
        """Return a membership row by id."""
        row = await self._session.get(models.ProjectMemberModel, member_id)
        return to_project_member(row) if row else None

    async def get_membership(self, project_id: UUID, user_id: UUID) -> ProjectMember | None:
        """Return a user's membership of a project, if any.

        The authorization layer's primary query. Note it returns *pending*
        invitations too — the caller checks
        :attr:`~app.domain.entities.ProjectMember.is_active`, because an
        invitee must be able to see their own pending invitation while holding
        no permissions on the project.
        """
        stmt = select(models.ProjectMemberModel).where(
            models.ProjectMemberModel.project_id == project_id,
            models.ProjectMemberModel.user_id == user_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_project_member(row) if row else None

    async def list_for_project(self, project_id: UUID) -> tuple[ProjectMember, ...]:
        """All memberships of a project, including pending invitations."""
        stmt = (
            select(models.ProjectMemberModel)
            .where(models.ProjectMemberModel.project_id == project_id)
            .order_by(models.ProjectMemberModel.created_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_project_member(row) for row in rows)

    async def list_pending_for_user(self, user_id: UUID) -> tuple[ProjectMember, ...]:
        """Invitations awaiting this user's response."""
        stmt = (
            select(models.ProjectMemberModel)
            .where(
                models.ProjectMemberModel.user_id == user_id,
                models.ProjectMemberModel.membership_status == MembershipStatus.PENDING,
            )
            .order_by(models.ProjectMemberModel.invited_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_project_member(row) for row in rows)

    async def count_by_role(self, project_id: UUID, role: MembershipRole) -> int:
        """How many accepted members hold *role*.

        Used to refuse removing or demoting the last owner, which would leave
        the project unadministrable.
        """
        stmt = (
            select(func.count())
            .select_from(models.ProjectMemberModel)
            .where(
                models.ProjectMemberModel.project_id == project_id,
                models.ProjectMemberModel.membership_role == role,
                models.ProjectMemberModel.membership_status == MembershipStatus.ACCEPTED,
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def add(self, member: ProjectMember) -> ProjectMember:
        """Create a membership or invitation."""
        row = models.ProjectMemberModel(
            id=member.id,
            project_id=member.project_id,
            user_id=member.user_id,
            membership_role=member.membership_role,
            membership_status=member.membership_status,
            invited_by=member.invited_by,
            invited_at=member.invited_at,
            responded_at=member.responded_at,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_project_member(row)

    async def update(self, member: ProjectMember) -> ProjectMember:
        """Change a membership's role or status."""
        row = await self._session.get(models.ProjectMemberModel, member.id)
        if row is None:
            msg = f"membership {member.id} not found"
            raise LookupError(msg)
        row.membership_role = member.membership_role
        row.membership_status = member.membership_status
        row.responded_at = member.responded_at
        await self._session.flush()
        await self._session.refresh(row)
        return to_project_member(row)

    async def delete(self, member_id: UUID) -> bool:
        """Remove a membership."""
        row = await self._session.get(models.ProjectMemberModel, member_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True
