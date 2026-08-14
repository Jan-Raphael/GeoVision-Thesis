"""Stored predictions → progress snapshots → the project's headline number.

The aggregation *algorithm* is proved in ``ai/tests/test_aggregator.py`` against
a table of numbers, including the worked example printed in the thesis. What is
proved here is the part that only a database can show: that predictions written
by the worker are bucketed into the right windows, that recomputation is
idempotent, and that replaying from scratch reproduces the same timeline.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from app.application.use_cases.recompute import RecomputeProgress, window_bounds
from app.domain.entities import Device, Image, Prediction, Project, User
from app.domain.enums import (
    ApprovalState,
    CameraFace,
    ImageSource,
    ImageStatus,
    MacroStage,
    ModelKind,
    ProfessionalRole,
    Visibility,
)
from app.domain.value_objects import Confidence, GeoPoint, ProgressPct, ProjectCode
from app.infrastructure.repositories import (
    SqlAlchemyAIModelRepository,
    SqlAlchemyDeviceRepository,
    SqlAlchemyImageRepository,
    SqlAlchemyPredictionRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemySnapshotRepository,
    SqlAlchemyUserRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

MANILA_NOON = datetime(2026, 8, 1, 4, 0, tzinfo=UTC)  # 12:00 Asia/Manila

#: (token, nominal %) pairs from the canonical class table, restated here so the
#: expected values in these tests are readable without a lookup.
COLUMNS = (4, 28.0)
SLAB = (5, 34.0)
WALLS = (6, 40.0)
COMPLETED = (9, 80.0)


class Fixture:
    """A project with one camera, ready to be given predictions."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the helper to a session."""
        self.session = session
        self.projects = SqlAlchemyProjectRepository(session)
        self.images = SqlAlchemyImageRepository(session)
        self.predictions = SqlAlchemyPredictionRepository(session)
        self.devices = SqlAlchemyDeviceRepository(session)
        self.snapshots = SqlAlchemySnapshotRepository(session)
        self.project: Project
        self.device: Device
        self.model_id = uuid4()

    async def setup(self, *, weight: float = 1.0) -> Fixture:
        """Create the owner, project, camera, and a registered model."""
        owner = await SqlAlchemyUserRepository(self.session).add(
            User(
                id=uuid4(),
                username=f"agg_{uuid4().hex[:8]}",
                email=f"agg_{uuid4().hex[:8]}@example.test",
                full_name="Aggregation Tester",
                professional_role=ProfessionalRole.ENGINEER,
            ),
            password_hash="x",
        )
        self.project = await self.projects.add(
            Project(
                id=uuid4(),
                owner_id=owner.id,
                name="Aggregation Site",
                code=ProjectCode(f"AG_{uuid4().int % 100:02d}"),
                location_label="Naga City",
                location=GeoPoint(13.6218, 123.1948),
                start_date=date(2026, 1, 1),
                deadline_date=date(2026, 12, 31),
                visibility=Visibility.PRIVATE,
            )
        )
        self.device = await self.devices.add(
            Device(
                id=uuid4(),
                project_id=self.project.id,
                device_name="ESP_AG_00_FD",
                face=CameraFace.FRONT_DIAGONAL,
                weight=weight,
            ),
            secret_encrypted="not-used-by-aggregation",
        )
        from app.domain.entities import AIModel

        model = await SqlAlchemyAIModelRepository(self.session).add(
            AIModel(
                id=self.model_id,
                name="stub-classifier",
                kind=ModelKind.CLASSIFIER,
                architecture="stub",
                version="stub-v1",
                class_names=("Columns",),
                input_size=224,
                is_active=True,
            )
        )
        self.model_id = model.id
        return self

    async def add_prediction(
        self,
        captured_at: datetime,
        stage: tuple[int, float],
        *,
        confidence: float = 0.9,
        device: Device | None = None,
    ) -> Image:
        """Store one image with a prediction attached."""
        class_index, nominal = stage
        camera = device or self.device
        image = await self.images.add(
            Image(
                id=uuid4(),
                project_id=self.project.id,
                device_id=camera.id,
                filename=f"{self.project.code.value}_{uuid4().hex[:8]}.jpg",
                storage_key=f"projects/{self.project.id}/{uuid4().hex}.jpg",
                captured_at=captured_at,
                sha256=uuid4().hex * 2,
                source=ImageSource.DEVICE,
                status=ImageStatus.INFERRED,
                seq_number=1,
            )
        )
        await self.predictions.add(
            Prediction(
                id=uuid4(),
                image_id=image.id,
                model_id=self.model_id,
                fine_class_index=class_index,
                fine_class=f"class-{class_index}",
                confidence=Confidence.from_float(confidence),
                macro_stage=_macro_for(nominal),
                raw_progress_pct=ProgressPct.from_float(nominal),
            )
        )
        return image

    def recompute(self) -> RecomputeProgress:
        """Build the use case against this fixture's repositories."""
        return RecomputeProgress(
            self.projects, self.predictions, self.images, self.devices, self.snapshots
        )


