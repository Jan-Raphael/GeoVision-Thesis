"""SQLAlchemy implementations for remarks, assets, reports, models, notifications."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select, update

from app.domain.entities import (
    AIModel,
    ContactMessage,
    Notification,
    ReferenceAsset,
    Remark,
    Report,
)
from app.domain.enums import ModelKind, ReportStatus
from app.infrastructure.db import models
from app.infrastructure.repositories._result import affected_rows
from app.infrastructure.repositories.mappers import (
    to_ai_model,
    to_contact_message,
    to_notification,
    to_reference_asset,
    to_remark,
    to_report,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SqlAlchemyAIModelRepository",
    "SqlAlchemyContactMessageRepository",
    "SqlAlchemyNotificationRepository",
    "SqlAlchemyReferenceAssetRepository",
    "SqlAlchemyRemarkRepository",
    "SqlAlchemyReportRepository",
]


class SqlAlchemyRemarkRepository:
    """Project remarks, backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def get(self, remark_id: UUID) -> Remark | None:
        """Return a remark by id."""
        row = await self._session.get(models.RemarkModel, remark_id)
        return to_remark(row) if row else None

    async def list_for_project(
        self, project_id: UUID, *, public_only: bool = False, limit: int = 50
    ) -> tuple[Remark, ...]:
        """Remarks newest first. ``public_only`` is the anonymous-caller path."""
        stmt = select(models.RemarkModel).where(models.RemarkModel.project_id == project_id)
        if public_only:
            stmt = stmt.where(models.RemarkModel.is_public.is_(True))
        stmt = stmt.order_by(models.RemarkModel.created_at.desc()).limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_remark(row) for row in rows)

    async def recent_of_type(
        self, project_id: UUID, remark_type: str, since: datetime
    ) -> Remark | None:
        """Most recent remark of a type, used to deduplicate system remarks.

        Prevents the maintenance job from re-posting "no captures in 16 days"
        on every run.
        """
        stmt = (
            select(models.RemarkModel)
            .where(
                models.RemarkModel.project_id == project_id,
                models.RemarkModel.remark_type == remark_type,
                models.RemarkModel.created_at >= since,
            )
            .order_by(models.RemarkModel.created_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalars().first()
        return to_remark(row) if row else None

    async def add(self, remark: Remark) -> Remark:
        """Create a remark."""
        row = models.RemarkModel(
            id=remark.id,
            project_id=remark.project_id,
            author_id=remark.author_id,
            remark_type=remark.remark_type,
            severity=remark.severity,
            message=remark.message,
            is_public=remark.is_public,
            effective_from=remark.effective_from,
            effective_to=remark.effective_to,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_remark(row)

    async def update(self, remark: Remark) -> Remark:
        """Edit a remark."""
        row = await self._session.get(models.RemarkModel, remark.id)
        if row is None:
            msg = f"remark {remark.id} not found"
            raise LookupError(msg)
        row.message = remark.message
        row.severity = remark.severity
        row.is_public = remark.is_public
        row.effective_from = remark.effective_from
        row.effective_to = remark.effective_to
        await self._session.flush()
        await self._session.refresh(row)
        return to_remark(row)

    async def delete(self, remark_id: UUID) -> bool:
        """Delete a remark."""
        row = await self._session.get(models.RemarkModel, remark_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


class SqlAlchemyReferenceAssetRepository:
    """Blueprints, renders, and reference documents."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def get(self, asset_id: UUID) -> ReferenceAsset | None:
        """Return an asset by id."""
        row = await self._session.get(models.ReferenceAssetModel, asset_id)
        return to_reference_asset(row) if row else None

    async def list_for_project(
        self, project_id: UUID, *, public_only: bool = False
    ) -> tuple[ReferenceAsset, ...]:
        """Assets attached to a project."""
        stmt = select(models.ReferenceAssetModel).where(
            models.ReferenceAssetModel.project_id == project_id
        )
        if public_only:
            stmt = stmt.where(models.ReferenceAssetModel.is_public.is_(True))
        stmt = stmt.order_by(models.ReferenceAssetModel.created_at.desc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_reference_asset(row) for row in rows)

    async def add(self, asset: ReferenceAsset) -> ReferenceAsset:
        """Record an uploaded asset."""
        row = models.ReferenceAssetModel(
            id=asset.id,
            project_id=asset.project_id,
            uploaded_by=asset.uploaded_by,
            kind=asset.kind,
            storage_key=asset.storage_key,
            original_filename=asset.original_filename,
            mime_type=asset.mime_type,
            size_bytes=asset.size_bytes,
            notes=asset.notes,
            is_public=asset.is_public,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_reference_asset(row)

    async def delete(self, asset_id: UUID) -> bool:
        """Delete an asset."""
        row = await self._session.get(models.ReferenceAssetModel, asset_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


class SqlAlchemyReportRepository:
    """Generated PDF/CSV exports."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def get(self, report_id: UUID) -> Report | None:
        """Return a report by id."""
        row = await self._session.get(models.ReportModel, report_id)
        return to_report(row) if row else None

    async def list_for_project(self, project_id: UUID, *, limit: int = 20) -> tuple[Report, ...]:
        """Reports for a project, newest first."""
        stmt = (
            select(models.ReportModel)
            .where(models.ReportModel.project_id == project_id)
            .order_by(models.ReportModel.requested_at.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_report(row) for row in rows)

    async def add(self, report: Report) -> Report:
        """Queue a report."""
        row = models.ReportModel(
            id=report.id,
            project_id=report.project_id,
            requested_by=report.requested_by,
            kind=report.kind,
            report_format=report.report_format,
            period_start=report.period_start,
            period_end=report.period_end,
            status=report.status,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_report(row)

    async def list_expired(self, before: datetime, *, limit: int = 200) -> tuple[Report, ...]:
        """Ready reports older than *before* — the daily cleanup's input.

        Returns the rows rather than deleting them, because the file in object
        storage has to go too and only the caller has a storage client. A row
        deleted here with its blob left behind is an orphan nobody will ever
        find again.
        """
        stmt = (
            select(models.ReportModel)
            .where(
                models.ReportModel.status == ReportStatus.READY,
                models.ReportModel.completed_at.is_not(None),
                models.ReportModel.completed_at < before,
            )
            .order_by(models.ReportModel.completed_at)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_report(row) for row in rows)

    async def delete(self, report_id: UUID) -> bool:
        """Remove a report row. The caller deletes its stored file first."""
        row = await self._session.get(models.ReportModel, report_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def update(self, report: Report) -> Report:
        """Update job status or attach the finished file."""
        row = await self._session.get(models.ReportModel, report.id)
        if row is None:
            msg = f"report {report.id} not found"
            raise LookupError(msg)
        row.status = report.status
        row.storage_key = report.storage_key
        row.error = report.error
        row.completed_at = report.completed_at
        await self._session.flush()
        await self._session.refresh(row)
        return to_report(row)


class SqlAlchemyAIModelRepository:
    """The trained-model registry."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def get(self, model_id: UUID) -> AIModel | None:
        """Return a model by id."""
        row = await self._session.get(models.AIModelModel, model_id)
        return to_ai_model(row) if row else None

    async def get_active(self, kind: ModelKind) -> AIModel | None:
        """The currently serving model of a kind, if any."""
        stmt = select(models.AIModelModel).where(
            models.AIModelModel.kind == kind,
            models.AIModelModel.is_active.is_(True),
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_ai_model(row) if row else None

    async def list_all(self) -> tuple[AIModel, ...]:
        """Every registered model — the thesis comparison table."""
        stmt = select(models.AIModelModel).order_by(
            models.AIModelModel.kind, models.AIModelModel.created_at.desc()
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_ai_model(row) for row in rows)

    async def add(self, model: AIModel) -> AIModel:
        """Register a model."""
        row = models.AIModelModel(
            id=model.id,
            name=model.name,
            kind=model.kind,
            architecture=model.architecture,
            version=model.version,
            framework=model.framework,
            weights_key=model.weights_key,
            class_names=list(model.class_names),
            input_size=model.input_size,
            metrics=model.metrics,
            is_active=model.is_active,
            trained_at=model.trained_at,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_ai_model(row)

    async def set_active(self, model_id: UUID) -> AIModel:
        """Activate a model, deactivating the previous one of the same kind.

        Both statements run in the caller's transaction. A partial unique index
        allows only one active model per kind, so deactivating first is not
        optional — doing it the other way round violates the constraint.
        """
        row = await self._session.get(models.AIModelModel, model_id)
        if row is None:
            msg = f"model {model_id} not found"
            raise LookupError(msg)

        await self._session.execute(
            update(models.AIModelModel)
            .where(
                models.AIModelModel.kind == row.kind,
                models.AIModelModel.id != model_id,
                models.AIModelModel.is_active.is_(True),
            )
            .values(is_active=False)
        )
        row.is_active = True
        await self._session.flush()
        await self._session.refresh(row)
        return to_ai_model(row)


class SqlAlchemyNotificationRepository:
    """In-app notifications."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def list_for_user(
        self, user_id: UUID, *, unread_only: bool = False, limit: int = 50
    ) -> tuple[Notification, ...]:
        """Notifications for a user, newest first."""
        stmt = select(models.NotificationModel).where(models.NotificationModel.user_id == user_id)
        if unread_only:
            stmt = stmt.where(models.NotificationModel.read_at.is_(None))
        stmt = stmt.order_by(models.NotificationModel.created_at.desc()).limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_notification(row) for row in rows)

    async def count_unread(self, user_id: UUID) -> int:
        """Unread count for the bell badge."""
        stmt = (
            select(func.count())
            .select_from(models.NotificationModel)
            .where(
                models.NotificationModel.user_id == user_id,
                models.NotificationModel.read_at.is_(None),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def add(self, notification: Notification) -> Notification:
        """Create a notification."""
        row = models.NotificationModel(
            id=notification.id,
            user_id=notification.user_id,
            project_id=notification.project_id,
            notification_type=notification.notification_type,
            title=notification.title,
            body=notification.body,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_notification(row)

    async def mark_read(self, notification_id: UUID, read_at: datetime) -> bool:
        """Mark one notification read."""
        stmt = (
            update(models.NotificationModel)
            .where(
                models.NotificationModel.id == notification_id,
                models.NotificationModel.read_at.is_(None),
            )
            .values(read_at=read_at)
        )
        result = await self._session.execute(stmt)
        return bool(affected_rows(result))


class SqlAlchemyContactMessageRepository:
    """Public Contact Us submissions."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def add(self, message: ContactMessage) -> ContactMessage:
        """Store a submitted message."""
        row = models.ContactMessageModel(
            id=message.id,
            name=message.name,
            email=message.email,
            subject=message.subject,
            message=message.message,
            ip_address=message.ip_address,
            user_agent=message.user_agent,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_contact_message(row)

    async def list_unhandled(self, *, limit: int = 50) -> tuple[ContactMessage, ...]:
        """Messages nobody has dealt with yet, oldest first."""
        stmt = (
            select(models.ContactMessageModel)
            .where(models.ContactMessageModel.handled_at.is_(None))
            .order_by(models.ContactMessageModel.created_at)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_contact_message(row) for row in rows)
