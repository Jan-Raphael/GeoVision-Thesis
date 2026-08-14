"""The connection hub: routing, isolation, and — mostly — not leaking.

A hub that leaks sockets does not fail a test, it fails a deployment three days
later with a memory graph nobody can explain. So most of what is asserted here
is that connections *disappear* on every exit path, including the abrupt ones
that are the normal case for a phone leaving coverage.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.application.ports.events import EventType, RealtimeEvent
from app.infrastructure.realtime.hub import ConnectionHub

pytestmark = pytest.mark.unit


class FakeSocket:
    """Records the frames it was sent."""

    def __init__(self, *, fails: bool = False) -> None:
        self.frames: list[dict[str, Any]] = []
        self.fails = fails

    async def send_json(self, data: Any) -> None:
        if self.fails:
            msg = "socket is gone"
            raise ConnectionError(msg)
        self.frames.append(data)


def _event(project_id: Any, kind: str = EventType.PROGRESS_UPDATED) -> RealtimeEvent:
    return RealtimeEvent(type=kind, project_id=project_id, payload={"displayed_pct": 38.5})


class TestRouting:
    """Events reach the right sockets and only those."""

    async def test_delivers_to_every_subscriber_of_a_project(self) -> None:
        hub = ConnectionHub()
        project = uuid4()
        first, second = FakeSocket(), FakeSocket()
        await hub.subscribe(first, {project})
        await hub.subscribe(second, {project})

        assert await hub.broadcast(_event(project)) == 2
        assert first.frames[0]["type"] == EventType.PROGRESS_UPDATED
        assert second.frames[0]["project_id"] == str(project)

    async def test_a_socket_never_sees_another_projects_events(self) -> None:
        """The whole authorization model rests on this."""
        hub = ConnectionHub()
        mine, theirs = uuid4(), uuid4()
        socket = FakeSocket()
        await hub.subscribe(socket, {mine})

        assert await hub.broadcast(_event(theirs)) == 0
        assert socket.frames == []

    async def test_an_event_for_nobody_is_not_an_error(self) -> None:
        hub = ConnectionHub()
        assert await hub.broadcast(_event(uuid4())) == 0

    async def test_the_wire_envelope_matches_the_contract(self) -> None:
        hub = ConnectionHub()
        project = uuid4()
        socket = FakeSocket()
        await hub.subscribe(socket, {project})
        await hub.broadcast(_event(project))

        frame = socket.frames[0]
        assert set(frame) == {"type", "project_id", "ts", "payload"}
        assert frame["ts"].endswith("Z")


class TestCleanup:
    """Nothing survives a disconnect."""

    async def test_disconnect_removes_the_socket_from_every_project(self) -> None:
        hub = ConnectionHub()
        one, two = uuid4(), uuid4()
        socket = FakeSocket()
        await hub.subscribe(socket, {one, two})

        await hub.disconnect(socket)

        assert hub.socket_count == 0
        assert hub.subscriber_count(one) == 0
        assert hub.subscriber_count(two) == 0

    async def test_disconnecting_twice_is_safe(self) -> None:
        """The endpoint's `finally` can run after an explicit close."""
        hub = ConnectionHub()
        socket = FakeSocket()
        await hub.subscribe(socket, {uuid4()})
        await hub.disconnect(socket)
        await hub.disconnect(socket)
        assert hub.socket_count == 0

    async def test_disconnecting_an_unknown_socket_is_safe(self) -> None:
        await ConnectionHub().disconnect(FakeSocket())

    async def test_unsubscribe_leaves_other_projects_alone(self) -> None:
        hub = ConnectionHub()
        kept, dropped = uuid4(), uuid4()
        socket = FakeSocket()
        await hub.subscribe(socket, {kept, dropped})

        await hub.unsubscribe(socket, {dropped})

        assert hub.subscriber_count(kept) == 1
        assert hub.subscriber_count(dropped) == 0

    async def test_an_emptied_project_leaves_no_entry_behind(self) -> None:
        """A long-lived process must not accumulate an empty set per project."""
        hub = ConnectionHub()
        project = uuid4()
        socket = FakeSocket()
        await hub.subscribe(socket, {project})
        await hub.disconnect(socket)

        assert project not in hub._by_project

    async def test_a_failed_send_drops_the_socket(self) -> None:
        """The send is how a dead connection announces itself."""
        hub = ConnectionHub()
        project = uuid4()
        dead, alive = FakeSocket(fails=True), FakeSocket()
        await hub.subscribe(dead, {project})
        await hub.subscribe(alive, {project})

        delivered = await hub.broadcast(_event(project))

        # The live socket still got it — one bad peer must not abort the fan-out.
        assert delivered == 1
        assert len(alive.frames) == 1
        assert hub.subscriber_count(project) == 1

    async def test_a_hundred_sockets_leave_nothing_behind(self) -> None:
        """The load-test shape, in miniature."""
        hub = ConnectionHub()
        project = uuid4()
        sockets = [FakeSocket() for _ in range(100)]
        for socket in sockets:
            await hub.subscribe(socket, {project})

        assert await hub.broadcast(_event(project)) == 100

        for socket in sockets:
            await hub.disconnect(socket)
        assert hub.socket_count == 0
        assert hub._by_project == {}
