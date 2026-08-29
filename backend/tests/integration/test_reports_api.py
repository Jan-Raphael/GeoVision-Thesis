"""Requesting, tracking, and downloading reports.

The builders are proved in ``tests/unit/test_reporting.py``. What is proved here
is the part only a database shows: that a request resolves the right period and
records a job, that authority is enforced at both ends (request *and* download),
and that the worker's assembly step gathers exactly the period's captures — the
step where a timezone mistake would silently pull the wrong days.
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from app.core.config import Settings, get_settings
from app.core.security import issue_access_token
from app.domain.entities import (
    AIModel,
    Device,
    Image,
    Prediction,
    ProgressSnapshot,
    Project,
    ProjectMember,
    Report,
    User,
)
from app.domain.enums import (
    CameraFace,
    ImageSource,
    ImageStatus,
    MacroStage,
    MembershipRole,
    MembershipStatus,
    ModelKind,
    ProfessionalRole,
    ReportFormat,
    ReportKind,
    ReportStatus,
    Visibility,
)
from app.domain.value_objects import Confidence, GeoPoint, ProgressPct, ProjectCode
from app.infrastructure.repositories import (
    SqlAlchemyAIModelRepository,
    SqlAlchemyDeviceRepository,
    SqlAlchemyImageRepository,
    SqlAlchemyPredictionRepository,
    SqlAlchemyProjectMemberRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyReportRepository,
    SqlAlchemySnapshotRepository,
    SqlAlchemyUserRepository,
)

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

API = "/api/v1"
MANILA = "Asia/Manila"
_CODES = itertools.count()


class Site:
    """A project with a week of captures, owned by a logged-in user."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind repositories to the test session."""
        self.session = session
        self.projects = SqlAlchemyProjectRepository(session)
        self.reports = SqlAlchemyReportRepository(session)
        self.members = SqlAlchemyProjectMemberRepository(session)
        self.owner: User
        self.project: Project
        self.model_id = uuid4()

    async def setup(self, *, with_captures: bool = True) -> Site:
        """Create the owner, project, camera, and optionally a week of data."""
        users = SqlAlchemyUserRepository(self.session)
        self.owner = await users.add(
            User(
                id=uuid4(),
                username=f"rep_{uuid4().hex[:8]}",
                email=f"rep_{uuid4().hex[:8]}@gvmail.com",
                full_name="Report Owner",
                professional_role=ProfessionalRole.ENGINEER,
            ),
            password_hash="x",
        )
        self.project = await self.projects.add(
            Project(
                id=uuid4(),
                owner_id=self.owner.id,
                name="Report Site",
                code=ProjectCode(f"RP_{next(_CODES) % 100:02d}"),
                location_label="Naga City",
                location=GeoPoint(13.6218, 123.1948),
                start_date=date(2026, 6, 1),
                deadline_date=date(2026, 12, 31),
                visibility=Visibility.PRIVATE,
                timezone=MANILA,
            )
        )
        await self.members.add(
            ProjectMember(
                id=uuid4(),
                project_id=self.project.id,
                user_id=self.owner.id,
                membership_role=MembershipRole.OWNER,
                membership_status=MembershipStatus.ACCEPTED,
            )
        )
        # Predictions carry a model_id FK; exactly one model may be active per
        # kind system-wide, so sites created in the same test share it.
        models = SqlAlchemyAIModelRepository(self.session)
        active = await models.get_active(ModelKind.CLASSIFIER)
        if active is None:
            active = await models.add(
                AIModel(
                    id=self.model_id,
                    name="stub-classifier",
                    kind=ModelKind.CLASSIFIER,
                    architecture="stub",
                    version="stub-v1",
                    class_names=("Walls",),
                    input_size=224,
                    is_active=True,
                )
            )
        self.model_id = active.id

        if with_captures:
            await self._add_week()
        return self

    async def _add_week(self) -> None:
        """Two captures a day across 3-9 August, plus daily snapshots."""
        device = await SqlAlchemyDeviceRepository(self.session).add(
            Device(
                id=uuid4(),
                project_id=self.project.id,
                device_name=Device.build_name(self.project.code, CameraFace.FRONT_DIAGONAL),
                face=CameraFace.FRONT_DIAGONAL,
                weight=1.0,
            ),
            secret_encrypted="unused",
        )
        images = SqlAlchemyImageRepository(self.session)
        predictions = SqlAlchemyPredictionRepository(self.session)
        snapshots = SqlAlchemySnapshotRepository(self.session)

        for n in range(7):
            day = datetime(2026, 8, 3, 4, 0, tzinfo=UTC) + timedelta(days=n)
            pct = 30.0 + n
            await snapshots.upsert(
                ProgressSnapshot(
                    id=uuid4(),
                    project_id=self.project.id,
                    window_start=day,
                    window_end=day + timedelta(days=1),
                    raw_pct=ProgressPct.from_float(pct),
                    ema_pct=ProgressPct.from_float(pct),
                    displayed_pct=ProgressPct.from_float(pct),
                    macro_stage=MacroStage.FRAMING,
                    eligible_image_count=2,
                    device_weights={device.device_name: 1.0},
                )
            )
            for seq in (1, 2):
                image = await images.add(
                    Image(
                        id=uuid4(),
                        project_id=self.project.id,
                        device_id=device.id,
                        filename=f"{self.project.code.value}_{uuid4().hex[:10]}.jpg",
                        storage_key=f"projects/{self.project.id}/{uuid4().hex}.jpg",
                        captured_at=day + timedelta(hours=seq),
                        sha256=uuid4().hex * 2,
                        source=ImageSource.DEVICE,
                        status=ImageStatus.INFERRED,
                        seq_number=seq,
                        location=GeoPoint(13.6218, 123.1948),
                    )
                )
                await predictions.add(
                    Prediction(
                        id=uuid4(),
                        image_id=image.id,
                        model_id=self.model_id,
                        fine_class_index=1,
                        fine_class="Structural",
                        confidence=Confidence.from_float(0.91),
                        macro_stage=MacroStage.FRAMING,
                        raw_progress_pct=ProgressPct.from_float(40.0),
                    )
                )

    async def add_member(self, role: MembershipRole) -> User:
        """Add an accepted collaborator with *role*."""
        user = await SqlAlchemyUserRepository(self.session).add(
            User(
                id=uuid4(),
                username=f"col_{uuid4().hex[:8]}",
                email=f"col_{uuid4().hex[:8]}@gvmail.com",
                full_name="Collaborator",
                professional_role=ProfessionalRole.ENGINEER,
            ),
            password_hash="x",
        )
        await self.members.add(
            ProjectMember(
                id=uuid4(),
                project_id=self.project.id,
                user_id=user.id,
                membership_role=role,
                membership_status=MembershipStatus.ACCEPTED,
            )
        )
        return user


