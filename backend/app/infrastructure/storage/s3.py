"""S3-compatible object storage (MinIO in Docker, S3 in production).

boto3 is synchronous, so every call runs in a worker thread; blocking the event
loop on a network round-trip would stall every other request the process is
serving.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.application.ports.storage import StorageError, StoredObject

if TYPE_CHECKING:
    from app.core.config import Settings

__all__ = ["S3ObjectStorage"]


class S3ObjectStorage:
    """Stores objects in an S3-compatible bucket."""

    def __init__(self, settings: Settings) -> None:
        """Build a client from settings."""
        import boto3
        from botocore.config import Config

        self._bucket = settings.s3_bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            use_ssl=settings.s3_use_ssl,
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    async def put(
        self,
        key: str,
        payload: bytes,
        *,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        """Upload an object."""

        def _put() -> dict[str, Any]:
            result: dict[str, Any] = self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=payload,
                ContentType=content_type,
                Metadata=metadata or {},
            )
            return result

        try:
            result = await asyncio.to_thread(_put)
        except Exception as exc:
            msg = f"could not store {key!r}: {exc}"
            raise StorageError(msg) from exc

        return StoredObject(
            key=key,
            size_bytes=len(payload),
            content_type=content_type,
            etag=str(result.get("ETag", "")).strip('"') or None,
            stored_at=datetime.now(UTC),
        )

    async def get(self, key: str) -> bytes:
        """Download an object."""

        def _get() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body: bytes = response["Body"].read()
            return body

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            msg = f"could not read {key!r}: {exc}"
            raise StorageError(msg) from exc

    async def delete(self, key: str) -> bool:
        """Delete an object.

        S3 deletes are idempotent and do not report whether the key existed, so
        existence is checked first to give the caller a truthful answer.
        """
        if not await self.exists(key):
            return False

        def _delete() -> None:
            self._client.delete_object(Bucket=self._bucket, Key=key)

        try:
            await asyncio.to_thread(_delete)
        except Exception as exc:
            msg = f"could not delete {key!r}: {exc}"
            raise StorageError(msg) from exc
        return True

    async def exists(self, key: str) -> bool:
        """Whether an object exists."""

        def _head() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
            except Exception:
                return False
            return True

        return await asyncio.to_thread(_head)

    async def signed_url(self, key: str, *, expires_in: int = 3600) -> str:
        """A genuinely pre-signed URL, so downloads bypass the API process."""

        def _sign() -> str:
            url: str = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return url

        try:
            return await asyncio.to_thread(_sign)
        except Exception as exc:
            msg = f"could not sign a URL for {key!r}: {exc}"
            raise StorageError(msg) from exc

    async def ensure_bucket(self) -> None:
        """Create the bucket if it is missing.

        MinIO starts empty, so without this the first upload fails with
        NoSuchBucket. Harmless against a bucket that already exists.
        """

        def _ensure() -> None:
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except Exception:
                self._client.create_bucket(Bucket=self._bucket)

        await asyncio.to_thread(_ensure)
