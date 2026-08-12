"""SQLAlchemy implementation of the project repository.

The public-read methods here are the enforcement point for project privacy.
They filter in SQL rather than fetching then checking, so an anonymous caller
cannot receive a private project even if a future refactor drops an
``if`` somewhere in the API layer.
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Select, func, or_, select

from app.domain.entities import Project
from app.domain.enums import MembershipStatus, ProjectStatus, Visibility
from app.domain.repositories.base import Page
from app.domain.value_objects import ProjectCode
from app.infrastructure.db import models
from app.infrastructure.repositories._result import to_decimal
from app.infrastructure.repositories.mappers import to_project

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["SqlAlchemyProjectRepository"]

SEARCH_SIMILARITY_THRESHOLD = 0.15


def _encode_cursor(moment: datetime, project_id: UUID) -> str:
    """Encode a keyset cursor.

    The cursor carries the sort key *and* the id, so pagination is stable even
    when several projects share a timestamp.
    """
    raw = f"{moment.isoformat()}|{project_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID] | None:
    """Decode a keyset cursor, returning ``None`` if it is malformed.

    A bad cursor is treated as "start from the beginning" rather than an error:
    cursors appear in URLs, and a truncated one should not produce a 500.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        moment_str, _, id_str = raw.partition("|")
        return datetime.fromisoformat(moment_str), UUID(id_str)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


