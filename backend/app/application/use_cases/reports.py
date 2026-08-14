"""Requesting, tracking, and downloading reports.

Generation is **asynchronous**: `POST` returns `202` with a report id, a worker
renders the file, and the caller polls or waits for a WebSocket event. That is
not ceremony — a monthly PDF walks every capture in the period, renders three
figures, and embeds them, which is unbounded work that has no business inside an
HTTP request.

Reports are **immutable once ready**. Regenerating creates a new row rather than
overwriting one, so "what did we report, and when?" stays answerable. For a
document that may be shown to a client, that audit trail is the point.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import uuid4

from app.application.ports.task_queue import QUEUE_REPORTS, TASK_GENERATE_REPORT
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.domain.entities import Report
from app.domain.enums import ReportFormat, ReportKind, ReportStatus
from app.domain.services.reporting import resolve_period

if TYPE_CHECKING:
    from datetime import date
    from uuid import UUID

    from app.application.ports.storage import ObjectStorage
    from app.application.ports.task_queue import TaskQueue
    from app.core.clock import Clock
    from app.domain.entities import Project
    from app.domain.repositories import ProjectRepository, ReportRepository

__all__ = [
    "DownloadReport",
    "GetReport",
    "ListReports",
    "ReportDownload",
    "RequestReport",
    "report_storage_key",
]

#: How long a download link stays valid. Long enough to click from an email or a
#: notification, short enough that a forwarded URL is not an open door to a
#: private project's report.
DOWNLOAD_URL_TTL_SECONDS = 900


def report_storage_key(project_id: UUID, report_id: UUID, report_format: ReportFormat) -> str:
    """Key for a generated report.

    Layout mirrors `Naming-Conventions.md` §5. Built from ids only — no
    user-supplied text reaches a storage key.
    """
    return f"projects/{project_id}/reports/{report_id}.{report_format.value}"


@dataclass(frozen=True, slots=True)
class ReportDownload:
    """A signed URL and the filename to save it under."""

    url: str
    filename: str
    report_format: ReportFormat


class RequestReport:
    """Queue a report for generation."""

    def __init__(
        self,
        projects: ProjectRepository,
        reports: ReportRepository,
        queue: TaskQueue,
        *,
        clock: Clock,
    ) -> None:
        """Bind the repositories, the queue, and the time source."""
        self._projects = projects
        self._reports = reports
        self._queue = queue
        self._clock = clock

    async def execute(
        self,
        project_id: UUID,
        *,
        requested_by: UUID,
        kind: ReportKind,
        report_format: ReportFormat,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> Report:
        """Resolve the period, record the job, and hand it to a worker.

        The period is resolved **here rather than in the worker** so an invalid
        request fails synchronously with a 400 the caller can act on, instead of
        becoming a `failed` row they have to go and look at.

        Raises:
            NotFoundError: If the project no longer exists.
            ValidationFailedError: If a custom period is incomplete, inverted, or
                too long.
        """
        project = await self._projects.get(project_id)
        if project is None:
            msg = "Project not found."
            raise NotFoundError(msg)

        try:
            period = resolve_period(
                kind,
                now=self._clock.now(),
                timezone=project.timezone,
                period_start=period_start,
                period_end=period_end,
            )
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc

        report = await self._reports.add(
            Report(
                id=uuid4(),
                project_id=project_id,
                requested_by=requested_by,
                kind=kind,
                report_format=report_format,
                period_start=period.start,
                period_end=period.end,
                status=ReportStatus.QUEUED,
            )
        )
        await self._queue.enqueue(
            TASK_GENERATE_REPORT, {"report_id": str(report.id)}, queue=QUEUE_REPORTS
        )
        return report


class GetReport:
    """Read one report's status."""

    def __init__(self, reports: ReportRepository) -> None:
        """Bind the report repository."""
        self._reports = reports

    async def execute(self, report_id: UUID, project_id: UUID) -> Report:
        """Return the report.

        Raises:
            NotFoundError: If it does not exist **or** belongs to another
                project — indistinguishable on purpose, so a report id cannot be
                probed from outside the project that owns it.
        """
        report = await self._reports.get(report_id)
        if report is None or report.project_id != project_id:
            msg = "Report not found."
            raise NotFoundError(msg)
        return report


class ListReports:
    """A project's recent reports."""

    def __init__(self, reports: ReportRepository) -> None:
        """Bind the report repository."""
        self._reports = reports

    async def execute(self, project_id: UUID, *, limit: int = 20) -> tuple[Report, ...]:
        """Return reports, newest first."""
        return await self._reports.list_for_project(project_id, limit=limit)


class DownloadReport:
    """Hand back a short-lived link to a finished report."""

    def __init__(self, reports: ReportRepository, storage: ObjectStorage) -> None:
        """Bind the report repository and object storage."""
        self._reports = reports
        self._storage = storage

    async def execute(self, report_id: UUID, project: Project) -> ReportDownload:
        """Return a signed URL for a ready report.

        Permission is re-checked by the caller's route guard **at download
        time**, not merely when the report was requested: membership can be
        revoked between the two, and a link that outlives someone's access is a
        leak with a timestamp on it.

        Raises:
            NotFoundError: If the report is not this project's.
            ConflictError: If it is not ready yet, or failed.
        """
        report = await self._reports.get(report_id)
        if report is None or report.project_id != project.id:
            msg = "Report not found."
            raise NotFoundError(msg)
        if report.status is not ReportStatus.READY or not report.storage_key:
            raise ConflictError(
                "This report is not ready to download.",
                details={"status": report.status.value, "error": report.error},
            )

        url = await self._storage.signed_url(
            report.storage_key, expires_in=DOWNLOAD_URL_TTL_SECONDS
        )
        stamp = f"{report.period_start:%Y%m%d}-{report.period_end:%Y%m%d}"
        return ReportDownload(
            url=url,
            filename=f"{project.code.value}_{report.kind.value}_{stamp}.{report.report_format.value}",
            report_format=report.report_format,
        )


def mark_failed(report: Report, reason: str, *, at: object) -> Report:
    """Return *report* marked failed with a reason.

    A failed report keeps its row rather than disappearing: the owner pressed a
    button and is owed an answer, and "failed: storage unreachable" is an answer.
    """
    from datetime import datetime

    completed = at if isinstance(at, datetime) else None
    return replace(report, status=ReportStatus.FAILED, error=reason[:500], completed_at=completed)
