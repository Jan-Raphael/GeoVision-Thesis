"""Authentication endpoints: register, login, refresh, logout, me."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import (
    AuditDep,
    ClientIPDep,
    CurrentUser,
    RefreshTokenRepoDep,
    SettingsDep,
    UserAgentDep,
    UserRepoDep,
)
from app.api.schemas.auth import (
    USERNAME_PATTERN,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SessionResponse,
    UsernameAvailabilityResponse,
    UserResponse,
)
from app.api.schemas.common import MessageResponse
from app.application.use_cases.auth import (
    AuthenticateUser,
    LogoutUser,
    RefreshSession,
    RegisterUser,
    SessionResult,
)
from app.core.rate_limit import get_limiter
from app.infrastructure.audit import AuditAction

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = get_limiter()


def _to_session_response(result: SessionResult, settings: SettingsDep) -> SessionResponse:
    """Render a session result for the wire."""
    return SessionResponse(
        user=UserResponse.model_validate(result.user),
        access_token=result.tokens.access_token,
        refresh_token=result.tokens.refresh_token,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    response_model=SessionResponse,
)
@limiter.limit("3/hour")
async def register(
    request: Request,
    response: Response,
    payload: RegisterRequest,
    users: UserRepoDep,
    refresh_tokens: RefreshTokenRepoDep,
    settings: SettingsDep,
    audit: AuditDep,
    client_ip: ClientIPDep,
    user_agent: UserAgentDep,
) -> SessionResponse:
    """Register a user and start their first session.

    The new account is logged straight in, matching the spec's flow: after
    registering, the user lands on their own profile page.
    """
    use_case = RegisterUser(users, refresh_tokens, settings)
    result = await use_case.execute(
        username=payload.username,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        professional_role=payload.professional_role,
        company=payload.company,
        user_agent=user_agent,
        ip_address=client_ip,
    )
    await audit.record(
        AuditAction.USER_REGISTERED,
        entity_type="user",
        entity_id=result.user.id,
        actor_user_id=result.user.id,
        ip_address=client_ip,
        # Never the password, and never the token.
        metadata={"username": result.user.username},
    )
    return _to_session_response(result, settings)


@router.post("/login", summary="Log in", response_model=SessionResponse)
@limiter.limit("20/minute")
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    users: UserRepoDep,
    refresh_tokens: RefreshTokenRepoDep,
    settings: SettingsDep,
    audit: AuditDep,
    client_ip: ClientIPDep,
    user_agent: UserAgentDep,
) -> SessionResponse:
    """Authenticate with a username **or** email plus a password.

    Two independent limits apply: a per-IP cap here, and a per-account failed
    attempt throttle inside the use case (``app.core.throttle``). The second is
    the one that matters against credential stuffing, since an attacker with
    many source addresses walks straight through a per-IP limit.
    """
    use_case = AuthenticateUser(users, refresh_tokens, settings)
    result = await use_case.execute(
        identifier=payload.identifier,
        password=payload.password,
        user_agent=user_agent,
        ip_address=client_ip,
    )
    await audit.record(
        AuditAction.USER_LOGGED_IN,
        entity_type="user",
        entity_id=result.user.id,
        actor_user_id=result.user.id,
        ip_address=client_ip,
    )
    return _to_session_response(result, settings)


@router.post("/refresh", summary="Rotate a refresh token", response_model=SessionResponse)
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest,
    users: UserRepoDep,
    refresh_tokens: RefreshTokenRepoDep,
    settings: SettingsDep,
) -> SessionResponse:
    """Exchange a refresh token for a new pair.

    Single-use. Presenting an already-rotated token is treated as theft and
    revokes the whole session family — see
    :class:`~app.application.use_cases.auth.RefreshSession`.
    """
    use_case = RefreshSession(users, refresh_tokens, settings)
    result = await use_case.execute(refresh_token=payload.refresh_token)
    return _to_session_response(result, settings)


@router.post("/logout", summary="End the session", response_model=MessageResponse)
async def logout(
    payload: RefreshRequest,
    refresh_tokens: RefreshTokenRepoDep,
) -> MessageResponse:
    """Revoke the session the refresh token belongs to.

    Always reports success, whether or not the token existed — otherwise logout
    becomes a way to probe which tokens are valid.
    """
    await LogoutUser(refresh_tokens).execute(refresh_token=payload.refresh_token)
    return MessageResponse(message="Signed out.")


@router.get("/me", summary="The signed-in user", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    """Return the caller's own profile."""
    return UserResponse.model_validate(user)


@router.get(
    "/check-username",
    summary="Username availability",
    response_model=UsernameAvailabilityResponse,
)
@limiter.limit("20/minute")
async def check_username(
    request: Request,
    response: Response,
    users: UserRepoDep,
    username: Annotated[str, Query(min_length=3, max_length=30)],
) -> UsernameAvailabilityResponse:
    """Live check for the registration form.

    This intentionally discloses whether a username exists — the registration
    form cannot work otherwise, and usernames are public on profile pages
    anyway. Email addresses get no equivalent endpoint.
    """
    candidate = username.strip()
    if not USERNAME_PATTERN.match(candidate):
        return UsernameAvailabilityResponse(
            username=candidate,
            available=False,
            reason="Username must be 3-30 characters: letters, digits, underscores, dots.",
        )
    taken = await users.username_exists(candidate)
    # Availability changes; never let a proxy cache it.
    response.headers["Cache-Control"] = "no-store"
    return UsernameAvailabilityResponse(
        username=candidate,
        available=not taken,
        reason="Already taken." if taken else None,
    )
