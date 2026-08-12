"""Alembic environment, configured for async SQLAlchemy.

Wiring async Alembic correctly is fiddly and entirely orthogonal to schema
design, so it is done here in Module 01. Module 02 only has to write revisions.

Two things worth knowing:

* The database URL comes from :class:`app.core.config.Settings`, never from
  ``alembic.ini`` - one source of truth, and no credentials in git.
* ``target_metadata`` is imported lazily, so this file works before any ORM
  model exists (Module 01) and picks them up automatically once they do.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy import Connection, MetaData

#: Tables created by PostgreSQL extensions that this project does not manage.
#: Excluding them keeps autogenerate from proposing spurious drops.
UNMANAGED_TABLES = frozenset({"spatial_ref_sys"})

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the DSN assembled from environment variables.
config.set_main_option("sqlalchemy.url", get_settings().database_url)


def _get_target_metadata() -> MetaData | None:
    """Return the ORM metadata, or ``None`` before models exist.

    Module 02 creates ``app.infrastructure.db.base.Base``; until then autogenerate
    has nothing to compare against, which is expected rather than an error.
    """
    try:
        from app.infrastructure.db.base import Base
    except ImportError:
        return None
    else:
        return Base.metadata


target_metadata = _get_target_metadata()


def _include_object(
    obj: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object,
) -> bool:
    """Filter objects out of autogenerate.

    PostGIS and other extensions create tables we do not manage; excluding them
    keeps generated migrations free of spurious drops.
    """
    return not (type_ == "table" and name in UNMANAGED_TABLES)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a database.

    Useful for reviewing exactly what a migration will do before applying it to
    a deployment: ``alembic upgrade head --sql``.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    """Run migrations on an established synchronous connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # compare_type/server_default catch column changes that Alembic would
        # otherwise silently miss - worth the small autogenerate noise.
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        # Keep the version table transactional with the migration itself.
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Create an async engine and run migrations through it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