def _macro_for(nominal: float) -> MacroStage:
    """Macro stage for a nominal percentage."""
    if nominal >= 80:
        return MacroStage.APPROVAL
    if nominal >= 60:
        return MacroStage.FINISHING
    if nominal >= 40:
        return MacroStage.ROOFING
    if nominal >= 20:
        return MacroStage.FRAMING
    return MacroStage.FOUNDATION


@pytest.fixture
async def site(session: AsyncSession) -> Fixture:
    """A project with one camera."""
    return await Fixture(session).setup()


class TestBasicAggregation:
    """Predictions become a snapshot and a headline number."""

    async def test_one_window_produces_one_snapshot(self, site: Fixture) -> None:
        await site.add_prediction(MANILA_NOON, COLUMNS)

        result = await site.recompute().execute(site.project.id)

        assert result is not None
        assert float(result.snapshot.displayed_pct.value) == pytest.approx(28.0)
        assert result.snapshot.eligible_image_count == 1

    async def test_the_project_row_is_updated(self, site: Fixture) -> None:
        """`projects.progress_pct` is a denormalised copy for list rendering."""
        await site.add_prediction(MANILA_NOON, WALLS)
        await site.recompute().execute(site.project.id)

        refreshed = await site.projects.get(site.project.id)
        assert refreshed is not None
        assert float(refreshed.progress_pct.value) == pytest.approx(40.0)
        assert refreshed.macro_stage is MacroStage.ROOFING

    async def test_a_project_with_no_predictions_returns_none(self, site: Fixture) -> None:
        assert await site.recompute().execute(site.project.id) is None

    async def test_low_confidence_predictions_are_excluded(self, site: Fixture) -> None:
        """Stored and badged, but never counted (Progress-Calculation §1).

        The repository filters on the gate, so this proves the filter is really
        applied rather than merely intended.
        """
        await site.add_prediction(MANILA_NOON, COLUMNS)
        await site.add_prediction(MANILA_NOON, COMPLETED, confidence=0.2)

        result = await site.recompute().execute(site.project.id)

        assert result is not None
        assert float(result.snapshot.displayed_pct.value) == pytest.approx(28.0)
        assert result.snapshot.eligible_image_count == 1

    async def test_the_median_is_taken_per_device(self, site: Fixture) -> None:
        """One bad frame in three cannot move the reading."""
        for stage in (WALLS, WALLS, COLUMNS):
            await site.add_prediction(MANILA_NOON, stage)

        result = await site.recompute().execute(site.project.id)

        assert result is not None
        assert float(result.snapshot.displayed_pct.value) == pytest.approx(40.0)


class TestWindowing:
    """Captures are bucketed by the project's local day, not by UTC."""

    async def test_captures_on_the_same_local_day_share_a_window(self, site: Fixture) -> None:
        """07:00 and 16:00 Manila are one working day.

        Bucketing by UTC would split every local day at 08:00 and put the two
        scheduled captures into different windows — exactly the pairing the
        median exists to smooth over.
        """
        morning = datetime(2026, 8, 1, 23, 0, tzinfo=UTC)  # 07:00 Aug 2 Manila
        afternoon = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)  # 16:00 Aug 2 Manila

        await site.add_prediction(morning, COLUMNS)
        await site.add_prediction(afternoon, WALLS)

        result = await site.recompute().execute(site.project.id)

        assert result is not None
        assert result.windows_computed == 1
        assert result.snapshot.eligible_image_count == 2

    async def test_window_bounds_span_a_local_day(self) -> None:
        start, end = window_bounds(MANILA_NOON, "Asia/Manila")

        assert end - start == timedelta(days=1)
        assert start <= MANILA_NOON < end

    async def test_empty_days_between_captures_still_get_snapshots(self, site: Fixture) -> None:
        """A gap must be a flat stretch a viewer can see, not a missing point
        that a line chart would interpolate straight through."""
        await site.add_prediction(MANILA_NOON, COLUMNS)
        await site.add_prediction(MANILA_NOON + timedelta(days=4), COLUMNS)

        result = await site.recompute().execute(site.project.id)

        assert result is not None
        assert result.windows_computed == 5

        series = await site.snapshots.list_series(site.project.id)
        assert len(series) == 5


