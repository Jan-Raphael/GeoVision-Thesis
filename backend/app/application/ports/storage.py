"""Outbound port for object storage.

Declared in the application layer so use cases depend on an interface rather
than on boto3 — the layering contract forbids them importing infrastructure at
all. Two implementations satisfy it (``app.infrastructure.storage``):

``LocalObjectStorage``
    Files on disk. What development uses until Docker/MinIO is available, and
    what keeps this module shippable today.
``S3ObjectStorage``
    MinIO in Docker, any S3-compatible service in production.

Reused unchanged by Module 05 (captured images and thumbnails) and Module 10
(generated PDF/CSV reports), so getting the interface right here is worth more
than it looks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = ["ObjectStorage", "StorageError", "StoredObject"]


class StorageError(RuntimeError):
    """The storage backend could not complete an operation."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    """A stored blob's identity and metadata.

    Attributes:
        key: The storage key. **The database stores this, never the bytes**
            (ADR-005).
        size_bytes: Length of the stored content.
        content_type: MIME type as *detected*, not as the client claimed.
        etag: Backend-supplied integrity tag, where available.
        stored_at: When it was written.
    """

    key: str
    size_bytes: int
    content_type: str
    etag: str | None = None
    stored_at: datetime | None = None


class ObjectStorage(Protocol):
    """Somewhere to put bytes and get them back."""

    async def put(
        self,
        key: str,
        payload: bytes,
        *,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        """Store *payload* under *key*, overwriting any existing object.

        Args:
            key: Destination key. Callers generate these; a client-supplied
                filename must never become a key.
            payload: The bytes to store.
            content_type: Detected MIME type.
            metadata: Optional backend metadata.

        Returns:
            A description of what was stored.

        Raises:
            StorageError: If the write fails.
        """
        ...

    async def get(self, key: str) -> bytes:
        """Read an object back.

        Raises:
            StorageError: If the object is missing or unreadable.
        """
        ...

    async def delete(self, key: str) -> bool:
        """Remove an object. Returns whether something was deleted."""
        ...

    async def exists(self, key: str) -> bool:
        """Whether an object exists at *key*."""
        ...

    async def signed_url(self, key: str, *, expires_in: int = 3600) -> str:
        """A time-limited URL a browser can fetch directly.

        Keeps large downloads off the API process. The local backend returns an
        application URL instead of a true pre-signed one — see its docstring for
        why that is an acceptable development-only difference.
        """
        ...


def build_asset_key(project_id: str, asset_id: str, extension: str) -> str:
    """Key for a project reference asset.

    Layout mirrors ``GeoVision-Vault/01-Architecture/Naming-Conventions.md`` §5.
    The client's filename is deliberately absent: it is attacker-controlled, and
    a key built from it invites traversal and collisions.
    """
    return f"projects/{project_id}/assets/{asset_id}{extension}"
