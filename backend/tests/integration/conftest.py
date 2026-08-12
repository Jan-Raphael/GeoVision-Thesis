"""Fixtures for tests that need a real PostgreSQL.

These run against ``geovision_test``, never the development database. SQLite is
not an option here: the schema depends on native enums, ``citext``, arrays,
JSONB, partial indexes and trigram operators, none of which SQLite has — a test
suite that passed on SQLite would prove nothing about the real deployment.

Each test gets a session wrapped in a transaction that is **rolled back**
afterwards, so tests are isolated and order-independent without re-creating the
schema between them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.infrastructure.db.base import Base

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

TEST_DATABASE = "geovision_test"


def _test_settings() -> Settings:
    """Settings pointed at the test database."""
    base = get_settings()
    return base.model_copy(update={"postgres_db": TEST_DATABASE, "db_echo": False})


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Session-wide settings for the test database."""
    return _test_settings()


@pytest.fixture(scope="session")
async def engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Engine bound to ``geovision_test``, with the schema created once.

    ``create_all`` rather than running migrations: it is far faster, and the
    migration path itself is covered separately by
    ``test_migrations.py``.
    """
    eng = create_async_engine(test_settings.database_url, poolclass=None)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back after the test.

    Nothing a test writes survives it, so tests neither see each other's data
    nor depend on execution order.
    """
    connection = await engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(bind=connection, expire_on_commit=False)
    try:
        async with factory() as db_session:
            yield db_session
    finally:
        # Tests that assert on IntegrityError leave the transaction already
        # aborted, so rolling back unconditionally emits a spurious SAWarning.
        # Check first: warnings that are merely noise train people to ignore
        # warnings that are not.
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
