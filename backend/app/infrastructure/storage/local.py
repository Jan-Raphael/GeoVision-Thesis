"""Filesystem-backed object storage, for development without MinIO.

Exists so Module 04 is complete and testable before Docker is installed, and so
the test suite never needs a running object store. Production uses
:class:`~app.infrastructure.storage.s3.S3ObjectStorage`; both satisfy the same
port, so nothing above this layer changes when the backend does.

**Not a production backend.** It has no replication, no lifecycle rules, and its
"signed" URLs are not cryptographically signed — see :meth:`signed_url`. The
settings validator refuses to select it outside local development.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.application.ports.storage import StorageError, StoredObject

if TYPE_CHECKING:
    pass

__all__ = ["LocalObjectStorage"]


class LocalObjectStorage:
    """Stores objects as files under a root directory."""

    def __init__(self, root: Path, *, public_base_url: str = "/api/v1/files") -> None:
        """Create the backend.

        Args:
            root: Directory to store objects under. Created if absent.
            public_base_url: Prefix for the URLs :meth:`signed_url` returns.
        """
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._public_base_url = public_base_url.rstrip("/")

    def _resolve(self, key: str) -> Path:
        """Map a key to a path, refusing anything that escapes the root.

        Keys are generated internally, but this backend is the one component
        that turns a string into a filesystem path — so it validates rather than
        trusting its callers. ``../`` in a key would otherwise write anywhere
        the process can reach.
        """
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            msg = f"refusing to access {key!r}: outside the storage root"
            raise StorageError(msg)
        return candidate

    async def put(
        self,
        key: str,
        payload: bytes,
        *,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        """Write an object to disk."""
        path = self._resolve(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temporary file and rename: a crash mid-write then
            # leaves no half-written object that later reads as valid.
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            msg = f"could not store {key!r}: {exc}"
            raise StorageError(msg) from exc

        return StoredObject(
            key=key,
            size_bytes=len(payload),
            content_type=content_type,
            stored_at=datetime.now(UTC),
        )

    async def get(self, key: str) -> bytes:
        """Read an object from disk."""
        path = self._resolve(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            msg = f"could not read {key!r}: {exc}"
            raise StorageError(msg) from exc

    async def delete(self, key: str) -> bool:
        """Delete an object, reporting whether one was there."""
        path = self._resolve(key)

        def _remove() -> bool:
            if not path.is_file():
                return False
            path.unlink()
            return True

        try:
            return await asyncio.to_thread(_remove)
        except OSError as exc:
            msg = f"could not delete {key!r}: {exc}"
            raise StorageError(msg) from exc

    async def exists(self, key: str) -> bool:
        """Whether an object exists."""
        return await asyncio.to_thread(self._resolve(key).is_file)

    async def signed_url(self, key: str, *, expires_in: int = 3600) -> str:
        """Return an application URL for the object.

        Deliberately **not** a real signed URL: there is no separate host to
        sign for. Access control therefore still runs through the API, which is
        why the download route re-checks permissions rather than trusting the
        URL. The S3 backend returns a genuinely pre-signed URL, and the download
        route is written to work with either.
        """
        _ = expires_in
        return f"{self._public_base_url}/{key}"

    async def clear(self) -> None:
        """Delete every stored object. Tests use this; nothing else should."""
        await asyncio.to_thread(shutil.rmtree, self._root, ignore_errors=True)
        with contextlib.suppress(OSError):
            self._root.mkdir(parents=True, exist_ok=True)
