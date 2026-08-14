"""The scheduled jobs that keep derived state honest.

Four tasks on Celery beat. Everything here is **idempotent** and safe to run
twice: a beat schedule redelivers after a restart, and a maintenance job that
double-posts is worse than one that occasionally skips.

``projects.refresh_status``  (6 h)
    Recompute ``projects.status`` from the stored signals.
``remarks.emit_system``      (6 h)
    Write the automatic remarks a project currently warrants, deduplicated.
``devices.sweep_offline``    (30 min)
    Mark silent cameras offline, and tell an owner when they have all gone dark.
``reports.cleanup_expired``  (daily)
    Delete report files past their retention window.

Status and remarks are deliberately **two jobs, not one**. Status is derived
state the system needs in order to render a list; a remark is a message to a
person. They happen to share a cadence today, and separating them means either
can be re-tuned — or paused during a noisy incident — without touching the other.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from celery import shared_task

from app.core.config import get_settings
from app.domain.enums import DeviceStatus, ImageStatus, NotificationType
from app.domain.services.remarks import DEDUPE_WINDOW_HOURS, due_remarks, offline_remark
from app.domain.services.status import ProjectSignals, derive_status

__all__ = [
    "cleanup_expired_reports",
    "emit_system_remarks",
    "refresh_project_status",
    "sweep_offline_devices",
]

logger = logging.getLogger(__name__)

#: A camera that has not been heard from for this long is shown as offline.
OFFLINE_AFTER_HOURS = 6

#: All of a project's cameras silent for this long earns a remark and a
#: notification. Longer than the offline threshold on purpose: a camera that
#: misses one scheduled capture is not news, and waking an owner for it would
#: teach them to ignore the alerts that matter.
ALL_OFFLINE_ALERT_HOURS = 48

#: How many recent captures the rejection-streak check looks back over.
_RECENT_CAPTURES = 5


@shared_task(name="projects.refresh_status", queue="reports")
def refresh_project_status() -> dict[str, Any]:
    """Recompute every live project's derived status."""
    from app.worker.inference import _run

    return _run(_in_session(_refresh_status))


@shared_task(name="remarks.emit_system", queue="reports")
def emit_system_remarks() -> dict[str, Any]:
    """Write any automatic remarks that are currently due."""
    from app.worker.inference import _run

    return _run(_in_session(_emit_remarks))


@shared_task(name="devices.sweep_offline", queue="reports")
def sweep_offline_devices() -> dict[str, Any]:
    """Mark silent cameras offline and alert on wholly dark sites."""
    from app.worker.inference import _run

    return _run(_in_session(_sweep_devices))


@shared_task(name="reports.cleanup_expired", queue="reports")
def cleanup_expired_reports() -> dict[str, Any]:
    """Delete generated reports past their retention window."""
    from app.worker.inference import _run

    return _run(_in_session(_cleanup_reports))


async def _in_session(job: Any) -> dict[str, Any]:
    """Run one job in its own transaction, committing on success.

    The jobs take a session rather than opening one so that a test can drive
    them inside its own rolled-back transaction. Owning the session here keeps
    that seam from leaking into the task definitions.
    """
    from app.infrastructure.db.session import session_scope

    async with session_scope() as session:
        result: dict[str, Any] = await job(session)
        await session.commit()
        return result


# ---------------------------------------------------------------------------
# implementations
# ---------------------------------------------------------------------------


def _signals_for(project: Any) -> ProjectSignals:
    """Build the status inputs from a project row."""
    return ProjectSignals(
        start_date=project.start_date,
        deadline_date=project.deadline_date,
        displayed_pct=project.progress_pct.as_float(),
        approval_state=project.approval_state,
        last_capture_at=project.last_capture_at,
        archived_at=project.archived_at,
    )


async def _refresh_status(session: Any) -> dict[str, Any]:
    """Recompute and persist derived status where it has drifted."""
    from app.infrastructure.repositories import SqlAlchemyProjectRepository

    now = datetime.now(UTC)
    changed = 0

    projects = SqlAlchemyProjectRepository(session)
    live = await projects.list_for_maintenance()
    for project in live:
        current = derive_status(_signals_for(project), now)
        if current is project.status:
            # Written only when it moves. The column exists to keep project
            # *lists* cheap, and rewriting every row every six hours would
            # churn the table and its indexes for no reader's benefit.
            continue
        await projects.update(replace(project, status=current))
        changed += 1
        logger.info("project %s status %s -> %s", project.code.value, project.status, current)

    return {"task": "projects.refresh_status", "examined": len(live), "changed": changed}