class TestIdempotencyAndReplay:
    """The two properties that make the timeline defensible."""

    async def test_recomputing_five_times_yields_one_row(self, site: Fixture) -> None:
        """Vault testing procedure #3."""
        await site.add_prediction(MANILA_NOON, COLUMNS)

        for _ in range(5):
            await site.recompute().execute(site.project.id)

        series = await site.snapshots.list_series(site.project.id)
        assert len(series) == 1

    async def test_repeated_recomputation_is_stable(self, site: Fixture) -> None:
        await site.add_prediction(MANILA_NOON, COLUMNS)
        await site.add_prediction(MANILA_NOON + timedelta(days=1), WALLS)

        first = await site.recompute().execute(site.project.id)
        second = await site.recompute().execute(site.project.id)

        assert first is not None
        assert second is not None
        assert first.snapshot.displayed_pct == second.snapshot.displayed_pct
        assert first.snapshot.raw_pct == second.snapshot.raw_pct

    async def test_a_replay_reproduces_the_timeline(self, site: Fixture) -> None:
        """Vault testing procedure #10.

        Recomputation always rebuilds from stored predictions rather than
        patching the previous snapshot, so wiping and recomputing must give
        back exactly what was there.
        """
        for offset, stage in enumerate((COLUMNS, SLAB, WALLS, WALLS)):
            await site.add_prediction(MANILA_NOON + timedelta(days=offset), stage)

        await site.recompute().execute(site.project.id)
        before = [
            (snapshot.window_start, float(snapshot.displayed_pct.value))
            for snapshot in await site.snapshots.list_series(site.project.id)
        ]

        await site.recompute().execute(site.project.id)
        after = [
            (snapshot.window_start, float(snapshot.displayed_pct.value))
            for snapshot in await site.snapshots.list_series(site.project.id)
        ]

        assert before == after
        assert len(before) == 4

    async def test_every_snapshot_records_its_algorithm_version(self, site: Fixture) -> None:
        """So a chart drawn from mixed versions is identifiable, not just wrong."""
        await site.add_prediction(MANILA_NOON, COLUMNS)
        result = await site.recompute().execute(site.project.id)

        assert result is not None
        assert result.snapshot.algorithm_version == "progress-v1"

    async def test_contributing_images_are_recorded(self, site: Fixture) -> None:
        """An owner asking "why is it 34 %?" gets an answer."""
        image = await site.add_prediction(MANILA_NOON, COLUMNS)
        result = await site.recompute().execute(site.project.id)

        assert result is not None
        assert image.id in result.snapshot.contributing_image_ids


class TestMachineCeiling:
    """ADR-007 — the AI cannot mark a project complete."""

    async def test_progress_never_exceeds_eighty(self, site: Fixture) -> None:
        for offset in range(30):
            await site.add_prediction(MANILA_NOON + timedelta(days=offset), COMPLETED)

        await site.recompute().execute(site.project.id)

        for snapshot in await site.snapshots.list_series(site.project.id):
            assert float(snapshot.displayed_pct.value) <= 80.0

    async def test_reaching_the_ceiling_awaits_inspection(self, site: Fixture) -> None:
        """Vault testing procedure #7.

        The machine has gone as far as it may; a named human decides the rest.
        """
        for offset in range(30):
            await site.add_prediction(MANILA_NOON + timedelta(days=offset), COMPLETED)

        await site.recompute().execute(site.project.id)

        refreshed = await site.projects.get(site.project.id)
        assert refreshed is not None
        assert refreshed.approval_state is ApprovalState.AWAITING_INSPECTION
        assert float(refreshed.progress_pct.value) == pytest.approx(80.0, abs=0.01)

    async def test_the_approval_bar_stays_empty(self, site: Fixture) -> None:
        """The fifth bar is the human's, and the machine never fills it."""
        for offset in range(30):
            await site.add_prediction(MANILA_NOON + timedelta(days=offset), COMPLETED)

        result = await site.recompute().execute(site.project.id)

        assert result is not None
        assert result.snapshot.approval_pct == 0.0
        assert result.snapshot.finishing_pct == 100.0


class TestMultiCamera:
    """Weighted fusion across cameras, with real device rows."""

    async def test_two_cameras_are_averaged_by_weight(self, session: AsyncSession) -> None:
        site = await Fixture(session).setup(weight=1.5)
        second = await site.devices.add(
            Device(
                id=uuid4(),
                project_id=site.project.id,
                device_name="ESP_AG_00_B",
                face=CameraFace.BACK,
                weight=1.0,
            ),
            secret_encrypted="not-used-by-aggregation",
        )

        await site.add_prediction(MANILA_NOON, WALLS)  # 40, weight 1.5
        await site.add_prediction(MANILA_NOON, COLUMNS, device=second)  # 28, weight 1.0

        result = await site.recompute().execute(site.project.id)

        assert result is not None
        # (1.5*40 + 1.0*28) / 2.5 = 35.2
        assert float(result.snapshot.raw_pct.value) == pytest.approx(35.2, abs=0.05)

    async def test_device_weights_are_recorded_on_the_snapshot(self, site: Fixture) -> None:
        """So a past number can be explained after the weights are changed."""
        await site.add_prediction(MANILA_NOON, COLUMNS)
        result = await site.recompute().execute(site.project.id)

        assert result is not None
        assert str(site.device.id) in result.snapshot.device_weights