class SqlAlchemyProjectRepository:
    """Projects, backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    # -- unrestricted reads (caller must already be authorized) -------------

    async def get(self, project_id: UUID) -> Project | None:
        """Return a project by id, regardless of visibility."""
        row = await self._session.get(models.ProjectModel, project_id)
        return to_project(row) if row else None

    async def get_by_code(self, code: ProjectCode) -> Project | None:
        """Return a project by code, regardless of visibility."""
        stmt = select(models.ProjectModel).where(models.ProjectModel.project_code == code.value)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_project(row) if row else None

    async def exists(self, project_id: UUID) -> bool:
        """Whether a project exists."""
        stmt = (
            select(func.count())
            .select_from(models.ProjectModel)
            .where(models.ProjectModel.id == project_id)
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    async def code_exists(self, code: ProjectCode) -> bool:
        """Whether a project code is taken. Codes are globally unique."""
        stmt = (
            select(func.count())
            .select_from(models.ProjectModel)
            .where(models.ProjectModel.project_code == code.value)
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    # -- visibility-scoped reads (safe for anonymous callers) ---------------

    @staticmethod
    def _public_filter(
        stmt: Select[tuple[models.ProjectModel]],
    ) -> Select[tuple[models.ProjectModel]]:
        """Restrict a query to publicly visible projects.

        One definition, applied by every public read, so the rule cannot drift
        between endpoints.
        """
        return stmt.where(
            models.ProjectModel.visibility == Visibility.PUBLIC,
            models.ProjectModel.archived_at.is_(None),
            models.ProjectModel.status != ProjectStatus.ARCHIVED,
        )

    async def get_public_by_code(self, code: ProjectCode) -> Project | None:
        """Return a project only if it is public.

        ``None`` for private projects, so the API answers **404 rather than
        403** and never confirms that a private project exists.
        """
        stmt = self._public_filter(
            select(models.ProjectModel).where(models.ProjectModel.project_code == code.value)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_project(row) if row else None

    async def list_public_feed(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        stage: str | None = None,
        status: ProjectStatus | None = None,
        query: str | None = None,
    ) -> Page[Project]:
        """The homepage feed: public, non-archived projects, newest activity first."""
        stmt = self._public_filter(select(models.ProjectModel))

        if stage:
            stmt = stmt.where(models.ProjectModel.macro_stage == stage)
        if status:
            stmt = stmt.where(models.ProjectModel.status == status)
        if query:
            similarity = func.greatest(
                func.similarity(models.ProjectModel.name, query),
                func.similarity(models.ProjectModel.location_label, query),
            )
            stmt = stmt.where(similarity > SEARCH_SIMILARITY_THRESHOLD)

        # Sort by recency of activity, falling back to creation for projects
        # that have never received a capture.
        sort_key = func.coalesce(
            models.ProjectModel.last_capture_at, models.ProjectModel.created_at
        )
        if cursor and (decoded := _decode_cursor(cursor)):
            cursor_moment, cursor_id = decoded
            stmt = stmt.where(
                or_(
                    sort_key < cursor_moment,
                    (sort_key == cursor_moment) & (models.ProjectModel.id < cursor_id),
                )
            )

        stmt = stmt.order_by(sort_key.desc(), models.ProjectModel.id.desc()).limit(limit + 1)
        rows = list((await self._session.execute(stmt)).scalars().all())

        # One extra row was requested purely to detect whether more exist.
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(
                last.last_capture_at or last.created_at or datetime.now(UTC), last.id
            )

        return Page(items=tuple(to_project(row) for row in rows), next_cursor=next_cursor)

    async def list_public_for_user(self, user_id: UUID) -> tuple[Project, ...]:
        """Public projects to show on a user's public profile.

        Includes projects they own and ones they are an accepted member of —
        the profile says "what projects are they handling".
        """
        member_projects = select(models.ProjectMemberModel.project_id).where(
            models.ProjectMemberModel.user_id == user_id,
            models.ProjectMemberModel.membership_status == MembershipStatus.ACCEPTED,
        )
        stmt = self._public_filter(
            select(models.ProjectModel).where(
                or_(
                    models.ProjectModel.owner_id == user_id,
                    models.ProjectModel.id.in_(member_projects),
                )
            )
        ).order_by(models.ProjectModel.created_at.desc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_project(row) for row in rows)

    async def search(self, query: str, *, limit: int = 20) -> tuple[Project, ...]:
        """Fuzzy-search public projects by name or location."""
        similarity = func.greatest(
            func.similarity(models.ProjectModel.name, query),
            func.similarity(models.ProjectModel.location_label, query),
        )
        stmt = (
            self._public_filter(select(models.ProjectModel))
            .where(similarity > SEARCH_SIMILARITY_THRESHOLD)
            .order_by(similarity.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_project(row) for row in rows)

    # -- authenticated reads -------------------------------------------------

    async def list_for_user(
        self, user_id: UUID, *, status: ProjectStatus | None = None
    ) -> tuple[Project, ...]:
        """Projects the user owns or is an accepted member of, public or not."""
        member_projects = select(models.ProjectMemberModel.project_id).where(
            models.ProjectMemberModel.user_id == user_id,
            models.ProjectMemberModel.membership_status == MembershipStatus.ACCEPTED,
        )
        stmt = select(models.ProjectModel).where(
            or_(
                models.ProjectModel.owner_id == user_id,
                models.ProjectModel.id.in_(member_projects),
            )
        )
        if status:
            stmt = stmt.where(models.ProjectModel.status == status)
        stmt = stmt.order_by(models.ProjectModel.created_at.desc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_project(row) for row in rows)

    # -- writes --------------------------------------------------------------

    async def add(self, project: Project) -> Project:
        """Create a project."""
        row = models.ProjectModel(
            id=project.id,
            owner_id=project.owner_id,
            name=project.name,
            project_code=project.code.value,
            description=project.description,
            intended_use=project.intended_use,
            location_label=project.location_label,
            latitude=to_decimal(project.location.latitude),
            longitude=to_decimal(project.location.longitude),
            start_date=project.start_date,
            deadline_date=project.deadline_date,
            worker_count=project.worker_count,
            visibility=project.visibility,
            status=project.status,
            approval_state=project.approval_state,
            progress_pct=project.progress_pct.value,
            macro_stage=project.macro_stage,
            window_mode=project.window_mode,
            timezone=project.timezone,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_project(row)

    async def update(self, project: Project) -> Project:
        """Persist project changes.

        ``project_code`` is deliberately not updatable: it is embedded in
        device names and image filenames, so changing it would orphan history.
        """
        row = await self._session.get(models.ProjectModel, project.id)
        if row is None:
            msg = f"project {project.id} not found"
            raise LookupError(msg)
        row.name = project.name
        row.description = project.description
        row.intended_use = project.intended_use
        row.location_label = project.location_label
        row.latitude = to_decimal(project.location.latitude)
        row.longitude = to_decimal(project.location.longitude)
        row.start_date = project.start_date
        row.deadline_date = project.deadline_date
        row.worker_count = project.worker_count
        row.visibility = project.visibility
        row.status = project.status
        row.approval_state = project.approval_state
        row.progress_pct = project.progress_pct.value
        row.macro_stage = project.macro_stage
        row.window_mode = project.window_mode
        row.timezone = project.timezone
        row.last_capture_at = project.last_capture_at
        row.completed_at = project.completed_at
        row.approved_by = project.approved_by
        row.approved_at = project.approved_at
        row.inspection_notes = project.inspection_notes
        row.archived_at = project.archived_at
        await self._session.flush()
        await self._session.refresh(row)
        return to_project(row)

    async def delete(self, project_id: UUID) -> bool:
        """Delete a project and everything it owns (ON DELETE CASCADE)."""
        row = await self._session.get(models.ProjectModel, project_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True
