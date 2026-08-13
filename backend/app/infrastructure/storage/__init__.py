"""Object storage adapters.

Image binaries and generated documents never enter PostgreSQL (ADR-005): object
storage holds the bytes, the database holds the keys.

Two backends satisfy `app.application.ports.storage.ObjectStorage`. The choice
is configuration, not code: `GV_STORAGE_BACKEND=local|s3`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.infrastructure.storage.local import LocalObjectStorage
from app.infrastructure.storage.s3 import S3ObjectStorage

if TYPE_CHECKING:
    from app.application.ports.storage import ObjectStorage
    from app.core.config import Settings

__all__ = ["LocalObjectStorage", "S3ObjectStorage", "build_storage"]

_storage: ObjectStorage | None = None


def build_storage(settings: Settings) -> ObjectStorage:
    """Construct the configured backend."""
    if settings.storage_backend == "s3":
        return S3ObjectStorage(settings)
    return LocalObjectStorage(settings.local_storage_path)


def get_storage(settings: Settings) -> ObjectStorage:
    """Return the process-wide storage backend, building it on first use."""
    global _storage
    if _storage is None:
        _storage = build_storage(settings)
    return _storage


def reset_storage() -> None:
    """Drop the cached backend. Tests use this after changing settings."""
    global _storage
    _storage = None
