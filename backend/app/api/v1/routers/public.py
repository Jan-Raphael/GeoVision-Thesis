"""The anonymous surface: homepage feed, public project pages, search, contact.

Everything here is reachable with no token. Two rules hold throughout:

* Reads go through the **visibility-scoped repository methods**, so a private
  project cannot be selected at all — rather than being fetched and then
  filtered, which is one forgotten ``if`` away from a leak.
* A hidden resource returns **404, never 403**. A 403 confirms the resource
  exists, which is itself a disclosure about something the caller is not
  allowed to know about.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import (
    AssetRepoDep,
    ClientIPDep,
    ClockDep,
    ContactRepoDep,
    DeviceRepoDep,
    ImageRepoDep,
    MemberRepoDep,
    OptionalUser,
    ProjectRepoDep,
    RemarkRepoDep,
    SnapshotRepoDep,
    StorageDep,
    UserAgentDep,
    UserRepoDep,
)
from app.api.schemas.common import MessageResponse, PageResponse
from app.api.schemas.projects import (
    ContactRequest,
    ProjectSummaryResponse,
    PublicProjectResponse,
    TimelinePointResponse,
)
from app.api.v1.presenters import present_public_project, present_summary, sign_thumbnails
from app.application.use_cases.content import SubmitContactMessage
from app.application.use_cases.projects import GetProjectFolder
from app.core.exceptions import NotFoundError
from app.core.rate_limit import get_limiter
from app.domain.enums import ProjectStatus
from app.domain.services.authorization import AccessContext
from app.domain.value_objects import DomainValidationError, ProjectCode

router = APIRouter(prefix="/public", tags=["public"])
limiter = get_limiter()


@router.get(
    "/feed",
    summary="Homepage feed of public projects",
    response_model=PageResponse[ProjectSummaryResponse],
)
async def public_feed(
    projects: ProjectRepoDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    status_filter: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    stage: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
) -> PageResponse[ProjectSummaryResponse]:
    """Public, non-archived projects, most recently active first.

    Cursor-paginated rather than offset: new captures arrive while a visitor is
    scrolling, and ``OFFSET`` would silently skip or repeat cards.
    """
    page = await projects.list_public_feed(
        limit=limit, cursor=cursor, stage=stage, status=status_filter, query=q
    )
    return PageResponse[ProjectSummaryResponse](
        items=[present_summary(project) for project in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/projects/{project_code}",
    summary="Public project folder",
    response_model=PublicProjectResponse,
    responses={404: {"description": "No such public project"}},
)
async def public_project(
    project_code: str,
    projects: ProjectRepoDep,
    members: MemberRepoDep,
    devices: DeviceRepoDep,
    images: ImageRepoDep,
    remarks: RemarkRepoDep,
    assets: AssetRepoDep,
    snapshots: SnapshotRepoDep,
    users: UserRepoDep,
    storage: StorageDep,
    clock: ClockDep,
    viewer: OptionalUser,
) -> PublicProjectResponse:
    """What a visitor sees when they open a project from the feed.

    Progress, the timeline, the deadline, the handler, public remarks, and
    recent geotagged captures. Members, devices, worker counts, assets, and
    inspection notes are absent by construction — the response model simply has
    no fields for them.
    """
    try:
        code = ProjectCode(project_code.upper())
    except DomainValidationError as exc:
        # A malformed code cannot name a real project, so it is a 404 rather
        # than a 422: the caller learns nothing either way.
        msg = "Project not found."
        raise NotFoundError(msg) from exc

    project = await projects.get_public_by_code(code)
    if project is None:
        msg = "Project not found."
        raise NotFoundError(msg)

    membership = await members.get_membership(project.id, viewer.id) if viewer is not None else None
    access = AccessContext.build(
        project, user_id=viewer.id if viewer else None, membership=membership
    )

    folder = await GetProjectFolder(
        projects, members, devices, images, remarks, assets, snapshots, users, clock=clock
    ).execute(access, public_only=True)
    return present_public_project(folder, await sign_thumbnails(storage, folder.recent_images))


@router.get(
    "/projects/{project_code}/timeline",
    summary="Public progress timeline",
    response_model=list[TimelinePointResponse],
)
async def public_timeline(
    project_code: str,
    projects: ProjectRepoDep,
    snapshots: SnapshotRepoDep,
) -> list[TimelinePointResponse]:
    """The progress chart series for a public project."""
    try:
        code = ProjectCode(project_code.upper())
    except DomainValidationError as exc:
        msg = "Project not found."
        raise NotFoundError(msg) from exc

    project = await projects.get_public_by_code(code)
    if project is None:
        msg = "Project not found."
        raise NotFoundError(msg)

    series = await snapshots.list_series(project.id)
    return [
        TimelinePointResponse(
            window_start=snapshot.window_start,
            displayed_pct=snapshot.displayed_pct.as_float(),
            macro_stage=snapshot.macro_stage,
        )
        for snapshot in series
    ]


@router.get(
    "/search",
    summary="Search public projects and profiles",
    response_model=dict,
)
@limiter.limit("30/minute")
async def search(
    request: Request,
    response: Response,
    projects: ProjectRepoDep,
    users: UserRepoDep,
    q: Annotated[str, Query(min_length=2, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict:
    """One search box over projects, locations, and owners.

    Rate-limited: trigram similarity across every project and user is the most
    expensive read in the system, and the easiest to abuse for scraping.
    """
    matched_projects = await projects.search(q, limit=limit)
    matched_users = await users.search(q, limit=limit)
    return {
        "query": q,
        "projects": [present_summary(project).model_dump() for project in matched_projects],
        "users": [
            {
                "username": user.username,
                "full_name": user.full_name,
                "professional_role": user.professional_role.value,
                "company": user.company,
            }
            for user in matched_users
        ],
    }


@router.post(
    "/contact",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Contact Us",
    response_model=MessageResponse,
)
@limiter.limit("5/hour")
async def contact(
    request: Request,
    response: Response,
    payload: ContactRequest,
    messages: ContactRepoDep,
    client_ip: ClientIPDep,
    user_agent: UserAgentDep,
) -> MessageResponse:
    """Submit a message from the public Contact Us form.

    Messages are **persisted**, not emailed: v1 has no mail delivery, and a
    contact form that silently discards submissions is broken rather than
    deferred. The owner reads them from the database until delivery exists.
    """
    await SubmitContactMessage(messages).execute(
        name=payload.name,
        email=payload.email,
        subject=payload.subject,
        message=payload.message,
        ip_address=client_ip,
        user_agent=user_agent,
    )
    return MessageResponse(message="Thanks - your message has been received.")
