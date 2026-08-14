"""Progress endpoints: the current reading, the timeline, and manual recompute.

Every number here is **read from a stored snapshot**, never recalculated on the
way out. That is what makes the dashboard, the PDF report, and the thesis
appendix agree: they are three renderings of one row, not three live
computations of the same formula. ``algorithm_version`` travels with the data so
a reader can tell which version of the rules produced what they are looking at.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import (
    AccessContextDep,
    AuditDep,
    ClientIPDep,
    CurrentUser,
    ProjectRepoDep,
    SnapshotRepoDep,
    TaskQueueDep,
    require_permission,
)
from app.api.route import TransactionalRoute
from app.api.schemas.predictions import (
    ProgressResponse,
    RecomputeAcceptedResponse,
    TimelineResponse,
)
from app.api.v1.presenters_ai import present_progress, present_timeline
from app.application.use_cases.progress import GetProjectProgress, GetTimeline, RequestRecompute
from app.domain.enums import Permission
from app.domain.services.authorization import AccessContext
from app.infrastructure.audit import AuditAction

router = APIRouter(prefix="/projects", tags=["progress"], route_class=TransactionalRoute)

ProjectId = Annotated[UUID, Path(description="Project id")]


@router.get(
    "/{project_id}/progress",
    summary="Current progress",
    response_model=ProgressResponse,
)
async def get_progress(
    project_id: ProjectId,
    access: AccessContextDep,
    projects: ProjectRepoDep,
    snapshots: SnapshotRepoDep,
) -> ProgressResponse:
    """The project's current percentage, macro stage, and five stage bars.

    ``has_data`` is the field worth reading first. A project with no captures
    reports ``0 %`` because that is its stored value, and without the flag the
    dashboard cannot tell that apart from a site where work genuinely has not
    started.
    """
    _ = access
    progress = await GetProjectProgress(projects, snapshots).execute(project_id)
    return present_progress(progress)


@router.get(
    "/{project_id}/timeline",
    summary="Progress snapshot series",
    response_model=TimelineResponse,
)
async def get_timeline(
    project_id: ProjectId,
    access: AccessContextDep,
    snapshots: SnapshotRepoDep,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> TimelineResponse:
    """The stored series behind the progress chart.

    Windows with no captures are **absent** rather than carried forward, so the
    chart can draw the gap. Interpolating a straight line through two silent
    weeks would assert measurements that were never taken.
    """
    _ = access
    series = await GetTimeline(snapshots).execute(project_id, since=since, until=until)
    return present_timeline(series)


@router.post(
    "/{project_id}/recompute",
    summary="Rebuild progress from stored predictions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RecomputeAcceptedResponse,
)
async def request_recompute(
    project_id: ProjectId,
    access: Annotated[AccessContext, Depends(require_permission(Permission.PROGRESS_RECOMPUTE))],
    queue: TaskQueueDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
    window_start: Annotated[datetime | None, Query(alias="window")] = None,
) -> RecomputeAcceptedResponse:
    """Queue a re-aggregation of this project's progress.

    Reads only persisted predictions, so replaying history after an algorithm
    change reproduces the whole timeline rather than inventing a new one. The
    task is idempotent: running it five times yields one snapshot per window,
    identical each time.

    Returns **202** — a full rebuild walks every window the project has, which
    is unbounded work and does not belong inside an HTTP request.
    """
    _ = access
    await RequestRecompute(queue).execute(project_id, window_start=window_start)
    await audit.record(
        AuditAction.PROGRESS_RECOMPUTE_REQUESTED,
        entity_type="project",
        entity_id=project_id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={"window_start": window_start.isoformat() if window_start else None},
    )
    return RecomputeAcceptedResponse(project_id=project_id)