@pytest.fixture
async def site(session: AsyncSession) -> Site:
    """A project with a week of captures."""
    return await Site(session).setup()


def _settings_of(app: FastAPI) -> Settings:
    """The settings this app was built with."""
    return app.dependency_overrides[get_settings]()


def _token(app: FastAPI, user: User) -> dict[str, str]:
    """Mint an access token for *user*."""
    access, _ = issue_access_token(user.id, _settings_of(app))
    return {"Authorization": f"Bearer {access}"}


class TestRequestReport:
    """Queueing a report."""

    async def test_weekly_request_is_accepted_and_resolves_the_period(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        response = await client.post(
            f"{API}/projects/{site.project.id}/reports",
            headers=_token(app, site.owner),
            json={"kind": "weekly", "report_format": "pdf"},
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == ReportStatus.QUEUED.value
        # Resolved server-side, and always a complete Monday-Sunday.
        start = date.fromisoformat(body["period_start"])
        end = date.fromisoformat(body["period_end"])
        assert start.weekday() == 0
        assert (end - start).days == 6

    async def test_employee_may_generate_reports(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """`report:generate` starts at employee — the lowest role that gets it."""
        employee = await site.add_member(MembershipRole.EMPLOYEE)
        response = await client.post(
            f"{API}/projects/{site.project.id}/reports",
            headers=_token(app, employee),
            json={"kind": "weekly", "report_format": "csv"},
        )
        assert response.status_code == 202, response.text

    async def test_viewer_may_not(self, client: AsyncClient, app: FastAPI, site: Site) -> None:
        viewer = await site.add_member(MembershipRole.VIEWER)
        response = await client.post(
            f"{API}/projects/{site.project.id}/reports",
            headers=_token(app, viewer),
            json={"kind": "weekly", "report_format": "pdf"},
        )
        assert response.status_code == 403

    async def test_custom_without_dates_is_rejected(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        response = await client.post(
            f"{API}/projects/{site.project.id}/reports",
            headers=_token(app, site.owner),
            json={"kind": "custom", "report_format": "pdf"},
        )
        assert response.status_code == 422

    async def test_dates_on_a_weekly_report_are_rejected(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """Silently ignoring them would be worse than refusing them."""
        response = await client.post(
            f"{API}/projects/{site.project.id}/reports",
            headers=_token(app, site.owner),
            json={
                "kind": "weekly",
                "report_format": "pdf",
                "period_start": "2026-08-03",
                "period_end": "2026-08-09",
            },
        )
        assert response.status_code == 422

    async def test_an_over_long_custom_period_fails_synchronously(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """A 400 the caller can act on, not a `failed` row they must go and find."""
        response = await client.post(
            f"{API}/projects/{site.project.id}/reports",
            headers=_token(app, site.owner),
            json={
                "kind": "custom",
                "report_format": "pdf",
                "period_start": "2024-01-01",
                "period_end": "2026-01-01",
            },
        )
        assert response.status_code == 400
        assert "maximum" in response.json()["error"]["message"]


class TestTrackAndList:
    """Polling and listing."""

    async def test_lists_and_reads_back_a_requested_report(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        auth = _token(app, site.owner)
        created = await client.post(
            f"{API}/projects/{site.project.id}/reports",
            headers=auth,
            json={"kind": "monthly", "report_format": "csv"},
        )
        report_id = created.json()["id"]

        listed = await client.get(f"{API}/projects/{site.project.id}/reports", headers=auth)
        assert listed.status_code == 200, listed.text
        assert report_id in [item["id"] for item in listed.json()["reports"]]

        single = await client.get(
            f"{API}/projects/{site.project.id}/reports/{report_id}", headers=auth
        )
        assert single.status_code == 200
        assert single.json()["report_format"] == "csv"

    async def test_a_report_from_another_project_is_not_found(
        self, client: AsyncClient, app: FastAPI, site: Site, session: AsyncSession
    ) -> None:
        other = await Site(session).setup(with_captures=False)
        created = await client.post(
            f"{API}/projects/{other.project.id}/reports",
            headers=_token(app, other.owner),
            json={"kind": "weekly", "report_format": "pdf"},
        )
        response = await client.get(
            f"{API}/projects/{site.project.id}/reports/{created.json()['id']}",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 404


class TestDownload:
    """Downloading is gated on readiness *and* on current permission."""

    async def test_a_queued_report_cannot_be_downloaded(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """409, not 404 — it exists, it is simply not finished."""
        auth = _token(app, site.owner)
        created = await client.post(
            f"{API}/projects/{site.project.id}/reports",
            headers=auth,
            json={"kind": "weekly", "report_format": "pdf"},
        )
        response = await client.get(
            f"{API}/projects/{site.project.id}/reports/{created.json()['id']}/download",
            headers=auth,
        )
        assert response.status_code == 409
        assert response.json()["error"]["details"]["status"] == "queued"

    async def test_a_ready_report_yields_a_signed_url(
        self, client: AsyncClient, app: FastAPI, site: Site, session: AsyncSession
    ) -> None:
        from dataclasses import replace

        from app.application.use_cases.reports import report_storage_key
        from app.infrastructure.storage import get_storage

        report = await site.reports.add(
            Report(
                id=uuid4(),
                project_id=site.project.id,
                requested_by=site.owner.id,
                kind=ReportKind.WEEKLY,
                report_format=ReportFormat.PDF,
                period_start=date(2026, 8, 3),
                period_end=date(2026, 8, 9),
            )
        )
        key = report_storage_key(site.project.id, report.id, ReportFormat.PDF)
        await get_storage(_settings_of(app)).put(
            key, b"%PDF-1.7\nstub\n%%EOF\n", content_type="application/pdf"
        )
        await site.reports.update(
            replace(
                report,
                status=ReportStatus.READY,
                storage_key=key,
                completed_at=datetime.now(UTC),
            )
        )

        response = await client.get(
            f"{API}/projects/{site.project.id}/reports/{report.id}/download",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["url"]
        assert body["filename"].startswith(site.project.code.value)
        assert body["filename"].endswith(".pdf")

    async def test_a_viewer_cannot_download(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """Permission is re-checked at download time, not just at request time."""
        auth = _token(app, site.owner)
        created = await client.post(
            f"{API}/projects/{site.project.id}/reports",
            headers=auth,
            json={"kind": "weekly", "report_format": "pdf"},
        )
        viewer = await site.add_member(MembershipRole.VIEWER)
        response = await client.get(
            f"{API}/projects/{site.project.id}/reports/{created.json()['id']}/download",
            headers=_token(app, viewer),
        )
        assert response.status_code == 403


class TestAssembly:
    """The worker's collection step — where a timezone slip would hide."""

    async def test_collects_exactly_the_periods_captures(
        self, site: Site, session: AsyncSession
    ) -> None:
        from app.worker.reports import _collect

        report = await site.reports.add(
            Report(
                id=uuid4(),
                project_id=site.project.id,
                requested_by=site.owner.id,
                kind=ReportKind.CUSTOM,
                report_format=ReportFormat.PDF,
                period_start=date(2026, 8, 3),
                period_end=date(2026, 8, 9),
            )
        )
        data = await _collect(session, report)

        # 7 days x 2 captures, all inside the Manila-local window.
        assert len(data.captures) == 14
        assert len(data.snapshots) == 7
        assert data.owner is not None
        assert data.period.timezone == MANILA
        assert all(row.prediction is not None for row in data.captures)
        assert all(row.device_name for row in data.captures)

    async def test_a_period_before_the_captures_is_empty_but_valid(
        self, site: Site, session: AsyncSession
    ) -> None:
        from app.infrastructure.reports import build_csv, build_pdf
        from app.worker.reports import _collect

        report = await site.reports.add(
            Report(
                id=uuid4(),
                project_id=site.project.id,
                requested_by=site.owner.id,
                kind=ReportKind.CUSTOM,
                report_format=ReportFormat.PDF,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 7),
            )
        )
        data = await _collect(session, report)
        assert data.has_data is False
        # Still renders — "no captures in this period" is the finding.
        assert build_pdf(data).startswith(b"%PDF-")
        assert b"filename,captured_at" in build_csv(data)
