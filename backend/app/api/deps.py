"""Dependency injection for the API layer.

Every repository, service, and guard the routers need is provided from here.
Modules 04-16 add endpoints by importing these rather than re-wiring anything,
which is the point: the composition root lives in one file.

The two guards worth understanding:

``CurrentUser``
    Requires a valid **access** token. A refresh token is rejected — see
    :func:`~app.core.security.verify_token`.
``require_permission(...)``
    A dependency *factory*. It resolves the project, the caller's membership,
    and their effective permissions in one pass, then hands the result to the
    handler as an :class:`~app.domain.services.authorization.AccessContext`, so
    a route never re-queries membership it has already been checked against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.events import EventPublisher
from app.application.ports.inference_gateway import InferenceGateway
from app.application.ports.storage import ObjectStorage
from app.application.ports.task_queue import TaskQueue
from app.core import device_auth
from app.core.clock import SYSTEM_CLOCK, Clock
from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthenticatedError
from app.core.security import TokenError, TokenType, verify_token
from app.domain.entities import Device, User
from app.domain.enums import Permission
from app.domain.services.authorization import AccessContext, can_view_project
from app.infrastructure.audit import AuditAction, AuditLogger
from app.infrastructure.cache import get_nonce_cache
from app.infrastructure.db.session import get_session
from app.infrastructure.repositories import (
    SqlAlchemyAIModelRepository,
    SqlAlchemyContactMessageRepository,
    SqlAlchemyDetectionRepository,
    SqlAlchemyDeviceRepository,
    SqlAlchemyImageRepository,
    SqlAlchemyNotificationRepository,
    SqlAlchemyPairingTokenRepository,
    SqlAlchemyPredictionRepository,
    SqlAlchemyProjectMemberRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyReferenceAssetRepository,
    SqlAlchemyRefreshTokenRepository,
    SqlAlchemyRemarkRepository,
    SqlAlchemyReportRepository,
    SqlAlchemySnapshotRepository,
    SqlAlchemyUserRepository,
)
from app.infrastructure.storage import get_storage

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

__all__ = [
    "AccessContextDep",
    "CurrentUser",
    "OptionalUser",
    "SessionDep",
    "SettingsDep",
    "StorageDep",
    "get_client_ip",
    "require_permission",
]

# `auto_error=False` so a missing header reaches our own handler and produces
# the project's standard error envelope rather than FastAPI's default shape.
_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_clock() -> Clock:
    """Provide the time source. Overridden in tests with a frozen clock."""
    return SYSTEM_CLOCK


ClockDep = Annotated[Clock, Depends(get_clock)]


# ---------------------------------------------------------------------------
# Repositories
#
# One provider per repository. Later modules add routes without touching
# construction: they just annotate a parameter with the matching Dep alias.
# ---------------------------------------------------------------------------


def get_user_repository(session: SessionDep) -> SqlAlchemyUserRepository:
    """Provide the user repository."""
    return SqlAlchemyUserRepository(session)


def get_refresh_token_repository(session: SessionDep) -> SqlAlchemyRefreshTokenRepository:
    """Provide the refresh-token repository."""
    return SqlAlchemyRefreshTokenRepository(session)


def get_project_repository(session: SessionDep) -> SqlAlchemyProjectRepository:
    """Provide the project repository."""
    return SqlAlchemyProjectRepository(session)


def get_member_repository(session: SessionDep) -> SqlAlchemyProjectMemberRepository:
    """Provide the project-membership repository."""
    return SqlAlchemyProjectMemberRepository(session)


def get_device_repository(session: SessionDep) -> SqlAlchemyDeviceRepository:
    """Provide the device repository."""
    return SqlAlchemyDeviceRepository(session)


def get_pairing_token_repository(session: SessionDep) -> SqlAlchemyPairingTokenRepository:
    """Provide the pairing-token repository."""
    return SqlAlchemyPairingTokenRepository(session)


def get_image_repository(session: SessionDep) -> SqlAlchemyImageRepository:
    """Provide the image repository."""
    return SqlAlchemyImageRepository(session)


def get_prediction_repository(session: SessionDep) -> SqlAlchemyPredictionRepository:
    """Provide the prediction repository."""
    return SqlAlchemyPredictionRepository(session)


def get_detection_repository(session: SessionDep) -> SqlAlchemyDetectionRepository:
    """Provide the detection repository."""
    return SqlAlchemyDetectionRepository(session)


def get_snapshot_repository(session: SessionDep) -> SqlAlchemySnapshotRepository:
    """Provide the progress-snapshot repository."""
    return SqlAlchemySnapshotRepository(session)


def get_remark_repository(session: SessionDep) -> SqlAlchemyRemarkRepository:
    """Provide the remark repository."""
    return SqlAlchemyRemarkRepository(session)


def get_asset_repository(session: SessionDep) -> SqlAlchemyReferenceAssetRepository:
    """Provide the reference-asset repository."""
    return SqlAlchemyReferenceAssetRepository(session)


def get_report_repository(session: SessionDep) -> SqlAlchemyReportRepository:
    """Provide the report repository."""
    return SqlAlchemyReportRepository(session)


def get_model_repository(session: SessionDep) -> SqlAlchemyAIModelRepository:
    """Provide the AI-model registry repository."""
    return SqlAlchemyAIModelRepository(session)


def get_notification_repository(session: SessionDep) -> SqlAlchemyNotificationRepository:
    """Provide the notification repository."""
    return SqlAlchemyNotificationRepository(session)


def get_contact_repository(session: SessionDep) -> SqlAlchemyContactMessageRepository:
    """Provide the contact-message repository."""
    return SqlAlchemyContactMessageRepository(session)


def get_object_storage(settings: SettingsDep) -> ObjectStorage:
    """Provide the configured object storage backend.

    Local filesystem or S3 depending on ``GV_STORAGE_BACKEND`` - the use cases
    that consume it only know the port, so Module 05's image ingest and Module
    10's report writer inherit both backends for free.
    """
    return get_storage(settings)


def get_audit_logger(session: SessionDep) -> AuditLogger:
    """Provide the audit logger."""
    return AuditLogger(session)


UserRepoDep = Annotated[SqlAlchemyUserRepository, Depends(get_user_repository)]
RefreshTokenRepoDep = Annotated[
    SqlAlchemyRefreshTokenRepository, Depends(get_refresh_token_repository)
]
ProjectRepoDep = Annotated[SqlAlchemyProjectRepository, Depends(get_project_repository)]
MemberRepoDep = Annotated[SqlAlchemyProjectMemberRepository, Depends(get_member_repository)]
DeviceRepoDep = Annotated[SqlAlchemyDeviceRepository, Depends(get_device_repository)]
PairingTokenRepoDep = Annotated[
    SqlAlchemyPairingTokenRepository, Depends(get_pairing_token_repository)
]
ImageRepoDep = Annotated[SqlAlchemyImageRepository, Depends(get_image_repository)]
PredictionRepoDep = Annotated[SqlAlchemyPredictionRepository, Depends(get_prediction_repository)]
DetectionRepoDep = Annotated[SqlAlchemyDetectionRepository, Depends(get_detection_repository)]
SnapshotRepoDep = Annotated[SqlAlchemySnapshotRepository, Depends(get_snapshot_repository)]
RemarkRepoDep = Annotated[SqlAlchemyRemarkRepository, Depends(get_remark_repository)]
AssetRepoDep = Annotated[SqlAlchemyReferenceAssetRepository, Depends(get_asset_repository)]
ReportRepoDep = Annotated[SqlAlchemyReportRepository, Depends(get_report_repository)]
ModelRepoDep = Annotated[SqlAlchemyAIModelRepository, Depends(get_model_repository)]
NotificationRepoDep = Annotated[
    SqlAlchemyNotificationRepository, Depends(get_notification_repository)
]
ContactRepoDep = Annotated[SqlAlchemyContactMessageRepository, Depends(get_contact_repository)]
StorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]
AuditDep = Annotated[AuditLogger, Depends(get_audit_logger)]


# ---------------------------------------------------------------------------
# Request context
# ---------------------------------------------------------------------------


def get_client_ip(request: Request) -> str | None:
    """Best-effort client address, for audit rows and session records.

    ``X-Forwarded-For`` is trusted only because Module 16 terminates TLS at a
    proxy that sets it. Directly exposed, a client could forge it.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


