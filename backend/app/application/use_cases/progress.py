"""Reading the progress a project has been assigned, and asking for it again.

The *computation* lives in two places already: the pure algorithm in
``ai.progress.aggregator`` and the orchestration in
:mod:`app.application.use_cases.recompute`. Nothing here computes anything.

That separation is the point. Every number these endpoints return was written to
``project_progress_snapshots`` by a worker and is read back verbatim, so the
figure on the dashboard, the figure in the PDF report, and the figure in the
thesis appendix are the same stored row rather than three live recalculations
that can quietly disagree. ``algorithm_version`` travels with it, so a reader
can always tell which version of the rules produced what they are looking at.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.application.ports.task_queue import QUEUE_INFERENCE, TASK_RECOMPUTE_WINDOW
from app.core.exceptions import NotFoundError
from app.domain.entities import StageBreakdown

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from app.application.ports.task_queue import TaskQueue
    from app.domain.entities import ProgressSnapshot
    from app.domain.enums import MacroStage
    from app.domain.repositories import ProjectRepository, SnapshotRepository

__all__ = ["CurrentProgress", "GetProjectProgress", "GetTimeline", "RequestRecompute"]


@dataclass(frozen=True, slots=True)
class CurrentProgress:
    """What ``GET /projects/{id}/progress`` reports."""

    displayed_pct: float
    macro_stage: MacroStage | None
    stages: StageBreakdown
    updated_at: datetime | None
    algorithm_version: str
    eligible_image_count: int
    devices_reporting: int
    #: False when no snapshot exists yet, i.e. nothing has been captured or
    #: nothing has cleared the confidence gate. Reported explicitly so the
    #: dashboard can show "no data yet" instead of a confident 0 %, which reads
    #: as "no progress has been made" and means something entirely different.
    has_data: bool


class GetProjectProgress:
    """Read a project's current progress from its most recent snapshot."""

    def __init__(self, projects: ProjectRepository, snapshots: SnapshotRepository) -> None:
        """Bind the project and snapshot repositories."""
        self._projects = projects
        self._snapshots = snapshots

    async def execute(self, project_id: UUID) -> CurrentProgress:
        """Return the stored progress for an already-authorised project.

        Raises:
            NotFoundError: If the project vanished between the access check and
                this read — a deletion racing the request.
        """
        project = await self._projects.get(project_id)
        if project is None:
            msg = "Project not found."
            raise NotFoundError(msg)

        snapshot = await self._snapshots.latest(project_id)
        if snapshot is None:
            return CurrentProgress(
                displayed_pct=project.progress_pct.as_float(),
                macro_stage=project.macro_stage,
                # Derived from the project's own value rather than zeroed: after
                # a manual approval the project sits at 100 % with no snapshot
                # for that moment, and five empty bars under a 100 % ring would
                # be a contradiction on screen.
                stages=StageBreakdown.from_progress(project.progress_pct),
                updated_at=project.last_capture_at,
                algorithm_version="progress-v1",
                eligible_image_count=0,
                devices_reporting=0,
                has_data=False,
            )
        return CurrentProgress(
            displayed_pct=snapshot.displayed_pct.as_float(),
            macro_stage=snapshot.macro_stage,
            stages=StageBreakdown(
                foundation_pct=snapshot.foundation_pct,
                framing_pct=snapshot.framing_pct,
                roofing_pct=snapshot.roofing_pct,
                finishing_pct=snapshot.finishing_pct,
                approval_pct=snapshot.approval_pct,
            ),
            updated_at=snapshot.window_start,
            algorithm_version=snapshot.algorithm_version,
            eligible_image_count=snapshot.eligible_image_count,
            devices_reporting=snapshot.devices_reporting,
            has_data=True,
        )


class GetTimeline:
    """The snapshot series behind the progress chart."""

    def __init__(self, snapshots: SnapshotRepository) -> None:
        """Bind the snapshot repository."""
        self._snapshots = snapshots

    async def execute(
        self,
        project_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[ProgressSnapshot, ...]:
        """Return the ordered series, gaps and all.

        Windows with no captures are simply absent rather than carried forward.
        The chart must plot the gap rather than interpolate through it: a flat
        line across two silent weeks asserts that progress was measured and
        found unchanged, when in fact nothing was measured at all.
        """
        return await self._snapshots.list_series(project_id, since=since, until=until)


class RequestRecompute:
    """Ask for a project's progress to be rebuilt from stored predictions."""

    def __init__(self, queue: TaskQueue) -> None:
        """Bind the queue the recompute task is handed to."""
        self._queue = queue

    async def execute(self, project_id: UUID, *, window_start: datetime | None = None) -> None:
        """Enqueue the recompute.

        Asynchronous on purpose: a full-history rebuild walks every window a
        project has, which is unbounded work and has no business happening
        inside an HTTP request. The task is idempotent, so an impatient user
        pressing the button twice costs a queue slot and nothing else.
        """
        payload: dict[str, object] = {"project_id": str(project_id)}
        if window_start is not None:
            payload["window_start"] = window_start.isoformat()
        await self._queue.enqueue(TASK_RECOMPUTE_WINDOW, payload, queue=QUEUE_INFERENCE)
