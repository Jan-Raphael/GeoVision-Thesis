"""Daily sequence allocation under concurrency.

Separated from the ingest API tests for a reason that matters: the shared test
``session`` fixture puts every request in **one** transaction, and an advisory
lock taken twice in the same transaction is reentrant. A concurrency test run
through that fixture would pass whether or not the lock existed — it would prove
nothing while looking thorough.

So these tests open genuinely independent connections, which is the only setup
where ``pg_advisory_xact_lock`` does any work.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.entities import Image, Project, User
from app.domain.enums import ImageSource, ImageStatus, ProfessionalRole, Visibility
from app.domain.value_objects import GeoPoint, ProjectCode
from app.infrastructure.db import models
from app.infrastructure.repositories import (
    SqlAlchemyImageRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyUserRepository,
)
from app.infrastructure.repositories.image import advisory_lock_key

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

DAY = date(2026, 8, 14)
CAPTURED = datetime(2026, 8, 14, 7, 0, tzinfo=UTC)


class TestAdvisoryLockKey:
    """The key must be the same everywhere, or the lock protects nothing."""

    def test_it_is_stable_across_processes(self) -> None:
        """Python's ``hash()`` is per-process randomised; this must not be.

        Two uvicorn workers computing different keys would take different locks
        and serialise nothing — and every single-process test would still pass,
        which is what makes this worth pinning to a literal.
        """
        key = advisory_lock_key(UUID("11111111-2222-4333-8444-555555555555"), DAY)
        assert key == advisory_lock_key(UUID("11111111-2222-4333-8444-555555555555"), DAY)
        assert key == 4300696443291658576

    def test_different_projects_do_not_share_a_key(self) -> None:
        """Otherwise one busy site would block uploads on an unrelated one."""
        assert advisory_lock_key(uuid4(), DAY) != advisory_lock_key(uuid4(), DAY)

    def test_different_days_do_not_share_a_key(self) -> None:
        project = uuid4()
        assert advisory_lock_key(project, DAY) != advisory_lock_key(
            project, DAY + timedelta(days=1)
        )

    def test_it_fits_a_signed_bigint(self) -> None:
        """``pg_advisory_xact_lock`` takes int8; an overflow would raise."""
        for _ in range(200):
            assert 0 <= advisory_lock_key(uuid4(), DAY) <= 2**63 - 1


@pytest.fixture
async def committed_project(engine: AsyncEngine) -> AsyncIterator[Project]:
    """A project that really exists in the database, cleaned up afterwards.

    Committed rather than rolled back because concurrent transactions have to be
    able to *see* it. The teardown removes it so the rest of the suite is
    unaffected.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    owner = User(
        id=uuid4(),
        username=f"seq_{uuid4().hex[:8]}",
        email=f"seq_{uuid4().hex[:8]}@example.test",
        full_name="Sequence Tester",
        professional_role=ProfessionalRole.ENGINEER,
    )
    project = Project(
        id=uuid4(),
        owner_id=owner.id,
        name="Sequence Site",
        code=ProjectCode(f"SQ_{uuid4().int % 100:02d}"),
        location_label="Naga City",
        location=GeoPoint(13.6218, 123.1948),
        start_date=date(2026, 1, 1),
        deadline_date=date(2026, 12, 31),
        visibility=Visibility.PRIVATE,
    )

    async with factory() as setup:
        await SqlAlchemyUserRepository(setup).add(owner, password_hash="x")
        await SqlAlchemyProjectRepository(setup).add(project)
        await setup.commit()

    yield project

    async with factory() as teardown:
        await teardown.execute(
            delete(models.ImageModel).where(models.ImageModel.project_id == project.id)
        )
        await teardown.execute(
            delete(models.ProjectModel).where(models.ProjectModel.id == project.id)
        )
        await teardown.execute(delete(models.UserModel).where(models.UserModel.id == owner.id))
        await teardown.commit()


async def _allocate_and_insert(
    factory: async_sessionmaker[AsyncSession], project: Project, offset: int
) -> int:
    """Do one full allocate-then-insert cycle in its own transaction."""
    async with factory() as session:
        repo = SqlAlchemyImageRepository(session)
        seq = await repo.next_sequence_number(project.id, DAY)
        captured = CAPTURED + timedelta(seconds=offset)
        await repo.add(
            Image(
                id=uuid4(),
                project_id=project.id,
                device_id=None,
                filename=Image.build_filename(project.code, captured, seq),
                storage_key=f"projects/{project.id}/images/{seq}.jpg",
                captured_at=captured,
                sha256=f"{offset:064x}",
                source=ImageSource.DEVICE,
                status=ImageStatus.PENDING,
                seq_number=seq,
            )
        )
        await session.commit()
    return seq


class TestConcurrentAllocation:
    """Twenty cameras uploading at the same instant."""

    async def test_twenty_concurrent_uploads_produce_no_duplicates_or_gaps(
        self, engine: AsyncEngine, committed_project: Project
    ) -> None:
        """The vault's testing procedure, verbatim: 001-020, none missing.

        Without the advisory lock every one of these transactions reads the same
        ``MAX(seq_number)`` and they all write ``001``. That failure is quiet —
        the uploads succeed, and one image silently overwrites another in object
        storage under a filename an owner is expected to be able to reconcile
        against a site diary.
        """
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)

        sequences = await asyncio.gather(
            *(_allocate_and_insert(factory, committed_project, index) for index in range(20))
        )

        assert sorted(sequences) == list(range(1, 21)), (
            f"expected 1..20 with no duplicates or gaps, got {sorted(sequences)}"
        )

    async def test_the_lock_is_actually_held(
        self, engine: AsyncEngine, committed_project: Project
    ) -> None:
        """Prove the lock exists rather than inferring it from a passing test.

        A green concurrency test can also mean "the work finished too fast to
        overlap". Asking PostgreSQL directly removes that doubt.
        """
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        key = advisory_lock_key(committed_project.id, DAY)

        async with factory() as holder:
            await SqlAlchemyImageRepository(holder).next_sequence_number(committed_project.id, DAY)
            async with factory() as observer:
                held = await observer.execute(
                    text(
                        "SELECT count(*) FROM pg_locks "
                        "WHERE locktype = 'advisory' AND objid = :low AND objsubid = 1"
                    ),
                    {"low": key & 0xFFFFFFFF},
                )
                assert held.scalar_one() >= 1, "no advisory lock was taken"
            await holder.rollback()

    async def test_sequences_are_scoped_to_the_day(
        self, engine: AsyncEngine, committed_project: Project
    ) -> None:
        """Numbering restarts each UTC day, so filenames stay short and readable."""
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        await _allocate_and_insert(factory, committed_project, 0)

        async with factory() as session:
            repo = SqlAlchemyImageRepository(session)
            assert await repo.next_sequence_number(committed_project.id, DAY) == 2
            assert (
                await repo.next_sequence_number(committed_project.id, DAY + timedelta(days=1))
            ) == 1
