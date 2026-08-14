"""The per-process registry of live WebSocket connections.

One hub per API process. It knows only about sockets *this* process holds —
which is the whole reason Redis pub/sub exists above it: with two Uvicorn
workers, a socket lives in exactly one of them, and a worker publishing an event
has no idea which. The hub is the last hop, never the fan-out.

Two invariants keep it from leaking:

**A socket is removed from every subscription it holds, on every exit path.**
Abrupt closes are the normal case, not the exception — a phone leaving a tunnel
does not send a close frame — so cleanup runs in a ``finally``, never after a
graceful-shutdown branch.

**A failed send unsubscribes the socket rather than propagating.** By the time a
send fails the connection is already gone; raising would abort the fan-out and
deprive every *other* subscriber of the same event.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from app.application.ports.events import RealtimeEvent

__all__ = ["ConnectionHub", "SocketLike", "get_hub", "reset_hub"]

logger = logging.getLogger(__name__)


class SocketLike(Protocol):
    """The slice of ``WebSocket`` the hub uses.

    A Protocol rather than the Starlette class so the hub can be tested with a
    fake that records frames, and so nothing here depends on the web framework.
    """

    async def send_json(self, data: Any) -> None:
        """Send one JSON frame."""
        ...


class ConnectionHub:
    """Sockets held by this process, indexed by the projects they follow."""

    def __init__(self) -> None:
        """Start empty."""
        self._by_project: dict[UUID, set[SocketLike]] = defaultdict(set)
        self._by_socket: dict[SocketLike, set[UUID]] = defaultdict(set)
        # Subscription changes and fan-out both mutate these maps, and a
        # disconnect during a broadcast would otherwise resize a set mid-iteration.
        self._lock = asyncio.Lock()

    async def subscribe(self, socket: SocketLike, project_ids: set[UUID]) -> None:
        """Add *socket* to each project's subscriber set.

        The caller has already authorized these ids; the hub does no permission
        work of its own, deliberately — one place decides who may see what, and
        it is the endpoint that has the user.
        """
        async with self._lock:
            for project_id in project_ids:
                self._by_project[project_id].add(socket)
                self._by_socket[socket].add(project_id)

    async def unsubscribe(self, socket: SocketLike, project_ids: set[UUID]) -> None:
        """Remove *socket* from the given projects."""
        async with self._lock:
            for project_id in project_ids:
                self._drop(socket, project_id)
            if not self._by_socket.get(socket):
                self._by_socket.pop(socket, None)

    async def disconnect(self, socket: SocketLike) -> None:
        """Forget *socket* entirely. Safe to call twice."""
        async with self._lock:
            for project_id in list(self._by_socket.get(socket, ())):
                self._drop(socket, project_id)
            self._by_socket.pop(socket, None)

    async def broadcast(self, event: RealtimeEvent) -> int:
        """Send *event* to every socket subscribed to its project.

        Returns how many sockets received it — useful in tests, and it is the
        number worth logging when an event appears not to have arrived.
        """
        async with self._lock:
            targets = list(self._by_project.get(event.project_id, ()))
        if not targets:
            return 0

        frame = event.as_wire()
        results = await asyncio.gather(
            *(socket.send_json(frame) for socket in targets), return_exceptions=True
        )

        delivered = 0
        dead: list[SocketLike] = []
        for socket, result in zip(targets, results, strict=True):
            if isinstance(result, BaseException):
                dead.append(socket)
            else:
                delivered += 1

        for socket in dead:
            # Already gone: the send is how we found out. Dropping it here is
            # what stops a closed connection collecting events forever.
            logger.debug("dropping a socket that failed to receive %s", event.type)
            await self.disconnect(socket)
        return delivered

    def _drop(self, socket: SocketLike, project_id: UUID) -> None:
        """Remove one (socket, project) pair. Caller holds the lock."""
        subscribers = self._by_project.get(project_id)
        if subscribers is not None:
            subscribers.discard(socket)
            if not subscribers:
                # Empty sets are removed rather than left behind: a long-running
                # process that has served a thousand projects would otherwise
                # keep a thousand empty sets forever.
                self._by_project.pop(project_id, None)
        following = self._by_socket.get(socket)
        if following is not None:
            following.discard(project_id)

    @property
    def socket_count(self) -> int:
        """How many distinct sockets this process holds."""
        return len(self._by_socket)

    def subscriber_count(self, project_id: UUID) -> int:
        """How many sockets here follow *project_id*."""
        return len(self._by_project.get(project_id, ()))


_hub: ConnectionHub | None = None


def get_hub() -> ConnectionHub:
    """The process-wide hub, created on first use."""
    global _hub
    if _hub is None:
        _hub = ConnectionHub()
    return _hub


def reset_hub() -> None:
    """Drop the hub. Tests call this between cases."""
    global _hub
    _hub = None
