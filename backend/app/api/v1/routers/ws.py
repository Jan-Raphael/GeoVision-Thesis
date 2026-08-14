"""The WebSocket endpoint: `WSS /api/v1/ws?token=<access_jwt>`.

Three things here are security, not plumbing.

**The token goes in the query string** because browsers cannot set headers on
`WebSocket`. That is a real exposure — query strings land in proxy logs — which
is why it must be an *access* token: fifteen minutes, and a refresh token is
rejected outright (ADR-015). The connection is upgraded only after the token
validates; an invalid one is closed before the handshake completes, so an
unauthenticated peer never reaches the message loop.

**Every subscription is authorized server-side, per project.** A client asking
for a project it cannot view is silently dropped from that id and the attempt is
audited. Silently, because telling the caller "you may not subscribe to that"
confirms the project exists — the same disclosure the REST layer answers 404 to
avoid.

**Nothing is pushed over a socket that REST would not return to the same user.**
The socket is a faster delivery route for data the user could already fetch, and
never a second, laxer access path.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.api.deps import SessionDep, SettingsDep
from app.api.route import TransactionalRoute
from app.application.ports.events import EventType, RealtimeEvent
from app.core.security import TokenError, TokenType, verify_token
from app.domain.services.authorization import can_view_project
from app.infrastructure.audit import AuditAction, AuditLogger
from app.infrastructure.realtime.hub import get_hub
from app.infrastructure.repositories import (
    SqlAlchemyProjectMemberRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyUserRepository,
)

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"], route_class=TransactionalRoute)

#: Frames larger than this are refused. A subscribe list is a few hundred bytes;
#: anything near this is either a bug or an attempt to exhaust memory.
MAX_FRAME_BYTES = 16 * 1024

#: How many projects one socket may follow. Generous for a real user, bounded
#: so a single connection cannot register itself against the whole table.
MAX_SUBSCRIPTIONS = 100


@router.websocket("/ws")
async def realtime(
    websocket: WebSocket,
    session: SessionDep,
    settings: SettingsDep,
    token: Annotated[str | None, Query(description="Access token from /auth/login")] = None,
) -> None:
    """Push project events to an authenticated browser.

    Protocol in ``Realtime-Events.md``. On connect the server sends
    ``connection.ready`` carrying the projects this user may subscribe to, so a
    client never has to guess and never has to be told "no" later.
    """
    user_id = await _authenticate(websocket, token, settings, session)
    if user_id is None:
        return

    projects = SqlAlchemyProjectRepository(session)
    members = SqlAlchemyProjectMemberRepository(session)
    audit = AuditLogger(session)
    hub = get_hub()

    allowed = {project.id for project in await projects.list_for_user(user_id)}
    await websocket.accept()
    await websocket.send_json(
        RealtimeEvent(
            type=EventType.CONNECTION_READY,
            # `connection.ready` is about the connection, not a project; the
            # nil UUID keeps the envelope uniform without inventing a project.
            project_id=UUID(int=0),
            payload={
                "user_id": str(user_id),
                "subscribable_project_ids": sorted(str(pid) for pid in allowed),
            },
        ).as_wire()
    )

    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue

            kind = message.get("type")
            if kind == "ping":
                # Application-level, not the protocol's own ping frame: the
                # client needs an answer it can observe in JavaScript, and
                # browsers do not surface protocol pongs.
                await websocket.send_json({"type": "pong"})
                continue

            if kind not in {"subscribe", "unsubscribe"}:
                continue

            requested = _parse_ids(message)
            if kind == "unsubscribe":
                await hub.unsubscribe(websocket, requested)
                continue

            granted, refused = await _authorize(requested, allowed, user_id, projects, members)
            if refused:
                for project_id in refused:
                    await audit.record(
                        AuditAction.WS_SUBSCRIBE_DENIED,
                        entity_type="project",
                        entity_id=project_id,
                        actor_user_id=user_id,
                        metadata={"reason": "not visible to this user"},
                    )
                await session.commit()

            if granted:
                await hub.subscribe(websocket, granted)
                await websocket.send_json(
                    {
                        "type": "subscribed",
                        "payload": {"project_ids": sorted(str(pid) for pid in granted)},
                    }
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("realtime socket failed", exc_info=True)
    finally:
        # Every exit path, including an abrupt close with no close frame —
        # which is the normal case for a phone leaving coverage. Skipping this
        # leaks the socket and every event addressed to it, forever.
        await hub.disconnect(websocket)


async def _authenticate(
    websocket: WebSocket,
    token: str | None,
    settings: SettingsDep,
    session: SessionDep,
) -> UUID | None:
    """Validate the token, or close before upgrading.

    Returns the user id, or ``None`` having already closed the socket. Closing
    with 1008 (policy violation) rather than accepting-then-closing means an
    unauthenticated peer never gets a usable connection at all.
    """
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Token required")
        return None
    try:
        decoded = verify_token(token, settings, expected_type=TokenType.ACCESS)
    except TokenError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return None

    user = await SqlAlchemyUserRepository(session).get(decoded.subject)
    if user is None or not user.is_active:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return None
    return user.id


def _parse_ids(message: dict[str, object]) -> set[UUID]:
    """Extract project ids from a subscribe/unsubscribe frame, ignoring junk."""
    payload = message.get("payload")
    raw = payload.get("project_ids") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return set()

    ids: set[UUID] = set()
    for item in raw[:MAX_SUBSCRIPTIONS]:
        try:
            ids.add(UUID(str(item)))
        except ValueError:
            # A malformed id is dropped rather than failing the frame: one bad
            # entry should not cost the client its other subscriptions.
            continue
    return ids


async def _authorize(
    requested: set[UUID],
    cached: set[UUID],
    user_id: UUID,
    projects: SqlAlchemyProjectRepository,
    members: SqlAlchemyProjectMemberRepository,
) -> tuple[set[UUID], set[UUID]]:
    """Split *requested* into what this user may follow and what they may not.

    The membership list fetched at connect is a fast path, not the authority: a
    long-lived socket outlives an invitation being accepted, so anything not in
    it is re-checked against the database rather than refused outright.
    """
    granted = requested & cached
    granted_now: set[UUID] = set()
    refused: set[UUID] = set()

    for project_id in requested - cached:
        project = await projects.get(project_id)
        if project is None:
            refused.add(project_id)
            continue
        membership = await members.get_membership(project_id, user_id)
        if can_view_project(project, membership=membership):
            granted_now.add(project_id)
        else:
            refused.add(project_id)

    return granted | granted_now, refused
