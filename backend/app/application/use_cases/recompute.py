"""Turning stored predictions into a project's progress timeline.

**Worker-only.** This module imports :mod:`ai.progress.aggregator`, and
``geovision-ai`` is installed only in the worker's dependency group — the API
process would fail to import it (ADR-011). That is deliberate rather than
awkward: the API never needs to aggregate, it only reads stored snapshots
(:mod:`app.application.use_cases.progress`), so the split keeps torch and OpenCV
out of the API image entirely.

``tests/unit/test_architecture.py`` asserts that no API module reaches this one.

Two properties make this defensible as a thesis artifact:

**Idempotent.** Running it five times over the same window produces one row with
identical values. Snapshots are upserted on ``(project, window_start)``.

**Replayable.** It always recomputes from *stored predictions*, never by
patching the previous snapshot incrementally. So wiping the snapshot table and
recomputing reproduces the whole timeline exactly — which is the only honest way
to apply an algorithm change to history.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from ai.progress.aggregator import WindowInput, WindowResult, compute_series
from ai.progress.constants import MACHINE_CEILING_PCT
from ai.progress.estimator import ImageProgress
from ai.progress.mapping import MacroStage as AiMacroStage

from app.core.clock import SYSTEM_CLOCK, Clock
from app.domain.entities import ProgressSnapshot
from app.domain.enums import ApprovalState, MacroStage
from app.domain.value_objects import ProgressPct

if TYPE_CHECKING:
    from app.domain.entities import Device, Image, Prediction, Project
    from app.domain.repositories import (
        DeviceRepository,
        ImageRepository,
        PredictionRepository,
        ProjectRepository,
        SnapshotRepository,
    )

__all__ = [
    "INSPECTION_REMARK",
    "REGRESSION_REMARK",
    "RecomputeProgress",
    "RecomputeResult",
    "window_bounds",
]

#: Widest plausible capture range. The repository needs concrete bounds, and a
#: project's images are already scoped by project_id - this only has to be wide
#: enough not to clip real data, never precise.
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)

#: Written when the ratchet releases. Phrased for a homeowner, not an engineer —
#: it appears on the public project page.
REGRESSION_REMARK = (
    "Progress regression detected - possible rework, demolition, or camera obstruction."
)
INSPECTION_REMARK = "All exterior stages complete. Manual inspection required."


def window_bounds(moment: datetime, timezone: str = "Asia/Manila") -> tuple[datetime, datetime]:
    """The daily window containing *moment*, in the project's local timezone.

    Local, not UTC. A window is "a day on site", and a Manila project's day runs
    00:00-24:00 Manila time. Bucketing by UTC would split every local day across
    two windows at 08:00, putting the morning and afternoon captures of one day
    into different buckets — which is exactly the pairing the median is supposed
    to smooth over.

    Returns:
        ``(start, end)`` as timezone-aware UTC instants, since that is what the
        database stores.
    """
    zone = ZoneInfo(timezone)
    local_day: date = moment.astimezone(zone).date()
    start_local = datetime.combine(local_day, time.min, tzinfo=zone)
    return start_local.astimezone(UTC), (start_local + timedelta(days=1)).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class RecomputeResult:
    """What one recomputation changed."""

    snapshot: ProgressSnapshot
    #: True when this run moved the project into ``awaiting_inspection``.
    reached_ceiling: bool = False
    #: True when the ratchet released on this window.
    regressed: bool = False
    windows_computed: int = 1


class RecomputeProgress:
    """Rebuild a project's progress from its stored predictions."""

    def __init__(
        self,
        projects: ProjectRepository,
        predictions: PredictionRepository,
        images: ImageRepository,
        devices: DeviceRepository,
        snapshots: SnapshotRepository,
        *,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._projects = projects
        self._predictions = predictions
        self._images = images
        self._devices = devices
        self._snapshots = snapshots
        self._clock = clock

    async def execute(
        self, project_id: UUID, *, window_start: datetime | None = None
    ) -> RecomputeResult | None:
        """Recompute one window, or the whole timeline.

        Args:
            project_id: The project to recompute.
            window_start: Recompute only the window containing this instant.
                ``None`` recomputes every window from the project's first
                capture — which is what a replay after an algorithm change does.

        Returns:
            The result for the most recent window computed, or ``None`` when the
            project has no eligible predictions at all.

        Note:
            Even a single-window recompute rebuilds the series from the start.
            The EMA and the ratchet are **path-dependent**: a window's displayed
            value depends on every window before it. Computing one in isolation
            from a stored previous snapshot would work, but it would also mean a
            corrected earlier window never propagated forward — history would
            silently disagree with itself.
        """
        project = await self._projects.get(project_id)
        if project is None:
            return None

        timezone = getattr(project, "timezone", None) or "Asia/Manila"
        weights = await self._device_weights(project_id)

        windows = await self._collect_windows(project, timezone=timezone, weights=weights)
        if not windows:
            return None

        series = compute_series(windows)
        stored = [await self._persist(project_id, result) for result in series]

        target = self._select(series, window_start, timezone)
        latest = series[-1]
        await self._apply_to_project(project, latest)

        return RecomputeResult(
            snapshot=stored[series.index(target)],
            reached_ceiling=target.reached_ceiling,
            regressed=target.regressed,
            windows_computed=len(series),
        )

    # -- gathering ----------------------------------------------------------

    async def _collect_windows(
        self, project: Project, *, timezone: str, weights: dict[str, float]
    ) -> tuple[WindowInput, ...]:
        """Bucket every eligible prediction into its capture-day window."""
        images = await self._images.list_in_window(project.id, EPOCH, FAR_FUTURE)
        by_id: dict[UUID, Image] = {image.id: image for image in images}
        if not by_id:
            return ()

        earliest = min(image.captured_at for image in by_id.values())
        latest = max(image.captured_at for image in by_id.values())

        first_start, _ = window_bounds(earliest, timezone)
        _, last_end = window_bounds(latest, timezone)

        predictions = await self._predictions.list_eligible_in_window(
            project.id, first_start, last_end
        )

        buckets: dict[datetime, list[ImageProgress]] = {}
        for prediction in predictions:
            image = by_id.get(prediction.image_id)
            if image is None:
                # The image was deleted after being scored. Its prediction row is
                # about to cascade away; excluding it now keeps the recompute
                # consistent with what the gallery shows.
                continue
            start, _ = window_bounds(image.captured_at, timezone)
            buckets.setdefault(start, []).append(self._to_progress(prediction, image))

        if not buckets:
            return ()

        # Every day between the first and last capture gets a window, including
        # the empty ones. A gap in the chart must be a flat stretch the viewer
        # can see, not a missing point that a line chart would interpolate
        # straight through and imply data nobody collected.
        windows: list[WindowInput] = []
        cursor, _ = window_bounds(earliest, timezone)
        final_start, _ = window_bounds(latest, timezone)
        while cursor <= final_start:
            end = cursor + timedelta(days=1)
            windows.append(
                WindowInput(
                    window_start=cursor,
                    window_end=end,
                    images=tuple(buckets.get(cursor, ())),
                    device_weights=weights,
                )
            )
            cursor = end
        return tuple(windows)

    @staticmethod
    def _to_progress(prediction: Prediction, image: Image) -> ImageProgress:
        """Adapt a stored prediction to the aggregator's input type.

        The aggregator knows nothing about the ORM or the domain entities — that
        is what keeps it unit-testable from a table of numbers.
        """
        return ImageProgress(
            image_id=str(prediction.image_id),
            device_id=str(image.device_id) if image.device_id else "manual",
            fine_class_index=prediction.fine_class_index,
            fine_class=prediction.fine_class,
            macro_stage=AiMacroStage(prediction.macro_stage.value),
            confidence=float(prediction.confidence.value),
            raw_progress_pct=float(prediction.raw_progress_pct.value),
            is_eligible=True,  # the repository already filtered on the gate
        )

    async def _device_weights(self, project_id: UUID) -> dict[str, float]:
        """Per-device aggregation weights, keyed as the aggregator expects."""
        found: tuple[Device, ...] = await self._devices.list_for_project(project_id)
        return {str(device.id): float(device.weight) for device in found}

    # -- persistence --------------------------------------------------------

    async def _persist(self, project_id: UUID, result: WindowResult) -> ProgressSnapshot:
        """Upsert one window's snapshot.

        Upsert, not insert: recomputation must be idempotent, so re-running a
        window replaces its row rather than accumulating duplicates.
        """
        existing = await self._snapshots.get_for_window(project_id, result.window_start)
        stages = {stage.value: pct for stage, pct in result.stage_pcts.items()}

        return await self._snapshots.upsert(
            ProgressSnapshot(
                id=existing.id if existing else uuid4(),
                project_id=project_id,
                window_start=result.window_start,
                window_end=result.window_end,
                raw_pct=ProgressPct.from_float(result.raw_pct),
                ema_pct=ProgressPct.from_float(result.ema_pct),
                displayed_pct=ProgressPct.from_float(result.displayed_pct),
                macro_stage=MacroStage(result.macro_stage.value),
                foundation_pct=stages.get("foundation", 0.0),
                framing_pct=stages.get("framing", 0.0),
                roofing_pct=stages.get("roofing", 0.0),
                finishing_pct=stages.get("finishing", 0.0),
                approval_pct=stages.get("approval", 0.0),
                eligible_image_count=result.eligible_image_count,
                contributing_image_ids=tuple(
                    UUID(value) for value in result.contributing_image_ids
                ),
                device_weights=result.device_weights,
                algorithm_version=result.algorithm_version,
            )
        )

    async def _apply_to_project(self, project: Project, latest: WindowResult) -> None:
        """Denormalise the newest window onto the project row.

        ``projects.progress_pct`` and ``macro_stage`` are copies kept for cheap
        list rendering; the snapshots table remains the source of truth.
        """
        approval = project.approval_state
        # Keyed on the project's *current* value, not on `reached_ceiling`.
        # That flag marks only the window where the ceiling was first crossed,
        # which is right for writing one remark and wrong for state: a project
        # that crossed on day 1 and is still at 80 on day 30 must still be
        # awaiting inspection, and a replay that recomputes the whole series
        # would otherwise leave it stuck at `not_ready`.
        at_ceiling = latest.displayed_pct >= MACHINE_CEILING_PCT
        if at_ceiling and approval is ApprovalState.NOT_READY:
            # ADR-007: the machine has gone as far as it may. A human decides the
            # rest, and until they do the project sits here.
            approval = ApprovalState.AWAITING_INSPECTION

        await self._projects.update(
            replace(
                project,
                progress_pct=ProgressPct.from_float(latest.displayed_pct),
                macro_stage=MacroStage(latest.macro_stage.value),
                approval_state=approval,
            )
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _select(
        series: tuple[WindowResult, ...], window_start: datetime | None, timezone: str
    ) -> WindowResult:
        """Pick the window the caller asked about, defaulting to the newest."""
        if window_start is None:
            return series[-1]
        wanted, _ = window_bounds(window_start, timezone)
        for result in series:
            if result.window_start == wanted:
                return result
        return series[-1]