async def _emit_remarks(session: Any) -> dict[str, Any]:
    """Write due remarks, skipping any said recently."""
    from app.domain.entities import Remark
    from app.infrastructure.repositories import (
        SqlAlchemyImageRepository,
        SqlAlchemyProjectRepository,
        SqlAlchemyRemarkRepository,
    )

    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=DEDUPE_WINDOW_HOURS)
    written = 0
    skipped = 0

    projects = SqlAlchemyProjectRepository(session)
    remarks = SqlAlchemyRemarkRepository(session)
    images = SqlAlchemyImageRepository(session)
    live = await projects.list_for_maintenance()

    for project in live:
        streak = await _rejection_streak(images, project.id)
        for due in due_remarks(_signals_for(project), now, consecutive_rejections=streak):
            existing = await remarks.recent_of_type(project.id, due.remark_type.value, cutoff)
            if existing is not None:
                skipped += 1
                continue
            await remarks.add(
                Remark(
                    id=uuid4(),
                    project_id=project.id,
                    author_id=None,
                    remark_type=due.remark_type,
                    severity=due.severity,
                    message=due.message,
                    # Visible on the public project page: a delay an owner
                    # published a site for is part of that site's story.
                    is_public=True,
                )
            )
            written += 1

    return {
        "task": "remarks.emit_system",
        "examined": len(live),
        "written": written,
        "deduplicated": skipped,
    }


async def _rejection_streak(images: Any, project_id: UUID) -> int:
    """How many of the newest captures the quality gate refused, in a row."""
    page = await images.list_for_project(project_id, limit=_RECENT_CAPTURES)
    streak = 0
    for image in page.items:  # newest first
        if image.status is not ImageStatus.REJECTED:
            break
        streak += 1
    return streak


async def _sweep_devices(session: Any) -> dict[str, Any]:
    """Mark silent cameras offline; alert when a whole site goes dark."""
    from app.domain.entities import Notification, Remark
    from app.infrastructure.repositories import (
        SqlAlchemyDeviceRepository,
        SqlAlchemyNotificationRepository,
        SqlAlchemyProjectRepository,
        SqlAlchemyRemarkRepository,
    )

    now = datetime.now(UTC)
    offline_cutoff = now - timedelta(hours=OFFLINE_AFTER_HOURS)
    alert_cutoff = now - timedelta(hours=ALL_OFFLINE_ALERT_HOURS)
    dedupe_cutoff = now - timedelta(hours=DEDUPE_WINDOW_HOURS)
    marked = 0
    alerted = 0

    devices = SqlAlchemyDeviceRepository(session)
    projects = SqlAlchemyProjectRepository(session)
    remarks = SqlAlchemyRemarkRepository(session)
    notifications = SqlAlchemyNotificationRepository(session)

    for device in await devices.list_stale(offline_cutoff):
        if device.status is DeviceStatus.OFFLINE:
            continue
        await devices.update(replace(device, status=DeviceStatus.OFFLINE))
        marked += 1

    # Then the per-project question, which is a different one: a site with
    # one silent camera out of three is still reporting.
    for project in await projects.list_for_maintenance():
        paired = [
            device
            for device in await devices.list_for_project(project.id)
            if device.status is not DeviceStatus.REVOKED
        ]
        if not paired:
            continue
        seen = [device.last_seen_at for device in paired if device.last_seen_at]
        if len(seen) != len(paired) or max(seen) >= alert_cutoff:
            continue

        if await remarks.recent_of_type(project.id, "system", dedupe_cutoff) is not None:
            continue
        hours = int((now - max(seen)).total_seconds() // 3600)
        due = offline_remark(hours, camera_count=len(paired))
        await remarks.add(
            Remark(
                id=uuid4(),
                project_id=project.id,
                author_id=None,
                remark_type=due.remark_type,
                severity=due.severity,
                message=due.message,
                is_public=False,
            )
        )
        await notifications.add(
            Notification(
                id=uuid4(),
                user_id=project.owner_id,
                notification_type=NotificationType.DEVICE_OFFLINE,
                title=f"{project.code.value}: all cameras offline",
                body=due.message,
                project_id=project.id,
            )
        )
        alerted += 1

    return {
        "task": "devices.sweep_offline",
        "marked_offline": marked,
        "projects_alerted": alerted,
    }


async def _cleanup_reports(session: Any) -> dict[str, Any]:
    """Delete stored report files past the retention window, then their rows."""
    from app.infrastructure.repositories import SqlAlchemyReportRepository
    from app.infrastructure.storage import get_storage

    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=settings.report_retention_days)
    storage = get_storage(settings)
    removed = 0

    reports = SqlAlchemyReportRepository(session)
    for report in await reports.list_expired(cutoff):
        if report.storage_key:
            try:
                await storage.delete(report.storage_key)
            except Exception:
                # Leave the row alone so the next run tries again. Deleting
                # it here would orphan the blob permanently — nothing else
                # records that key.
                logger.warning("could not delete %s; keeping the row", report.storage_key)
                continue
        await reports.delete(report.id)
        removed += 1

    return {
        "task": "reports.cleanup_expired",
        "removed": removed,
        "retention_days": settings.report_retention_days,
    }
