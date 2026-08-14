"""The WebSocket endpoint's security decisions, against a real database.

**Why these call the endpoint's functions rather than opening a socket.**
Starlette's `TestClient` drives the app on its own event loop in a worker
thread, while the async `session` fixture belongs to pytest-asyncio's loop —
sharing them raises "attached to a different loop", and the alternative is
letting the socket write to the developer's real database instead of a
rolled-back transaction. So the *protocol* (frames, ping/pong, reconnect) is
proved on the client side in `dashboard/src/lib/ws.test.ts`, and what is proved
here is the part that actually guards data: who may connect, and what they may
follow. The full browser round trip belongs to Module 15's Playwright suite.
"""

from __future__ import annotations

import itertools
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from app.api.v1.routers.ws import _authenticate, _authorize, _parse_ids
from app.core.config import get_settings
from app.core.security import issue_access_token
from app.domain.entities import Project, ProjectMember, User
from app.domain.enums import (
    MembershipRole,
    MembershipStatus,
    ProfessionalRole,
    Visibility,
)
from app.domain.value_objects import GeoPoint, ProjectCode
from app.infrastructure.repositories import (
    SqlAlchemyProjectMemberRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyUserRepository,
)

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_CODES = itertools.count()


class FakeSocket:
    """Records whether — and why — the endpoint closed the connection."""

    def __init__(self) -> None:
        self.closed_with: tuple[int, str] | None = None
        self.frames: list[Any] = []

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_with = (code, reason)

    async def accept(self) -> None:
        pass

    async def send_json(self, data: Any) -> None:
        self.frames.append(data)


async def _user(session: AsyncSession, tag: str) -> User:
    return await SqlAlchemyUserRepository(session).add(
        User(
            id=uuid4(),
            username=f"{tag}_{uuid4().hex[:8]}",
            email=f"{tag}_{uuid4().hex[:8]}@gvmail.com",
            full_name="Socket User",
            professional_role=ProfessionalRole.ENGINEER,
        ),
        password_hash="x",
    )


async def _project(session: AsyncSession, owner: User, *, member: bool = True) -> Project:
    project = await SqlAlchemyProjectRepository(session).add(
        Project(
            id=uuid4(),
            owner_id=owner.id,
            name="Socket Site",
            code=ProjectCode(f"WS_{next(_CODES) % 100:02d}"),
            location_label="Naga City",
            location=GeoPoint(13.6218, 123.1948),
            start_date=date(2026, 6, 1),
            deadline_date=date(2026, 12, 31),
            visibility=Visibility.PRIVATE,
        )
    )
    if member:
        await SqlAlchemyProjectMemberRepository(session).add(
            ProjectMember(
                id=uuid4(),
                project_id=project.id,
                user_id=owner.id,
                membership_role=MembershipRole.OWNER,
                membership_status=MembershipStatus.ACCEPTED,
            )
        )
    return project


def _settings(app: FastAPI) -> Any:
    return app.dependency_overrides[get_settings]()


class TestAuthentication:
    """No valid access token, no socket."""

    async def test_a_missing_token_closes_the_socket(
        self, app: FastAPI, session: AsyncSession
    ) -> None:
        socket = FakeSocket()
        assert await _authenticate(socket, None, _settings(app), session) is None  # type: ignore[arg-type]
        assert socket.closed_with is not None
        assert socket.closed_with[0] == 1008

    async def test_a_garbage_token_closes_the_socket(
        self, app: FastAPI, session: AsyncSession
    ) -> None:
        socket = FakeSocket()
        assert await _authenticate(socket, "not-a-jwt", _settings(app), session) is None  # type: ignore[arg-type]
        assert socket.closed_with is not None

    async def test_a_valid_access_token_yields_the_user(
        self, app: FastAPI, session: AsyncSession
    ) -> None:
        user = await _user(session, "ok")
        token, _ = issue_access_token(user.id, _settings(app))

        resolved = await _authenticate(FakeSocket(), token, _settings(app), session)  # type: ignore[arg-type]
        assert resolved == user.id

    async def test_a_deactivated_account_is_refused(
        self, app: FastAPI, session: AsyncSession
    ) -> None:
        """A token outlives a deactivation; the socket must not."""
        from dataclasses import replace

        user = await _user(session, "gone")
        token, _ = issue_access_token(user.id, _settings(app))
        await SqlAlchemyUserRepository(session).update(replace(user, is_active=False))

        socket = FakeSocket()
        assert await _authenticate(socket, token, _settings(app), session) is None  # type: ignore[arg-type]
        assert socket.closed_with is not None


