"""SQLAlchemy engine, session factory, and ORM models (Module 02).

`base.Base.metadata` is what Alembic autogenerates against; importing `models`
here guarantees every table is registered before that happens.
"""

from __future__ import annotations

# Imported for the side effect of registering every model on Base.metadata.
from app.infrastructure.db import models
from app.infrastructure.db.base import Base
from app.infrastructure.db.session import (
    create_engine,
    dispose_engine,
    get_engine,
    get_session,
    get_session_factory,
)

__all__ = [
    "Base",
    "create_engine",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_session_factory",
    "models",
]
