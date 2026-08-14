"""The four scheduled jobs, against a real database.

The rules are proved in ``tests/unit/test_remark_rules.py``. What is proved here
is what only a database shows: that status is written **only when it moves**,
that deduplication actually suppresses the second run, that the offline sweep
distinguishes one silent camera from a wholly dark site, and that report cleanup
never orphans a stored file.

Each job's implementation takes a session, so the tests drive ``_refresh_status``
and friends through their inner coroutines rather than the Celery wrapper —
the wrapper only opens a session and disposes an engine, both covered by
``tests/unit/test_worker_session.py``.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from app.domain.entities import (
    Device,
    Image,
    Project,
    Report,
    User,
)
from app.domain.enums import (
    CameraFace,
    DeviceStatus,
    ImageSource,
    ImageStatus,
    NotificationType,
    ProfessionalRole,
    ProjectStatus,
    RemarkType,
    ReportFormat,
    ReportKind,
    ReportStatus,
    Severity,
    Visibility,
)
from app.domain.value_objects import GeoPoint, ProgressPct, ProjectCode
from app.infrastructure.repositories import (
    SqlAlchemyDeviceRepository,
    SqlAlchemyImageRepository,
    SqlAlchemyNotificationRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyRemarkRepository,
    SqlAlchemyReportRepository,
    SqlAlchemyUserRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_CODES = itertools.count()
NOW = datetime.now(UTC)


async def _owner(session: AsyncSession) -> User:
    """A user to own test projects."""
    return await SqlAlchemyUserRepository(session).add(
        User(
            id=uuid4(),
            username=f"mnt_{uuid4().hex[:8]}",
            email=f"mnt_{uuid4().hex[:8]}@gvmail.com",
            full_name="Maintenance Owner",
            professional_role=ProfessionalRole.ENGINEER,
        ),
        password_hash="x",
    )


async def _project(session: AsyncSession, owner: User, **overrides: object) -> Project:
    """A live project, healthy unless overridden."""
    values: dict[str, object] = {
        "id": uuid4(),
        "owner_id": owner.id,
        "name": "Maintenance Site",
        "code": ProjectCode(f"MN_{next(_CODES) % 100:02d}"),
        "location_label": "Naga City",
        "location": GeoPoint(13.6218, 123.1948),
        "start_date": date(2026, 6, 1),
        "deadline_date": date(2026, 12, 31),
        "visibility": Visibility.PRIVATE,
        "status": ProjectStatus.ACTIVE,
        "progress_pct": ProgressPct.from_float(30.0),
        "last_capture_at": NOW - timedelta(hours=2),
    }
    values.update(overrides)
    entity = Project(**values)  # type: ignore[arg-type]
    projects = SqlAlchemyProjectRepository(session)
    created = await projects.add(entity)
    # `add` deliberately does not persist `last_capture_at` or `archived_at` —
    # they are set by the ingest and archive paths, through `update`. A fixture
    # that needs them has to go the same way the application does.
    if entity.last_capture_at is not None or entity.archived_at is not None:
        created = await projects.update(
            replace(
                created,
                last_capture_at=entity.last_capture_at,
                archived_at=entity.archived_at,
            )
        )
    return created


async def _camera(
    session: AsyncSession,
    project: Project,
    *,
    face: CameraFace = CameraFace.FRONT_DIAGONAL,
    last_seen: datetime | None = None,
    status: DeviceStatus = DeviceStatus.ONLINE,
) -> Device:
    """A paired camera with a given liveness."""
    devices = SqlAlchemyDeviceRepository(session)
    created = await devices.add(
        Device(
            id=uuid4(),
            project_id=project.id,
            device_name=Device.build_name(project.code, face),
            face=face,
            weight=1.0,
            status=status,
        ),
        secret_encrypted="unused",
    )
    # `add` does not persist `last_seen_at` — a camera has not been seen at
    # pairing time; heartbeats set it. The fixture takes the same route.
    return await devices.update(
        replace(
            created,
            last_seen_at=last_seen if last_seen is not None else NOW - timedelta(minutes=5),
        )
    )


class TestRefreshStatus:
    """Derived status, recomputed on a schedule."""

    async def test_a_silent_project_becomes_inactive(self, session: AsyncSession) -> None:
        from app.worker.maintenance import _refresh_status

        owner = await _owner(session)
        project = await _project(session, owner, last_capture_at=NOW - timedelta(days=20))
        await session.commit()

        result = await _refresh_status(session)
        assert result["changed"] >= 1

        refreshed = await SqlAlchemyProjectRepository(session).get(project.id)
        assert refreshed is not None
        assert refreshed.status is ProjectStatus.INACTIVE

    async def test_a_project_past_its_deadline_becomes_delayed(self, session: AsyncSession) -> None:
        from app.worker.maintenance import _refresh_status

        owner = await _owner(session)
        project = await _project(session, owner, deadline_date=NOW.date() - timedelta(days=3))
        await session.commit()

        await _refresh_status(session)
        refreshed = await SqlAlchemyProjectRepository(session).get(project.id)
        assert refreshed is not None
        assert refreshed.status is ProjectStatus.DELAYED

    async def test_a_healthy_project_is_left_alone(self, session: AsyncSession) -> None:
        """Unchanged rows are not rewritten — the table would churn for nothing."""
        from app.worker.maintenance import _refresh_status

        owner = await _owner(session)
        project = await _project(session, owner)
        await session.commit()

        before = await SqlAlchemyProjectRepository(session).get(project.id)
        await _refresh_status(session)
        after = await SqlAlchemyProjectRepository(session).get(project.id)
        assert before is not None and after is not None
        assert after.status is ProjectStatus.ACTIVE
        assert after.updated_at == before.updated_at


class TestEmitRemarks:
    """Automatic remarks, written once."""

    async def test_an_inactive_project_gets_a_remark(self, session: AsyncSession) -> None:
        from app.worker.maintenance import _emit_remarks

        owner = await _owner(session)
        project = await _project(session, owner, last_capture_at=NOW - timedelta(days=20))
        await session.commit()

        await _emit_remarks(session)
        written = await SqlAlchemyRemarkRepository(session).list_for_project(project.id)
        inactivity = [r for r in written if r.remark_type is RemarkType.INACTIVITY]
        assert len(inactivity) == 1
        assert inactivity[0].author_id is None
        assert "days" in inactivity[0].message

    async def test_running_twice_writes_one_remark(self, session: AsyncSession) -> None:
        """The dedup window is the whole point of the job being re-runnable."""
        from app.worker.maintenance import _emit_remarks

        owner = await _owner(session)
        project = await _project(session, owner, last_capture_at=NOW - timedelta(days=20))
        await session.commit()

        first = await _emit_remarks(session)
        second = await _emit_remarks(session)

        written = await SqlAlchemyRemarkRepository(session).list_for_project(project.id)
        assert len([r for r in written if r.remark_type is RemarkType.INACTIVITY]) == 1
        assert first["written"] >= 1
        assert second["deduplicated"] >= 1

    async def test_a_remark_older_than_the_window_is_repeated(self, session: AsyncSession) -> None:
        """A persisting problem gets restated, or it silently drops off the page."""
        from sqlalchemy import text

        from app.worker.maintenance import _emit_remarks

        owner = await _owner(session)
        project = await _project(session, owner, last_capture_at=NOW - timedelta(days=20))
        await session.commit()

        await _emit_remarks(session)
        # Age the existing remark past the 72-hour window.
        await session.execute(
            text(
                "UPDATE remarks SET created_at = created_at - INTERVAL '5 days' "
                "WHERE project_id = :pid"
            ),
            {"pid": project.id},
        )
        await session.commit()

        await _emit_remarks(session)
        written = await SqlAlchemyRemarkRepository(session).list_for_project(project.id)
        assert len([r for r in written if r.remark_type is RemarkType.INACTIVITY]) == 2

    async def test_a_rejection_streak_is_reported(self, session: AsyncSession) -> None:
        from app.worker.maintenance import _emit_remarks

        owner = await _owner(session)
        project = await _project(session, owner)
        images = SqlAlchemyImageRepository(session)
        for n in range(3):
            await images.add(
                Image(
                    id=uuid4(),
                    project_id=project.id,
                    filename=f"{project.code.value}_{uuid4().hex[:10]}.jpg",
                    storage_key=f"projects/{project.id}/{uuid4().hex}.jpg",
                    captured_at=NOW - timedelta(minutes=10 * (3 - n)),
                    sha256=uuid4().hex * 2,
                    source=ImageSource.DEVICE,
                    status=ImageStatus.REJECTED,
                    seq_number=n + 1,
                )
            )
        await session.commit()

        await _emit_remarks(session)
        written = await SqlAlchemyRemarkRepository(session).list_for_project(project.id)
        system = [r for r in written if r.remark_type is RemarkType.SYSTEM]
        assert len(system) == 1
        assert "rejected for image quality" in system[0].message


class TestOfflineSweep:
    """Silent cameras, and wholly dark sites."""

    async def test_a_silent_camera_is_marked_offline(self, session: AsyncSession) -> None:
        from app.worker.maintenance import _sweep_devices

        owner = await _owner(session)
        project = await _project(session, owner)
        camera = await _camera(session, project, last_seen=NOW - timedelta(hours=10))
        await session.commit()

        result = await _sweep_devices(session)
        assert result["marked_offline"] >= 1

        refreshed = await SqlAlchemyDeviceRepository(session).get(camera.id)
        assert refreshed is not None
        assert refreshed.status is DeviceStatus.OFFLINE

    async def test_a_recently_seen_camera_is_untouched(self, session: AsyncSession) -> None:
        from app.worker.maintenance import _sweep_devices

        owner = await _owner(session)
        project = await _project(session, owner)
        camera = await _camera(session, project, last_seen=NOW - timedelta(hours=1))
        await session.commit()

        await _sweep_devices(session)
        refreshed = await SqlAlchemyDeviceRepository(session).get(camera.id)
        assert refreshed is not None
        assert refreshed.status is DeviceStatus.ONLINE

    async def test_a_wholly_dark_site_alerts_its_owner(self, session: AsyncSession) -> None:
        from app.worker.maintenance import _sweep_devices

        owner = await _owner(session)
        project = await _project(session, owner)
        await _camera(session, project, last_seen=NOW - timedelta(hours=60))
        await session.commit()

        result = await _sweep_devices(session)
        assert result["projects_alerted"] >= 1

        remarks = await SqlAlchemyRemarkRepository(session).list_for_project(project.id)
        offline = [r for r in remarks if "offline" in r.message]
        assert len(offline) == 1
        assert offline[0].severity is Severity.WARNING
        # Not published: a dark camera is an operational problem, not part of
        # the public story of the build.
        assert offline[0].is_public is False

        notifications = await SqlAlchemyNotificationRepository(session).list_for_user(owner.id)
        assert any(
            item.notification_type is NotificationType.DEVICE_OFFLINE for item in notifications
        )

    async def test_one_live_camera_keeps_the_site_reporting(self, session: AsyncSession) -> None:
        """A site with two cameras, one alive, is not dark."""
        from app.worker.maintenance import _sweep_devices

        owner = await _owner(session)
        project = await _project(session, owner)
        await _camera(session, project, last_seen=NOW - timedelta(hours=60))
        await _camera(
            session,
            project,
            face=CameraFace.BACK_DIAGONAL,
            last_seen=NOW - timedelta(minutes=20),
        )
        await session.commit()

        await _sweep_devices(session)
        remarks = await SqlAlchemyRemarkRepository(session).list_for_project(project.id)
        assert not [r for r in remarks if "offline" in r.message]

    async def test_the_alert_is_not_repeated_within_the_window(self, session: AsyncSession) -> None:
        from app.worker.maintenance import _sweep_devices

        owner = await _owner(session)
        project = await _project(session, owner)
        await _camera(session, project, last_seen=NOW - timedelta(hours=60))
        await session.commit()

        await _sweep_devices(session)
        await _sweep_devices(session)

        remarks = await SqlAlchemyRemarkRepository(session).list_for_project(project.id)
        assert len([r for r in remarks if "offline" in r.message]) == 1


class TestReportCleanup:
    """Retention, without orphaning files."""

    async def test_an_old_report_and_its_file_are_removed(
        self, session: AsyncSession, test_settings: object
    ) -> None:
        from sqlalchemy import text

        from app.application.use_cases.reports import report_storage_key
        from app.infrastructure.storage import get_storage
        from app.worker.maintenance import _cleanup_reports

        owner = await _owner(session)
        project = await _project(session, owner)
        reports = SqlAlchemyReportRepository(session)
        report = await reports.add(
            Report(
                id=uuid4(),
                project_id=project.id,
                requested_by=owner.id,
                kind=ReportKind.WEEKLY,
                report_format=ReportFormat.PDF,
                period_start=date(2025, 1, 1),
                period_end=date(2025, 1, 7),
            )
        )
        key = report_storage_key(project.id, report.id, ReportFormat.PDF)
        storage = get_storage(test_settings)  # type: ignore[arg-type]
        await storage.put(key, b"%PDF-1.7\nold\n%%EOF\n", content_type="application/pdf")
        await session.execute(
            text(
                "UPDATE reports SET status='ready', storage_key=:k, "
                "completed_at = now() - INTERVAL '400 days' WHERE id = :i"
            ),
            {"k": key, "i": report.id},
        )
        await session.commit()

        result = await _cleanup_reports(session)
        assert result["removed"] >= 1
        assert await reports.get(report.id) is None
        assert await storage.exists(key) is False

    async def test_a_recent_report_is_kept(
        self, session: AsyncSession, test_settings: object
    ) -> None:
        from dataclasses import replace

        from app.worker.maintenance import _cleanup_reports

        owner = await _owner(session)
        project = await _project(session, owner)
        reports = SqlAlchemyReportRepository(session)
        report = await reports.add(
            Report(
                id=uuid4(),
                project_id=project.id,
                requested_by=owner.id,
                kind=ReportKind.WEEKLY,
                report_format=ReportFormat.CSV,
                period_start=date(2026, 8, 3),
                period_end=date(2026, 8, 9),
            )
        )
        await reports.update(
            replace(report, status=ReportStatus.READY, storage_key="k", completed_at=NOW)
        )
        await session.commit()

        await _cleanup_reports(session)
        assert await reports.get(report.id) is not None