class TestSubscriptionAuthorization:
    """The security boundary: what a connected user may follow."""

    async def test_an_owner_may_follow_their_own_project(self, session: AsyncSession) -> None:
        owner = await _user(session, "own")
        project = await _project(session, owner)
        projects = SqlAlchemyProjectRepository(session)
        members = SqlAlchemyProjectMemberRepository(session)

        granted, refused = await _authorize({project.id}, set(), owner.id, projects, members)
        assert granted == {project.id}
        assert refused == set()

    async def test_a_stranger_is_refused(self, session: AsyncSession) -> None:
        owner = await _user(session, "own")
        stranger = await _user(session, "str")
        project = await _project(session, owner)
        projects = SqlAlchemyProjectRepository(session)
        members = SqlAlchemyProjectMemberRepository(session)

        granted, refused = await _authorize({project.id}, set(), stranger.id, projects, members)
        assert granted == set()
        assert refused == {project.id}

    async def test_a_project_that_does_not_exist_is_refused(self, session: AsyncSession) -> None:
        user = await _user(session, "ghost")
        granted, refused = await _authorize(
            {uuid4()},
            set(),
            user.id,
            SqlAlchemyProjectRepository(session),
            SqlAlchemyProjectMemberRepository(session),
        )
        assert granted == set()
        assert len(refused) == 1

    async def test_membership_accepted_after_connect_is_honoured(
        self, session: AsyncSession
    ) -> None:
        """A long-lived socket outlives an invitation being accepted.

        The list fetched at connect is a fast path, not the authority — so a
        project absent from it is re-checked rather than refused outright.
        """
        owner = await _user(session, "own")
        joiner = await _user(session, "join")
        project = await _project(session, owner)
        await SqlAlchemyProjectMemberRepository(session).add(
            ProjectMember(
                id=uuid4(),
                project_id=project.id,
                user_id=joiner.id,
                membership_role=MembershipRole.VIEWER,
                membership_status=MembershipStatus.ACCEPTED,
            )
        )

        granted, refused = await _authorize(
            {project.id},
            set(),  # not in the connect-time cache
            joiner.id,
            SqlAlchemyProjectRepository(session),
            SqlAlchemyProjectMemberRepository(session),
        )
        assert granted == {project.id}
        assert refused == set()

    async def test_a_pending_invitation_grants_nothing(self, session: AsyncSession) -> None:
        owner = await _user(session, "own")
        invitee = await _user(session, "inv")
        project = await _project(session, owner)
        await SqlAlchemyProjectMemberRepository(session).add(
            ProjectMember(
                id=uuid4(),
                project_id=project.id,
                user_id=invitee.id,
                membership_role=MembershipRole.EDITOR,
                membership_status=MembershipStatus.PENDING,
            )
        )

        granted, refused = await _authorize(
            {project.id},
            set(),
            invitee.id,
            SqlAlchemyProjectRepository(session),
            SqlAlchemyProjectMemberRepository(session),
        )
        assert granted == set()
        assert refused == {project.id}


class TestFrameParsing:
    """Junk in a frame must not cost a client its other subscriptions."""

    def test_reads_valid_ids(self) -> None:
        first, second = uuid4(), uuid4()
        parsed = _parse_ids(
            {"type": "subscribe", "payload": {"project_ids": [str(first), str(second)]}}
        )
        assert parsed == {first, second}

    def test_drops_a_malformed_id_and_keeps_the_rest(self) -> None:
        good = uuid4()
        assert _parse_ids({"payload": {"project_ids": ["nope", str(good)]}}) == {good}

    def test_a_frame_with_no_payload_yields_nothing(self) -> None:
        assert _parse_ids({"type": "subscribe"}) == set()

    def test_a_non_list_payload_yields_nothing(self) -> None:
        assert _parse_ids({"payload": {"project_ids": "all-of-them"}}) == set()

    def test_the_subscription_count_is_bounded(self) -> None:
        """One socket must not register itself against the whole table."""
        from app.api.v1.routers.ws import MAX_SUBSCRIPTIONS

        ids = [str(uuid4()) for _ in range(MAX_SUBSCRIPTIONS + 50)]
        assert len(_parse_ids({"payload": {"project_ids": ids}})) == MAX_SUBSCRIPTIONS
