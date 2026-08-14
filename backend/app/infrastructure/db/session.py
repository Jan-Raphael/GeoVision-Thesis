"""Async engine, session factory, and the FastAPI session dependency."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_worker_engine: AsyncEngine | None = None
_worker_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings | None = None, *, pooled: bool = True) -> AsyncEngine:
    """Build a new async engine.

    Args:
        settings: Optional override; defaults to the cached process settings.
        pooled: Whether to keep connections in a pool. ``False`` selects
            ``NullPool`` — see :func:`get_worker_engine` for the one caller that
            needs it and why.

    Returns:
        A configured asyncpg engine.
    """
    settings = settings or get_settings()
    if not pooled:
        return create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            poolclass=NullPool,
            future=True,
        )
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Recycle before typical idle-connection timeouts so a pooled
        # connection is never handed out already dead.
        pool_recycle=1800,
        pool_pre_ping=True,
        future=True,
    )


def get_engine() -> AsyncEngine:
    """Return the process-wide engine, creating it on first use."""
    global _engine  # one engine per process is the intent
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session.

    Commits on success and rolls back on any exception, so a request either
    persists all of its changes or none of them. Repositories therefore never
    call ``commit()`` themselves — transaction scope belongs to the request, not
    to a single query.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


async def dispose_engine() -> None:
    """Close all pooled connections. Called from the app's lifespan shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_worker_engine() -> AsyncEngine:
    """Return the worker's engine — deliberately **unpooled**.

    Each Celery task calls :func:`asyncio.run`, which creates a fresh event loop
    and **closes it** when the task returns. An asyncpg connection belongs to the
    loop that opened it, so a pooled connection outlives its loop and is handed
    to the next task already dead. The symptom is not a clean error either: the
    first task or two succeed, then every subsequent one fails with
    ``RuntimeError: Event loop is closed`` surfacing as
    ``AttributeError: 'NoneType' object has no attribute 'send'`` from deep
    inside the driver, and the images simply stop being scored.

    ``NullPool`` opens a connection per checkout and closes it on release, so
    nothing survives the loop that created it. The cost is one connect per task —
    a few milliseconds against an inference that takes hundreds — and in exchange
    the worker is correct across an unbounded number of tasks.

    The API keeps the pooled engine: it serves many requests on **one** long-lived
    loop, which is exactly the case pooling is for.
    """
    global _worker_engine
    if _worker_engine is None:
        _worker_engine = create_engine(pooled=False)
    return _worker_engine


def get_worker_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the worker's session factory, bound to the unpooled engine."""
    global _worker_session_factory
    if _worker_session_factory is None:
        _worker_session_factory = async_sessionmaker(
            bind=get_worker_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _worker_session_factory


async def dispose_worker_engine() -> None:
    """Drop the worker engine, so the next task builds a fresh one."""
    global _worker_engine, _worker_session_factory
    if _worker_engine is not None:
        await _worker_engine.dispose()
        _worker_engine = None
        _worker_session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A transactional session for code with no request around it.

    The Celery worker needs the same commit-or-rollback discipline that
    :func:`get_session` gives a request, but it is not a FastAPI dependency and
    cannot be injected. Same semantics, different entry point — the worker either
    persists a whole image's results or none of them, so a failure halfway
    through never leaves a prediction without its detections.

    Backed by the **unpooled** worker engine; see :func:`get_worker_engine`.
    """
    factory = get_worker_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
