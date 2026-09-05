"""The commit must land before the response does (Q12, ADR-031).

This is the test the suite was missing. The defect it pins was invisible to
every existing test for one specific reason: ``httpx.ASGITransport`` awaits the
whole ASGI call — dependency teardown included — before handing back a response,
so a test always observes the committed state no matter when the commit ran.
Only a real network client could see the gap, and it measured ~7 ms.

So this drives the ASGI app **directly** and records the order of two events:
when the session was committed, and when the response actually started being
sent. Anything that moves the commit back into teardown fails here immediately
rather than in somebody's browser.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, Request

from app.api.route import TransactionalRoute
from app.infrastructure.db.session import SESSION_STATE_KEY

pytestmark = pytest.mark.unit


class FakeSession:
    """Records when it was committed, into a shared timeline."""

    def __init__(self, timeline: list[str], *, open_transaction: bool = True) -> None:
        self._timeline = timeline
        self._open = open_transaction
        self.commits = 0

    def in_transaction(self) -> bool:
        return self._open

    async def commit(self) -> None:
        self.commits += 1
        self._timeline.append("commit")


async def _drive(app: FastAPI, timeline: list[str], path: str = "/thing") -> int:
    """Call the ASGI app by hand, recording when the response starts."""
    status_code = 0

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status_code
        if message["type"] == "http.response.start":
            status_code = int(message["status"])
            timeline.append("response.start")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    return status_code


def _app(timeline: list[str], session: FakeSession | None, *, fail: bool = False) -> FastAPI:
    """A minimal app whose single route uses the transactional route class."""
    application = FastAPI()
    router = APIRouter(route_class=TransactionalRoute)

    @router.post("/thing")
    async def create(request: Request) -> dict[str, bool]:
        if session is not None:
            setattr(request.state, SESSION_STATE_KEY, session)
        if fail:
            msg = "handler exploded"
            raise RuntimeError(msg)
        return {"ok": True}

    application.include_router(router)
    return application


class TestCommitOrdering:
    """The property the whole fix exists for."""

    async def test_the_commit_lands_before_the_response_starts(self) -> None:
        timeline: list[str] = []
        session = FakeSession(timeline)

        status_code = await _drive(_app(timeline, session), timeline)

        assert status_code == 200
        # The ordering *is* the assertion. Reversed, a client that reads its own
        # write immediately gets a 404 — which is exactly what Q12 measured.
        assert timeline == ["commit", "response.start"]
        assert session.commits == 1


class TestWhenNotToCommit:
    """Committing the wrong thing is its own bug."""

    async def test_a_failed_handler_is_never_committed(self) -> None:
        timeline: list[str] = []
        session = FakeSession(timeline)

        with pytest.raises(RuntimeError, match="handler exploded"):
            await _drive(_app(timeline, session, fail=True), timeline)

        assert session.commits == 0
        assert "commit" not in timeline

    async def test_a_read_only_request_issues_no_commit(self) -> None:
        """SQLAlchemy begins lazily, so a pure read has nothing open.

        Committing anyway would put a wasted round trip on the hottest paths in
        the system — the public feed and the health probes.
        """
        timeline: list[str] = []
        session = FakeSession(timeline, open_transaction=False)

        await _drive(_app(timeline, session), timeline)

        assert session.commits == 0

    async def test_an_endpoint_that_never_touched_the_database_is_fine(self) -> None:
        """No session on the request, no commit, no crash."""
        timeline: list[str] = []
        status_code = await _drive(_app(timeline, None), timeline)

        assert status_code == 200
        assert timeline == ["response.start"]


class TestEveryWritingRouterIsCovered:
    """A router that forgets the route class reintroduces the defect silently."""

    def test_all_v1_routers_use_the_transactional_route(self) -> None:
        import pathlib

        routers = pathlib.Path("app/api/v1/routers")
        missing: list[str] = []
        for path in sorted(routers.glob("*.py")):
            if path.name in {"__init__.py", "health.py", "mobile_pair.py"}:
                # Neither touches a database and should not pay for a session:
                # health is a liveness probe, mobile_pair only ever serves a
                # static HTML file.
                continue
            source = path.read_text(encoding="utf-8")
            if "APIRouter(" in source and "route_class=TransactionalRoute" not in source:
                missing.append(path.name)

        assert missing == [], (
            f"these routers commit after the response, reintroducing Q12: {missing}"
        )
