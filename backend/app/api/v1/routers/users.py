"""Authenticated profile endpoints (`/users/me`)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AuditDep, ClientIPDep, CurrentUser, ProjectRepoDep, UserRepoDep
from app.api.schemas.auth import (
    UpdateProfileRequest,
    UserResponse,
    VisibilityRequest,
)
from app.application.use_cases.users import (
    SetProfileVisibility,
    UpdateProfile,
)
from app.infrastructure.audit import AuditAction

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", summary="My profile", response_model=UserResponse)
async def get_my_profile(user: CurrentUser) -> UserResponse:
    """Return the caller's full profile, including private fields."""
    return UserResponse.model_validate(user)


@router.patch("/me", summary="Update my profile", response_model=UserResponse)
async def update_my_profile(
    payload: UpdateProfileRequest,
    user: CurrentUser,
    users: UserRepoDep,
    audit: AuditDep,
    client_ip: ClientIPDep,
) -> UserResponse:
    """Apply a partial update to the caller's own profile.

    ``company`` is optional at registration and editable here, exactly as the
    dashboard spec describes.
    """
    updated = await UpdateProfile(users).execute(
        user.id,
        full_name=payload.full_name,
        company=payload.company,
        bio=payload.bio,
        professional_role=payload.professional_role,
        profile_visibility=payload.profile_visibility,
        clear_company=payload.clear_company,
        clear_bio=payload.clear_bio,
    )
    await audit.record(
        AuditAction.PROFILE_UPDATED,
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        ip_address=client_ip,
    )
    return UserResponse.model_validate(updated)


@router.patch(
    "/me/visibility",
    summary="Set profile visibility",
    response_model=UserResponse,
)
async def set_visibility(
    payload: VisibilityRequest,
    user: CurrentUser,
    users: UserRepoDep,
    audit: AuditDep,
    client_ip: ClientIPDep,
) -> UserResponse:
    """Toggle the profile between public and private (spec B.5).

    Private accounts stay findable by exact username so they can still be
    invited to a project, but disclose nothing else.
    """
    updated = await SetProfileVisibility(users).execute(user.id, payload.profile_visibility)
    await audit.record(
        AuditAction.PROFILE_VISIBILITY_CHANGED,
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={"visibility": payload.profile_visibility.value},
    )
    return UserResponse.model_validate(updated)


@router.get("/me/projects", summary="My projects", response_model=list[dict])
async def my_projects(
    user: CurrentUser,
    projects: ProjectRepoDep,
) -> list[dict]:
    """Projects the caller owns or is an accepted member of.

    Returns a light shape for now; Module 04 replaces this with the full
    project schema once the project endpoints exist.
    """
    owned = await projects.list_for_user(user.id)
    return [
        {
            "id": str(project.id),
            "project_code": project.code.value,
            "name": project.name,
            "status": project.status.value,
            "visibility": project.visibility.value,
            "progress_pct": project.progress_pct.as_float(),
            "macro_stage": project.macro_stage.value if project.macro_stage else None,
            "deadline_date": project.deadline_date.isoformat(),
        }
        for project in owned
    ]
