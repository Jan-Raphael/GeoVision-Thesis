"""Repository behaviour against a real database.

The visibility tests here are the most important in Module 02: they prove that
a private project or profile cannot be returned by a public read path. Modules
04 and 11 build the anonymous API on top of exactly these methods.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from app.domain.entities import Project, User
from app.domain.enums import (
    CameraFace,
    MembershipRole,
    MembershipStatus,
    ModelKind,
    ProfessionalRole,
    ProjectStatus,
    Visibility,
)
from app.domain.value_objects import GeoPoint, ProgressPct, ProjectCode
from app.infrastructure.repositories import (
    SqlAlchemyAIModelRepository,
    SqlAlchemyDeviceRepository,
    SqlAlchemyImageRepository,
    SqlAlchemyProjectMemberRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyUserRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


def _user(username: str, visibility: Visibility = Visibility.PUBLIC) -> User:
    """Build a user entity."""
    return User(
        id=uuid4(),
        username=username,
        email=f"{username}@example.test",
        full_name=f"{username.title()} Tester",
        professional_role=ProfessionalRole.ENGINEER,
        profile_visibility=visibility,
    )


def _project(owner_id: object, code: str, visibility: Visibility, **kw: object) -> Project:
    """Build a project entity."""
    values: dict[str, object] = {
        "id": uuid4(),
        "owner_id": owner_id,
        "name": f"Project {code}",
        "code": ProjectCode(code),
        "location_label": "Naga City",
        "location": GeoPoint(13.6218, 123.1948),
        "start_date": date(2026, 1, 1),
        "deadline_date": date(2026, 12, 31),
        "visibility": visibility,
    }
    values.update(kw)
    return Project(**values)  # type: ignore[arg-type]


class TestUserRepository:
    """Accounts, lookups, and profile visibility."""

    async def test_round_trip(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        created = await repo.add(_user("alice"), password_hash="hash-value")

        fetched = await repo.get(created.id)
        assert fetched is not None
        assert fetched.username == "alice"
        assert fetched.professional_role is ProfessionalRole.ENGINEER

    async def test_lookup_by_username_is_case_insensitive(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        await repo.add(_user("alice"), password_hash="h")
        assert await repo.get_by_username("ALICE") is not None

    async def test_login_identifier_accepts_username_or_email(self, session: AsyncSession) -> None:
        """The login form has one field; both forms must resolve."""
        repo = SqlAlchemyUserRepository(session)
        await repo.add(_user("alice"), password_hash="h")
        assert await repo.get_by_identifier("alice") is not None
        assert await repo.get_by_identifier("alice@example.test") is not None
        assert await repo.get_by_identifier("nobody") is None

    async def test_password_hash_is_stored_separately_from_the_entity(
        self, session: AsyncSession
    ) -> None:
        """The User entity carries no credential material, by design."""
        repo = SqlAlchemyUserRepository(session)
        created = await repo.add(_user("alice"), password_hash="secret-hash")
        assert await repo.get_password_hash(created.id) == "secret-hash"
        assert "secret-hash" not in repr(created)

    async def test_public_profile_lookup_excludes_private_accounts(
        self, session: AsyncSession
    ) -> None:
        """Spec B.5, enforced in SQL rather than by a later filter."""
        repo = SqlAlchemyUserRepository(session)
        await repo.add(_user("alice", Visibility.PUBLIC), password_hash="h")
        await repo.add(_user("bruno", Visibility.PRIVATE), password_hash="h")

        assert await repo.get_public_profile("alice") is not None
        assert await repo.get_public_profile("bruno") is None
        # Still findable by exact username, so they can be invited.
        assert await repo.get_by_username("bruno") is not None

    async def test_search_excludes_private_profiles(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        await repo.add(_user("alicia", Visibility.PUBLIC), password_hash="h")
        await repo.add(_user("alicja", Visibility.PRIVATE), password_hash="h")

        found = {u.username for u in await repo.search("alici")}
        assert "alicia" in found
        assert "alicja" not in found

    async def test_existence_checks(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        await repo.add(_user("alice"), password_hash="h")
        assert await repo.username_exists("alice") is True
        assert await repo.username_exists("nobody") is False
        assert await repo.email_exists("alice@example.test") is True


class TestProjectRepository:
    """Projects, the public feed, and visibility scoping."""

    async def test_round_trip_preserves_value_objects(self, session: AsyncSession) -> None:
        users = SqlAlchemyUserRepository(session)
        repo = SqlAlchemyProjectRepository(session)
        owner = await users.add(_user("alice"), password_hash="h")

        created = await repo.add(_project(owner.id, "NG_00", Visibility.PUBLIC))
        fetched = await repo.get_by_code(ProjectCode("NG_00"))

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.code == ProjectCode("NG_00")
        assert fetched.location.latitude == pytest.approx(13.6218)
        assert isinstance(fetched.progress_pct, ProgressPct)

    async def test_public_feed_excludes_private_projects(self, session: AsyncSession) -> None:
        """The single most important query in the system to get right."""
        users = SqlAlchemyUserRepository(session)
        repo = SqlAlchemyProjectRepository(session)
        owner = await users.add(_user("alice"), password_hash="h")

        await repo.add(_project(owner.id, "PB_00", Visibility.PUBLIC))
        await repo.add(_project(owner.id, "PV_00", Visibility.PRIVATE))

        codes = {p.code.value for p in (await repo.list_public_feed()).items}
        assert "PB_00" in codes
        assert "PV_00" not in codes

    async def test_public_feed_excludes_archived_projects(self, session: AsyncSession) -> None:
        users = SqlAlchemyUserRepository(session)
        repo = SqlAlchemyProjectRepository(session)
        owner = await users.add(_user("alice"), password_hash="h")
        await repo.add(
            _project(
                owner.id,
                "AR_00",
                Visibility.PUBLIC,
                archived_at=datetime.now(UTC),
                status=ProjectStatus.ARCHIVED,
            )
        )
        assert (await repo.list_public_feed()).items == ()

    async def test_get_public_by_code_hides_private_projects(self, session: AsyncSession) -> None:
        """Returns None so the API can answer 404, never 403.

        A 403 would confirm the project exists, which is itself a disclosure.
        """
        users = SqlAlchemyUserRepository(session)
        repo = SqlAlchemyProjectRepository(session)
        owner = await users.add(_user("alice"), password_hash="h")
        await repo.add(_project(owner.id, "PV_00", Visibility.PRIVATE))

        assert await repo.get_public_by_code(ProjectCode("PV_00")) is None
        # ...but an authorized caller can still reach it.
        assert await repo.get_by_code(ProjectCode("PV_00")) is not None

    async def test_feed_pagination_is_stable(self, session: AsyncSession) -> None:
        users = SqlAlchemyUserRepository(session)
        repo = SqlAlchemyProjectRepository(session)
        owner = await users.add(_user("alice"), password_hash="h")
        base = datetime.now(UTC)
        for index in range(5):
            await repo.add(
                _project(
                    owner.id,
                    f"PG_{index:02d}",
                    Visibility.PUBLIC,
                    last_capture_at=base - timedelta(hours=index),
                )
            )

        first = await repo.list_public_feed(limit=2)
        assert len(first) == 2
        assert first.has_more

        second = await repo.list_public_feed(limit=2, cursor=first.next_cursor)
        first_ids = {p.id for p in first.items}
        second_ids = {p.id for p in second.items}
        assert not (first_ids & second_ids), "pages must not overlap"

    async def test_malformed_cursor_does_not_raise(self, session: AsyncSession) -> None:
        """Cursors appear in URLs; a truncated one must not 500."""
        repo = SqlAlchemyProjectRepository(session)
        page = await repo.list_public_feed(cursor="not-a-real-cursor")
        assert page.items == ()

    async def test_list_for_user_includes_accepted_memberships(self, session: AsyncSession) -> None:
        users = SqlAlchemyUserRepository(session)
        projects = SqlAlchemyProjectRepository(session)
        members = SqlAlchemyProjectMemberRepository(session)

        owner = await users.add(_user("alice"), password_hash="h")
        collaborator = await users.add(_user("bruno"), password_hash="h")
        project = await projects.add(_project(owner.id, "NG_00", Visibility.PRIVATE))

        from app.domain.entities import ProjectMember

        await members.add(
            ProjectMember(
                id=uuid4(),
                project_id=project.id,
                user_id=collaborator.id,
                membership_role=MembershipRole.MANAGER,
                membership_status=MembershipStatus.ACCEPTED,
            )
        )

        assert len(await projects.list_for_user(collaborator.id)) == 1

    async def test_pending_membership_does_not_grant_visibility(
        self, session: AsyncSession
    ) -> None:
        """An invitee sees nothing of the project until they accept."""
        users = SqlAlchemyUserRepository(session)
        projects = SqlAlchemyProjectRepository(session)
        members = SqlAlchemyProjectMemberRepository(session)

        owner = await users.add(_user("alice"), password_hash="h")
        invitee = await users.add(_user("carla"), password_hash="h")
        project = await projects.add(_project(owner.id, "NG_00", Visibility.PRIVATE))

        from app.domain.entities import ProjectMember

        await members.add(
            ProjectMember(
                id=uuid4(),
                project_id=project.id,
                user_id=invitee.id,
                membership_role=MembershipRole.VIEWER,
                membership_status=MembershipStatus.PENDING,
            )
        )

        assert await projects.list_for_user(invitee.id) == ()

    async def test_code_exists(self, session: AsyncSession) -> None:
        users = SqlAlchemyUserRepository(session)
        repo = SqlAlchemyProjectRepository(session)
        owner = await users.add(_user("alice"), password_hash="h")
        await repo.add(_project(owner.id, "NG_00", Visibility.PUBLIC))

        assert await repo.code_exists(ProjectCode("NG_00")) is True
        assert await repo.code_exists(ProjectCode("ZZ_99")) is False


class TestDeviceRepository:
    """Devices and face allocation."""

    async def test_face_taken_ignores_revoked_devices(self, session: AsyncSession) -> None:
        """Unpairing frees the slot for a replacement camera."""
        from app.domain.entities import Device

        users = SqlAlchemyUserRepository(session)
        projects = SqlAlchemyProjectRepository(session)
        devices = SqlAlchemyDeviceRepository(session)

        owner = await users.add(_user("alice"), password_hash="h")
        project = await projects.add(_project(owner.id, "NG_00", Visibility.PUBLIC))

        device = await devices.add(
            Device(
                id=uuid4(),
                project_id=project.id,
                device_name="ESP_NG_00_FD",
                face=CameraFace.FRONT_DIAGONAL,
                weight=1.5,
            ),
            secret_hash="hashed-secret",
        )
        assert await devices.face_taken(project.id, CameraFace.FRONT_DIAGONAL) is True

        await devices.revoke(device.id, datetime.now(UTC))
        assert await devices.face_taken(project.id, CameraFace.FRONT_DIAGONAL) is False

    async def test_secret_hash_is_write_only_through_the_entity(
        self, session: AsyncSession
    ) -> None:
        from app.domain.entities import Device

        users = SqlAlchemyUserRepository(session)
        projects = SqlAlchemyProjectRepository(session)
        devices = SqlAlchemyDeviceRepository(session)

        owner = await users.add(_user("alice"), password_hash="h")
        project = await projects.add(_project(owner.id, "NG_00", Visibility.PUBLIC))
        device = await devices.add(
            Device(
                id=uuid4(),
                project_id=project.id,
                device_name="ESP_NG_00_FD",
                face=CameraFace.FRONT_DIAGONAL,
                weight=1.5,
            ),
            secret_hash="hashed-secret",
        )

        assert "hashed-secret" not in repr(device)
        assert await devices.get_secret_hash(device.id) == "hashed-secret"

    async def test_capture_schedule_round_trips_through_jsonb(self, session: AsyncSession) -> None:
        from app.domain.entities import CaptureSchedule, Device

        users = SqlAlchemyUserRepository(session)
        projects = SqlAlchemyProjectRepository(session)
        devices = SqlAlchemyDeviceRepository(session)

        owner = await users.add(_user("alice"), password_hash="h")
        project = await projects.add(_project(owner.id, "NG_00", Visibility.PUBLIC))
        schedule = CaptureSchedule(times=("06:30", "12:00", "17:45"), jitter_seconds=60)
        device = await devices.add(
            Device(
                id=uuid4(),
                project_id=project.id,
                device_name="ESP_NG_00_B",
                face=CameraFace.BACK,
                weight=1.0,
                capture_schedule=schedule,
            ),
            secret_hash="h",
        )

        fetched = await devices.get(device.id)
        assert fetched is not None
        assert fetched.capture_schedule.times == ("06:30", "12:00", "17:45")
        assert fetched.capture_schedule.jitter_seconds == 60


class TestImageRepository:
    """Ingest idempotency and race-free sequence allocation."""

    async def test_sequence_numbers_increment_within_a_day(self, session: AsyncSession) -> None:
        from app.domain.entities import Image

        users = SqlAlchemyUserRepository(session)
        projects = SqlAlchemyProjectRepository(session)
        images = SqlAlchemyImageRepository(session)

        owner = await users.add(_user("alice"), password_hash="h")
        project = await projects.add(_project(owner.id, "NG_00", Visibility.PUBLIC))
        day = date(2026, 8, 13)

        assert await images.next_sequence_number(project.id, day) == 1

        await images.add(
            Image(
                id=uuid4(),
                project_id=project.id,
                filename="NG_00_20260813T070000Z_001.jpg",
                storage_key="k1",
                captured_at=datetime(2026, 8, 13, 7, 0, tzinfo=UTC),
                sha256="c" * 64,
                seq_number=1,
            )
        )
        assert await images.next_sequence_number(project.id, day) == 2
        # A different day restarts the sequence.
        assert await images.next_sequence_number(project.id, date(2026, 8, 14)) == 1

    async def test_lookup_by_hash_supports_ingest_idempotency(self, session: AsyncSession) -> None:
        from app.domain.entities import Image

        users = SqlAlchemyUserRepository(session)
        projects = SqlAlchemyProjectRepository(session)
        images = SqlAlchemyImageRepository(session)

        owner = await users.add(_user("alice"), password_hash="h")
        project = await projects.add(_project(owner.id, "NG_00", Visibility.PUBLIC))
        digest = "d" * 64
        await images.add(
            Image(
                id=uuid4(),
                project_id=project.id,
                filename="NG_00_20260813T070000Z_001.jpg",
                storage_key="k",
                captured_at=datetime.now(UTC),
                sha256=digest,
            )
        )

        assert await images.get_by_hash(project.id, digest) is not None
        assert await images.get_by_hash(project.id, "e" * 64) is None


class TestAIModelRepository:
    """Model registry activation."""

    async def test_activating_a_model_deactivates_the_previous_one(
        self, session: AsyncSession
    ) -> None:
        """A partial unique index permits only one active model per kind."""
        from app.domain.entities import AIModel

        repo = SqlAlchemyAIModelRepository(session)
        first = await repo.add(
            AIModel(
                id=uuid4(),
                name="resnet18",
                kind=ModelKind.CLASSIFIER,
                architecture="resnet18",
                version="v1",
                is_active=True,
            )
        )
        second = await repo.add(
            AIModel(
                id=uuid4(),
                name="resnet18",
                kind=ModelKind.CLASSIFIER,
                architecture="resnet18",
                version="v2",
            )
        )

        await repo.set_active(second.id)

        active = await repo.get_active(ModelKind.CLASSIFIER)
        assert active is not None
        assert active.id == second.id
        refetched_first = await repo.get(first.id)
        assert refetched_first is not None
        assert refetched_first.is_active is False

    async def test_stub_model_is_recognised(self, session: AsyncSession) -> None:
        """A registry entry with no weights is the pre-training stand-in."""
        from app.domain.entities import AIModel

        repo = SqlAlchemyAIModelRepository(session)
        stub = await repo.add(
            AIModel(
                id=uuid4(),
                name="stub-classifier",
                kind=ModelKind.CLASSIFIER,
                architecture="stub",
                version="0.0.1",
                weights_key=None,
            )
        )
        assert stub.is_stub is True
