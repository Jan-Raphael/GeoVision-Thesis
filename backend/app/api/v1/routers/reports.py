"""Report endpoints: request, track, list, download.

Generation is asynchronous — `POST` returns **202** with an id, and the file
appears when a worker has rendered it. Download re-checks permission **at
download time** rather than trusting the request that created the report:
membership can be revoked in between, and a link that outlives someone's access
is a leak with a timestamp on it.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import (
    AccessContextDep,
    AuditDep,
    ClientIPDep,
    ClockDep,
    CurrentUser,
    ProjectRepoDep,
    ReportRepoDep,
    StorageDep,
    TaskQueueDep,
    require_permission,
)
from app.api.route import TransactionalRoute
from app.api.schemas.reports import (
    ReportDownloadResponse,
    ReportListResponse,
    ReportResponse,
    RequestReportRequest,
)
from app.application.use_cases.reports import (
    DownloadReport,
    GetReport,
    ListReports,
    RequestReport,
)
from app.core.exceptions import NotFoundError
from app.domain.enums import Permission
from app.domain.services.authorization import AccessContext
from app.infrastructure.audit import AuditAction

router = APIRouter(tags=["reports"], route_class=TransactionalRoute)

ProjectId = Annotated[UUID, Path(description="Project id")]
ReportId = Annotated[UUID, Path(description="Report id")]


def _present(report: object) -> ReportResponse:
    """Map a report entity onto the wire."""
    return ReportResponse.model_validate(report, from_attributes=True)


@router.post(
    "/projects/{project_id}/reports",
    summary="Request a report",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReportResponse,
    responses={400: {"description": "Invalid custom period"}},
)
async def request_report(
    project_id: ProjectId,
    payload: RequestReportRequest,
    access: Annotated[AccessContext, Depends(require_permission(Permission.REPORT_GENERATE))],
    projects: ProjectRepoDep,
    reports: ReportRepoDep,
    queue: TaskQueueDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
    clock: ClockDep,
) -> ReportResponse:
    """Queue a PDF or CSV for the requested period.

    The period is resolved **synchronously**, so an impossible custom range
    fails here with a 400 the caller can act on rather than becoming a `failed`
    row they have to go and find. A weekly report always covers the last
    *complete* Monday-Sunday in the project's timezone; monthly, the last
    complete calendar month.
    """
    _ = access
    report = await RequestReport(projects, reports, queue, clock=clock).execute(
        project_id,
        requested_by=user.id,
        kind=payload.kind,
        report_format=payload.report_format,
        period_start=payload.period_start,
        period_end=payload.period_end,
    )
    await audit.record(
        AuditAction.REPORT_REQUESTED,
        entity_type="report",
        entity_id=report.id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={
            "project_id": str(project_id),
            "kind": report.kind.value,
            "format": report.report_format.value,
        },
    )
    return _present(report)


@router.get(
    "/projects/{project_id}/reports",
    summary="List a project's reports",
    response_model=ReportListResponse,
)
async def list_reports(
    project_id: ProjectId,
    access: AccessContextDep,
    reports: ReportRepoDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ReportListResponse:
    """Recent reports, newest first — including failed ones.

    Failures are listed rather than hidden: somebody pressed a button, and an
    empty list would suggest they never did.
    """
    _ = access
    found = await ListReports(reports).execute(project_id, limit=limit)
    return ReportListResponse(reports=[_present(report) for report in found])


@router.get(
    "/projects/{project_id}/reports/{report_id}",
    summary="Report status",
    response_model=ReportResponse,
)
async def get_report(
    project_id: ProjectId,
    report_id: ReportId,
    access: AccessContextDep,
    reports: ReportRepoDep,
) -> ReportResponse:
    """Poll one report's progress: `queued` → `processing` → `ready` | `failed`."""
    _ = access
    return _present(await GetReport(reports).execute(report_id, project_id))


@router.get(
    "/projects/{project_id}/reports/{report_id}/download",
    summary="Download a finished report",
    response_model=ReportDownloadResponse,
    responses={409: {"description": "The report is not ready yet, or failed"}},
)
async def download_report(
    project_id: ProjectId,
    report_id: ReportId,
    access: AccessContextDep,
    reports: ReportRepoDep,
    projects: ProjectRepoDep,
    storage: StorageDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
) -> ReportDownloadResponse:
    """Return a short-lived signed URL for the rendered file.

    A URL rather than a streamed body: reports run to several megabytes with
    embedded figures, and pushing them through the API process would tie up a
    worker for the length of somebody's download.

    Requires `report:generate` — the same authority that created it, re-checked
    now. A **409** means the render has not finished (or failed), which is
    different from a 404 and should be retried rather than reported as missing.
    """
    project = await projects.get(project_id)
    if project is None:
        msg = "Project not found."
        raise NotFoundError(msg)
    if not access.allows(Permission.REPORT_GENERATE):
        from app.core.exceptions import ForbiddenError

        raise ForbiddenError(
            "This action requires the 'report:generate' permission.",
            details={"required_permission": Permission.REPORT_GENERATE.value},
        )

    download = await DownloadReport(reports, storage).execute(report_id, project)
    await audit.record(
        AuditAction.REPORT_DOWNLOADED,
        entity_type="report",
        entity_id=report_id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={"project_id": str(project_id)},
    )
    return ReportDownloadResponse(
        url=download.url,
        filename=download.filename,
        report_format=download.report_format,
    )
