"""The report generation task.

Assembles everything the document needs in one pass, renders it, stores it, and
flips the row to `ready`. It runs on its own `reports` queue: rendering a
month of captures into a PDF is slow and CPU-bound, and it has nothing to do
with scoring images — sharing the `inference` queue would put every capture
arriving during a render behind it.

Failure is recorded, never swallowed. The owner pressed a button and is owed an
answer; `failed` with a reason is an answer, a row stuck at `queued` forever is
not.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from celery import shared_task

from app.core.config import get_settings
from app.domain.enums import ReportFormat, ReportStatus

__all__ = ["generate_report"]

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="reports.generate",
    max_retries=2,
    default_retry_delay=60,
    queue="reports",
)
def generate_report(self: Any, report_id: str) -> dict[str, Any]:
    """Render one requested report and attach the file to its row."""
    from app.worker.inference import _run

    return _run(_generate(self, UUID(report_id)))


async def _generate(task: Any, report_id: UUID) -> dict[str, Any]:
    """Do the work, inside an event loop."""
    from app.application.use_cases.reports import report_storage_key
    from app.infrastructure.db.session import session_scope
    from app.infrastructure.repositories import SqlAlchemyReportRepository
    from app.infrastructure.storage import get_storage

    settings = get_settings()

    async with session_scope() as session:
        reports = SqlAlchemyReportRepository(session)
        report = await reports.get(report_id)
        if report is None:
            # Deleted between enqueue and execution. Retrying will not help.
            logger.info("report %s no longer exists; nothing to do", report_id)
            return {"report_id": str(report_id), "status": "gone"}
        if report.status is ReportStatus.READY:
            # Redelivery after a worker restart is expected with `acks_late`.
            # Reports are immutable once ready, so re-rendering would replace a
            # document somebody may already have downloaded and cited.
            logger.info("report %s is already ready; skipping", report_id)
            return {"report_id": str(report_id), "status": "already_ready"}

        await reports.update(replace(report, status=ReportStatus.PROCESSING))
        await session.commit()

        try:
            data = await _collect(session, report)
        except Exception as exc:
            logger.exception("could not assemble report %s", report_id)
            await _fail(reports, report, f"could not assemble report data: {exc}")
            await session.commit()
            return {"report_id": str(report_id), "status": "failed", "reason": str(exc)}

    # Rendering happens outside the session: it is CPU-bound and takes seconds,
    # and holding a database connection open through it wastes the one resource
    # the worker has least of.
    try:
        if report.report_format is ReportFormat.PDF:
            from app.infrastructure.reports import build_pdf

            payload = build_pdf(data)
            content_type = "application/pdf"
        else:
            from app.infrastructure.reports import build_csv

            payload = build_csv(data)
            content_type = "text/csv; charset=utf-8"
    except Exception as exc:
        logger.exception("could not render report %s", report_id)
        async with session_scope() as session:
            reports = SqlAlchemyReportRepository(session)
            current = await reports.get(report_id)
            if current is not None:
                await _fail(reports, current, f"could not render report: {exc}")
            await session.commit()
        return {"report_id": str(report_id), "status": "failed", "reason": str(exc)}

    key = report_storage_key(report.project_id, report.id, report.report_format)
    try:
        await get_storage(settings).put(key, payload, content_type=content_type)
    except Exception as exc:
        # Transient: the object store may simply be unreachable, and the report
        # is cheap to render again.
        logger.warning("storage write failed for report %s: %s", report_id, exc)
        raise task.retry(exc=exc) from exc

    async with session_scope() as session:
        reports = SqlAlchemyReportRepository(session)
        current = await reports.get(report_id)
        if current is not None:
            await reports.update(
                replace(
                    current,
                    status=ReportStatus.READY,
                    storage_key=key,
                    error=None,
                    completed_at=datetime.now(UTC),
                )
            )
        await session.commit()

    from app.application.ports.events import EventType, RealtimeEvent
    from app.worker.inference import _publish

    await _publish(
        RealtimeEvent(
            type=EventType.REPORT_READY,
            project_id=report.project_id,
            payload={
                "report_id": str(report_id),
                "kind": report.kind.value,
                "format": report.report_format.value,
            },
        )
    )

    return {
        "report_id": str(report_id),
        "status": "ready",
        "format": report.report_format.value,
        "bytes": len(payload),
        "captures": len(data.captures),
    }


async def _fail(reports: Any, report: Any, reason: str) -> None:
    """Record a failure on the report row."""
    await reports.update(
        replace(
            report,
            status=ReportStatus.FAILED,
            error=reason[:500],
            completed_at=datetime.now(UTC),
        )
    )


async def _collect(session: Any, report: Any) -> Any:
    """Gather every entity the document renders, in one pass."""
    from app.domain.reporting import CaptureRow, ReportData
    from app.domain.services.reporting import ReportPeriod
    from app.domain.services.status import ProjectSignals, derive_status, explain_status
    from app.infrastructure.repositories import (
        SqlAlchemyDetectionRepository,
        SqlAlchemyDeviceRepository,
        SqlAlchemyImageRepository,
        SqlAlchemyPredictionRepository,
        SqlAlchemyProjectRepository,
        SqlAlchemyRemarkRepository,
        SqlAlchemySnapshotRepository,
        SqlAlchemyUserRepository,
    )

    projects = SqlAlchemyProjectRepository(session)
    project = await projects.get(report.project_id)
    if project is None:
        msg = f"project {report.project_id} no longer exists"
        raise LookupError(msg)

    period = ReportPeriod(
        start=report.period_start, end=report.period_end, timezone=project.timezone
    )
    start, end = period.bounds_utc()
    now = datetime.now(UTC)

    images = await SqlAlchemyImageRepository(session).list_in_window(project.id, start, end)
    predictions = await SqlAlchemyPredictionRepository(session).list_for_images(
        [image.id for image in images]
    )
    devices = await SqlAlchemyDeviceRepository(session).list_for_project(project.id)
    names = {device.id: device.device_name for device in devices}

    detections = SqlAlchemyDetectionRepository(session)
    counts: dict[str, int] = {}
    for image in images:
        summary = await detections.get_summary(image.id)
        if summary is None:
            continue
        for name, count in summary.counts.items():
            counts[name] = counts.get(name, 0) + count

    snapshots = await SqlAlchemySnapshotRepository(session).list_series(
        project.id, since=start, until=end
    )
    remarks = await SqlAlchemyRemarkRepository(session).list_for_project(project.id)
    in_period = tuple(
        remark
        for remark in remarks
        if remark.created_at is not None and start <= remark.created_at < end
    )

    signals = ProjectSignals(
        start_date=project.start_date,
        deadline_date=project.deadline_date,
        displayed_pct=project.progress_pct.as_float(),
        approval_state=project.approval_state,
        last_capture_at=project.last_capture_at,
        archived_at=project.archived_at,
    )

    return ReportData(
        project=project,
        owner=await SqlAlchemyUserRepository(session).get(project.owner_id),
        period=period,
        generated_at=now,
        snapshots=snapshots,
        captures=tuple(
            CaptureRow(
                image=image,
                prediction=predictions.get(image.id),
                device_name=names.get(image.device_id) if image.device_id else None,
            )
            for image in images
        ),
        devices=devices,
        remarks=in_period,
        status=derive_status(signals, now),
        status_reason=explain_status(signals, now),
        expected_pct=signals.expected_pct_at(period.end),
        detection_counts=counts,
    )
