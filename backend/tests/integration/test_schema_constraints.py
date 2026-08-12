"""Tests that the database itself refuses invalid data.

Application-level validation is not enough. Bugs happen, migrations get run by
hand, and a database that *permits* a 300 % progress value will eventually
contain one. These tests prove the constraints in the schema are real.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.enums import (
    ApprovalState,
    CameraFace,
    MacroStage,
    MembershipRole,
    MembershipStatus,
    ModelKind,
    ProfessionalRole,
    Visibility,
)
from app.infrastructure.db import models

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _make_user(session: AsyncSession, username: str = "alice") -> models.UserModel:
    """Insert a minimal valid user."""
    user = models.UserModel(
        username=username,
        email=f"{username}@example.test",
        password_hash="hash",
        full_name="Test User",
        professional_role=ProfessionalRole.ENGINEER,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_project(
    session: AsyncSession, owner: models.UserModel, code: str = "NG_00", **kwargs: object
) -> models.ProjectModel:
    """Insert a minimal valid project."""
    values: dict[str, object] = {
        "owner_id": owner.id,
        "name": "Test Project",
        "project_code": code,
        "location_label": "Naga City",
        "latitude": Decimal("13.621800"),
        "longitude": Decimal("123.194800"),
        "start_date": date(2026, 1, 1),
        "deadline_date": date(2026, 12, 31),
    }
    values.update(kwargs)
    project = models.ProjectModel(**values)  # type: ignore[arg-type]
    session.add(project)
    await session.flush()
    return project


class TestUniqueness:
    """Unique constraints that prevent duplicate or conflicting rows."""

    async def test_duplicate_username_is_rejected(self, session: AsyncSession) -> None:
        await _make_user(session, "alice")
        with pytest.raises(IntegrityError):
            await _make_user(session, "alice")

    async def test_username_is_case_insensitive(self, session: AsyncSession) -> None:
        """``citext`` prevents ``Alice`` and ``alice`` both registering."""
        await _make_user(session, "alice")
        session.add(
            models.UserModel(
                username="ALICE",
                email="other@example.test",
                password_hash="h",
                full_name="Other",
                professional_role=ProfessionalRole.OTHER,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_duplicate_project_code_is_rejected(self, session: AsyncSession) -> None:
        """Codes are globally unique; they are embedded in filenames."""
        owner = await _make_user(session)
        await _make_project(session, owner, "NG_00")
        with pytest.raises(IntegrityError):
            await _make_project(session, owner, "NG_00")

    async def test_one_device_per_project_face(self, session: AsyncSession) -> None:
        owner = await _make_user(session)
        project = await _make_project(session, owner)
        for name in ("ESP_NG_00_FD", "ESP_NG_00_FD2"):
            session.add(
                models.DeviceModel(
                    project_id=project.id,
                    device_name=name,
                    face=CameraFace.FRONT_DIAGONAL,
                    weight=Decimal("1.5"),
                )
            )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_duplicate_image_hash_per_project_is_rejected(
        self, session: AsyncSession
    ) -> None:
        """The ingest idempotency guarantee, enforced by the database."""
        owner = await _make_user(session)
        project = await _make_project(session, owner)
        digest = "a" * 64
        for index in (1, 2):
            session.add(
                models.ImageModel(
                    project_id=project.id,
                    filename=f"NG_00_20260813T07000{index}Z_001.jpg",
                    storage_key=f"k{index}",
                    captured_at=datetime.now(UTC),
                    sha256=digest,
                )
            )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_duplicate_membership_is_rejected(self, session: AsyncSession) -> None:
        owner = await _make_user(session, "owner")
        member = await _make_user(session, "member")
        project = await _make_project(session, owner)
        for _ in range(2):
            session.add(
                models.ProjectMemberModel(
                    project_id=project.id,
                    user_id=member.id,
                    membership_role=MembershipRole.VIEWER,
                )
            )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_only_one_active_model_per_kind(self, session: AsyncSession) -> None:
        """Enforced by a partial unique index, not by application code."""
        for version in ("v1", "v2"):
            session.add(
                models.AIModelModel(
                    name="resnet18",
                    kind=ModelKind.CLASSIFIER,
                    architecture="resnet18",
                    version=version,
                    is_active=True,
                )
            )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_two_inactive_models_are_fine(self, session: AsyncSession) -> None:
        """The partial index only constrains rows where is_active is true."""
        for version in ("v1", "v2"):
            session.add(
                models.AIModelModel(
                    name="resnet18",
                    kind=ModelKind.CLASSIFIER,
                    architecture="resnet18",
                    version=version,
                    is_active=False,
                )
            )
        await session.flush()


class TestCheckConstraints:
    """Value-range rules the database refuses to violate."""

    async def test_project_code_format_is_enforced(self, session: AsyncSession) -> None:
        owner = await _make_user(session)
        with pytest.raises(IntegrityError):
            await _make_project(session, owner, "ng_00")

    async def test_deadline_must_not_precede_start(self, session: AsyncSession) -> None:
        owner = await _make_user(session)
        with pytest.raises(IntegrityError):
            await _make_project(
                session, owner, start_date=date(2026, 6, 1), deadline_date=date(2026, 1, 1)
            )

    async def test_progress_above_100_is_rejected(self, session: AsyncSession) -> None:
        owner = await _make_user(session)
        with pytest.raises(IntegrityError):
            await _make_project(
                session, owner, progress_pct=Decimal("150"), approval_state=ApprovalState.APPROVED
            )

    async def test_machine_ceiling_requires_approval(self, session: AsyncSession) -> None:
        """A project cannot exceed 80 % without a human sign-off (ADR-007).

        The safety property of the whole system, encoded in the schema so no
        code path — including a future one — can bypass it.
        """
        owner = await _make_user(session)
        with pytest.raises(IntegrityError):
            await _make_project(
                session,
                owner,
                progress_pct=Decimal("95"),
                approval_state=ApprovalState.NOT_READY,
            )

    async def test_approved_project_may_reach_100(self, session: AsyncSession) -> None:
        owner = await _make_user(session)
        project = await _make_project(
            session,
            owner,
            progress_pct=Decimal("100"),
            approval_state=ApprovalState.APPROVED,
        )
        assert project.progress_pct == Decimal("100")

    async def test_out_of_range_latitude_is_rejected(self, session: AsyncSession) -> None:
        owner = await _make_user(session)
        with pytest.raises(IntegrityError):
            await _make_project(session, owner, latitude=Decimal("95.0"))

    async def test_device_name_format_is_enforced(self, session: AsyncSession) -> None:
        owner = await _make_user(session)
        project = await _make_project(session, owner)
        session.add(
            models.DeviceModel(
                project_id=project.id,
                device_name="my-camera",
                face=CameraFace.FRONT,
                weight=Decimal("1.0"),
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_snapshot_window_must_be_ordered(self, session: AsyncSession) -> None:
        owner = await _make_user(session)
        project = await _make_project(session, owner)
        start = datetime.now(UTC)
        session.add(
            models.ProgressSnapshotModel(
                project_id=project.id,
                window_start=start,
                window_end=start - timedelta(days=1),
                raw_pct=Decimal("10"),
                ema_pct=Decimal("10"),
                displayed_pct=Decimal("10"),
                macro_stage=MacroStage.FOUNDATION,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()


class TestCascades:
    """Deleting a project must not leave orphans behind."""

    async def test_deleting_a_project_removes_its_children(self, session: AsyncSession) -> None:
        owner = await _make_user(session)
        project = await _make_project(session, owner)
        device = models.DeviceModel(
            project_id=project.id,
            device_name="ESP_NG_00_FD",
            face=CameraFace.FRONT_DIAGONAL,
            weight=Decimal("1.5"),
        )
        session.add(device)
        await session.flush()
        session.add(
            models.ImageModel(
                project_id=project.id,
                device_id=device.id,
                filename="NG_00_20260813T070000Z_001.jpg",
                storage_key="k",
                captured_at=datetime.now(UTC),
                sha256="b" * 64,
            )
        )
        await session.flush()

        await session.delete(project)
        await session.flush()

        from sqlalchemy import func, select

        for model in (models.DeviceModel, models.ImageModel):
            count = (await session.execute(select(func.count()).select_from(model))).scalar_one()
            assert count == 0, f"{model.__tablename__} rows survived the cascade"

    async def test_user_with_projects_cannot_be_hard_deleted(self, session: AsyncSession) -> None:
        """``ON DELETE RESTRICT``: users are deactivated, never deleted.

        Removing a user would orphan the project history their name is attached
        to, including any approvals they signed.
        """
        owner = await _make_user(session)
        await _make_project(session, owner)
        await session.delete(owner)
        with pytest.raises(IntegrityError):
            await session.flush()


class TestDefaults:
    """Server-side defaults behave as the domain expects."""

    async def test_ids_and_timestamps_are_generated(self, session: AsyncSession) -> None:
        user = await _make_user(session)
        assert user.id is not None
        assert user.created_at is not None
        assert user.created_at.tzinfo is not None, "timestamps must be timezone-aware"

    async def test_project_defaults_to_private(self, session: AsyncSession) -> None:
        """Safe default: a new project is not published until the owner says so."""
        owner = await _make_user(session)
        project = await _make_project(session, owner)
        assert project.visibility is Visibility.PRIVATE
        assert project.progress_pct == Decimal("0.00")
        assert project.approval_state is ApprovalState.NOT_READY

    async def test_membership_defaults_to_pending(self, session: AsyncSession) -> None:
        owner = await _make_user(session, "owner")
        member = await _make_user(session, "member")
        project = await _make_project(session, owner)
        row = models.ProjectMemberModel(
            project_id=project.id,
            user_id=member.id,
            membership_role=MembershipRole.VIEWER,
        )
        session.add(row)
        await session.flush()
        assert row.membership_status is MembershipStatus.PENDING
