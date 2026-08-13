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

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.infrastructure.db.base import Base

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

TEST_DATABASE = "geovision_test"


def _test_settings() -> Settings:
    """Settings pointed at the test database.

    Argon2 is dialled right down and rate limiting is off. Both are deliberate:
    production Argon2 parameters cost ~50 ms per hash, which would add minutes
    to a suite that registers users constantly, and a 3/hour registration limit
    would fail every test after the third.

    The limiter is exercised by its own dedicated test, which switches it back on.
    """
    base = get_settings()
    return base.model_copy(
        update={
            "postgres_db": TEST_DATABASE,
            "db_echo": False,
            "argon2_memory_cost": 64,
            "argon2_time_cost": 1,
            "argon2_parallelism": 1,
            "rate_limit_enabled": False,
            "storage_backend": "local",
            "local_storage_path": Path(tempfile.gettempdir()) / "geovision-test-storage",
        }
    )


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


@pytest.fixture
async def app(session: AsyncSession, test_settings: Settings) -> AsyncIterator[FastAPI]:
    """An application wired to the test database.

    ``get_session`` is overridden to yield the test transaction, so anything a
    request writes is rolled back with the test and never touches the
    development database.
    """
    from app.infrastructure.db.session import get_session
    from app.infrastructure.storage import reset_storage
    from app.main import create_app

    reset_storage()
    application = create_app(test_settings)
    # The limiter is a module-level singleton built from the *global* settings
    # at import time, so `rate_limit_enabled=False` in test settings cannot
    # reach it. Disable it directly, otherwise the 3/hour registration limit
    # fails every test after the third.
    application.state.limiter.enabled = False

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    application.dependency_overrides[get_session] = _override
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP client bound to the test application (no network, no port)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
