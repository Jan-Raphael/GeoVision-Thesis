"""Public, unauthenticated profile endpoints.

Everything here is reachable with no token, so each handler routes through a
visibility-scoped use case rather than a general one. The private-account
response is built by the domain entity, not assembled here — a field added to
``User`` later cannot leak through this router by omission.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import OptionalUser, ProjectRepoDep, UserRepoDep
from app.api.route import TransactionalRoute
from app.api.schemas.auth import (
    PublicProfileDetailResponse,
    PublicProfileResponse,
    PublicProjectSummary,
)
from app.application.use_cases.users import GetPublicProfile, SearchUsers
from app.core.rate_limit import get_limiter

router = APIRouter(prefix="/public", tags=["public"], route_class=TransactionalRoute)
limiter = get_limiter()


@router.get(
    "/users/{username}",
    summary="Public profile",
    response_model=PublicProfileDetailResponse,
    responses={404: {"description": "No such account"}},
)
async def public_profile(
    username: str,
    users: UserRepoDep,
    projects: ProjectRepoDep,
    viewer: OptionalUser,
) -> PublicProfileDetailResponse:
    """Return a profile as a visitor sees it.

    A **private** account returns ``{"username": ..., "is_private": true}`` with
    every other field null and no projects — it resolves rather than 404ing,
    because the page must be able to render "this account is private", and the
    person must stay findable so they can be invited to a project.

    Viewing your own profile always shows the full version.
    """
    view = await GetPublicProfile(users, projects).execute(
        username, viewer_id=viewer.id if viewer else None
    )
    return PublicProfileDetailResponse(
        **PublicProfileResponse.model_validate(view.profile).model_dump(),
        projects=[
            PublicProjectSummary(
                project_code=project.code.value,
                name=project.name,
                location_label=project.location_label,
                progress_pct=project.progress_pct.as_float(),
                status=project.status.value,
                macro_stage=project.macro_stage.value if project.macro_stage else None,
            )
            for project in view.projects
        ],
    )


@router.get(
    "/users",
    summary="Search public profiles",
    response_model=list[PublicProfileResponse],
)
@limiter.limit("30/minute")
async def search_users(
    request: Request,
    response: Response,
    users: UserRepoDep,
    q: Annotated[str, Query(min_length=2, max_length=80, description="Name or username")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[PublicProfileResponse]:
    """Fuzzy-search **public** profiles by username or full name.

    Private accounts are excluded here but remain reachable by exact username.
    Rate-limited: search is the most expensive read in the system (trigram
    similarity across every user) and the easiest to abuse for scraping.
    """
    found = await SearchUsers(users).execute(q, limit=limit)
    return [PublicProfileResponse.model_validate(profile) for profile in found]