ClientIPDep = Annotated[str | None, Depends(get_client_ip)]


def get_user_agent(request: Request) -> str | None:
    """The caller's User-Agent, truncated to the column width."""
    agent = request.headers.get("User-Agent")
    return agent[:256] if agent else None


UserAgentDep = Annotated[str | None, Depends(get_user_agent)]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


async def get_current_user(
    settings: SettingsDep,
    users: UserRepoDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    """Resolve the authenticated user, or raise 401.

    Rejects anything that is not a valid **access** token, including a valid
    refresh token: without that check a stolen 7-day refresh token would work
    as a 15-minute access token, and the short access lifetime would be
    decorative.

    Raises:
        UnauthenticatedError: If the token is missing, invalid, of the wrong
            type, or belongs to a deactivated account.
    """
    if credentials is None or not credentials.credentials:
        msg = "Authentication required."
        raise UnauthenticatedError(msg)

    try:
        decoded = verify_token(credentials.credentials, settings, expected_type=TokenType.ACCESS)
    except TokenError as exc:
        raise UnauthenticatedError("Invalid or expired token.") from exc

    user = await users.get(decoded.subject)
    if user is None or not user.is_active:
        # The account was deleted or deactivated after the token was issued.
        msg = "Invalid or expired token."
        raise UnauthenticatedError(msg)
    return user


async def get_optional_user(
    settings: SettingsDep,
    users: UserRepoDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User | None:
    """Resolve the user if a valid token is present, else ``None``.

    For endpoints that are public but render differently when signed in — the
    homepage feed and public project pages in Module 11. A bad token here is
    treated as "anonymous" rather than an error, so a stale token in a
    long-open browser tab degrades to the public view instead of an error page.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        decoded = verify_token(credentials.credentials, settings, expected_type=TokenType.ACCESS)
    except TokenError:
        return None
    user = await users.get(decoded.subject)
    return user if user is not None and user.is_active else None


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def get_task_queue(settings: SettingsDep) -> TaskQueue:
    """Provide the background task queue.

    Celery when a broker is configured, the logging stub otherwise. With the
    stub, ingest still records the handoff and `images.status='pending'` is the
    durable backlog a worker drains whenever it arrives - so running without a
    worker loses nothing but time.
    """
    from app.infrastructure.queue import get_task_queue as build_queue

    queue: TaskQueue = build_queue(settings)
    return queue


TaskQueueDep = Annotated[TaskQueue, Depends(get_task_queue)]


def get_gateway(settings: SettingsDep) -> InferenceGateway:
    """Provide the request/response channel to the inference worker.

    Distinct from :data:`TaskQueueDep`, which is fire-and-forget. Two endpoints
    need an *answer* from a model, and the API may not load one itself
    (ADR-011), so they ask a worker and wait. Imported lazily for the same
    reason the queue is: nothing should pull Celery in at module import time.
    """
    from app.infrastructure.ai.gateway import get_inference_gateway

    gateway: InferenceGateway = get_inference_gateway(settings)
    return gateway


InferenceGatewayDep = Annotated[InferenceGateway, Depends(get_gateway)]


def get_publisher(settings: SettingsDep) -> EventPublisher:
    """Provide the realtime event publisher.

    Imported lazily so nothing pulls the Redis client in at module import time,
    and so a deployment without a broker never constructs one.
    """
    from app.infrastructure.realtime import get_event_publisher

    publisher: EventPublisher = get_event_publisher(settings)
    return publisher


EventPublisherDep = Annotated[EventPublisher, Depends(get_publisher)]


async def get_current_device(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    devices: DeviceRepoDep,
    audit: AuditDep,
    clock: ClockDep,
) -> Device:
    """Authenticate an ESP32-CAM by its HMAC signature.

    Implements `Device-Pairing-Protocol.md` Phase 3. The raw body is read here
    (Starlette caches it, so the handler can still parse the multipart form) and
    hashed into the canonical string, which is what stops an attacker swapping
    the image while keeping a valid-looking signature.

    **Every failure returns the same 401.** The specific reason is logged and
    audited server-side; disclosing it would tell an attacker which half of
    their forgery to fix.

    Raises:
        UnauthenticatedError: On any verification failure.
    """
    body = await request.body()
    client_ip = get_client_ip(request)

    async def _deny(reason: str, device_id: object = None) -> UnauthenticatedError:
        await audit.record(
            AuditAction.DEVICE_AUTH_FAILED,
            entity_type="device",
            entity_id=device_id if isinstance(device_id, UUID) else UUID(int=0),
            ip_address=client_ip,
            metadata={"reason": reason, "path": request.url.path},
        )
        # Committed here, before the raise. Everything after this point unwinds
        # into a rollback, and the row recording *why* a device was refused
        # would go with it — leaving the endpoint behaving exactly as designed
        # while the evidence a brute-force attempt leaves behind quietly did not
        # exist. Safe to commit: this dependency runs before the handler, so the
        # audit row is the only pending write.
        await session.commit()
        return UnauthenticatedError(device_auth.GENERIC_AUTH_FAILURE)

    try:
        signed = device_auth.parse_signed_request(request.headers, body)
    except device_auth.DeviceAuthError as exc:
        raise await _deny(exc.reason) from exc

    device = await devices.get(signed.device_id)
    usable = device is not None and device.is_usable
    secret = (
        await devices.get_secret(signed.device_id, settings.device_secret_key) if usable else None
    )

    try:
        await device_auth.verify_signed_request(
            signed,
            secret=secret,
            method=request.method,
            path=request.url.path,
            nonces=get_nonce_cache(settings),
            now=clock.now(),
            skew_seconds=settings.device_clock_skew_seconds,
        )
    except device_auth.DeviceAuthError as exc:
        raise await _deny(exc.reason, signed.device_id) from exc

    assert device is not None  # noqa: S101 - narrowed by `usable` above
    return device


CurrentDevice = Annotated[Device, Depends(get_current_device)]


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def get_access_context(
    project_id: Annotated[UUID, Path(description="Project id")],
    projects: ProjectRepoDep,
    members: MemberRepoDep,
    user: OptionalUser,
) -> AccessContext:
    """Resolve what the caller may do with the project in the path.

    Raises:
        NotFoundError: If the project does not exist **or** the caller may not
            know that it does. Never 403 for a hidden project — a 403 confirms
            existence, which is itself a disclosure.
    """
    project = await projects.get(project_id)
    if project is None:
        msg = "Project not found."
        raise NotFoundError(msg)

    membership = await members.get_membership(project_id, user.id) if user is not None else None
    if not can_view_project(project, membership=membership):
        msg = "Project not found."
        raise NotFoundError(msg)

    return AccessContext.build(project, user_id=user.id if user else None, membership=membership)


AccessContextDep = Annotated[AccessContext, Depends(get_access_context)]


def require_permission(
    permission: Permission,
) -> Callable[[AccessContext], Coroutine[Any, Any, AccessContext]]:
    """Build a dependency that demands *permission* on the path's project.

    Used by every mutating project route from Module 04 onward::

        @router.patch("/projects/{project_id}")
        async def update_project(
            access: Annotated[AccessContext, Depends(require_permission(Permission.PROJECT_EDIT))],
        ) -> ProjectResponse: ...

    The resolved context is returned, so the handler already has the project's
    membership and permission set without querying again.

    Raises:
        ForbiddenError: If the caller may see the project but not perform this
            action. (Callers who may not see it at all already got a 404 from
            :func:`get_access_context`.)
    """

    async def dependency(access: AccessContextDep) -> AccessContext:
        if not access.allows(permission):
            raise ForbiddenError(
                f"This action requires the '{permission.value}' permission.",
                details={"required_permission": permission.value},
            )
        return access

    return dependency
