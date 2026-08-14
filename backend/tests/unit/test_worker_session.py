"""The worker's database engine must not pool connections across event loops.

This pins a bug that a live worker found and that no other test could: every
Celery task runs ``asyncio.run``, which closes its loop on the way out. A pooled
asyncpg connection belongs to the loop that opened it, so the *next* task
checked out a corpse and failed inside the driver with
``AttributeError: 'NoneType' object has no attribute 'send'``. The first task or
two succeeded, then images silently stopped being scored.

Nothing here touches PostgreSQL — building an engine does not connect — so these
stay unit tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import NullPool

from app.infrastructure.db import session as db

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_engines() -> object:
    """Reset the module singletons around each test."""
    db._engine = None
    db._session_factory = None
    db._worker_engine = None
    db._worker_session_factory = None
    yield
    db._engine = None
    db._session_factory = None
    db._worker_engine = None
    db._worker_session_factory = None


class TestWorkerEngine:
    """Unpooled for the worker, pooled for the API."""

    def test_worker_engine_uses_nullpool(self) -> None:
        """A pooled connection would outlive the loop that opened it."""
        assert isinstance(db.get_worker_engine().pool, NullPool)

    def test_api_engine_still_pools(self) -> None:
        """The API serves many requests on one loop, which is what pooling is for."""
        assert not isinstance(db.get_engine().pool, NullPool)

    def test_worker_and_api_engines_are_distinct(self) -> None:
        assert db.get_worker_engine() is not db.get_engine()

    def test_session_scope_is_bound_to_the_worker_engine(self) -> None:
        """`session_scope` is the worker's entry point and must not borrow the pool."""
        factory = db.get_worker_session_factory()
        assert factory.kw["bind"] is db.get_worker_engine()
        assert isinstance(factory.kw["bind"].pool, NullPool)

    async def test_disposing_the_worker_engine_rebuilds_it(self) -> None:
        """Each task disposes, so the next one must get a fresh engine."""
        first = db.get_worker_engine()
        await db.dispose_worker_engine()
        assert db.get_worker_engine() is not first


class TestTaskRunner:
    """Every task runs its coroutine and then tears the engine down."""

    def test_run_disposes_the_engine_after_the_task(self) -> None:
        from app.worker.inference import _run

        db.get_worker_engine()  # build it, as a task's first query would

        async def work() -> dict[str, str]:
            return {"status": "done"}

        assert _run(work()) == {"status": "done"}
        assert db._worker_engine is None

    def test_the_engine_is_disposed_even_when_the_task_fails(self) -> None:
        """Otherwise one failure would poison every task after it."""
        from app.worker.inference import _run

        db.get_worker_engine()

        async def work() -> dict[str, str]:
            msg = "storage timeout"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="storage timeout"):
            _run(work())
        assert db._worker_engine is None
