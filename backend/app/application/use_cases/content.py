"""Reference assets, remarks, and contact messages.

Grouped because all three are "things attached to a project (or to the site)"
with the same shape of rules: validate, store, scope by visibility.

.. note::
   The uploaded blueprint or 3-D render is **stored, displayed, and included in
   reports — it is not consumed by the model** (ADR-010). Comparing site photos
   against a plan needs viewpoint registration and plan understanding, which is
   a research project of its own. The thesis states this boundary rather than
   implying capability that is not there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.application.ports.storage import build_asset_key
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.domain.entities import ContactMessage, ReferenceAsset, Remark
from app.domain.enums import AssetKind, RemarkType, Severity
from app.domain.services.file_validation import (
    FileValidationError,
    safe_filename,
    validate_asset_upload,
)

if TYPE_CHECKING:
    from app.application.ports.storage import ObjectStorage
    from app.domain.repositories import (
        ContactMessageRepository,
        ReferenceAssetRepository,
        RemarkRepository,
    )

__all__ = [
    "CreateRemark",
    "DeleteAsset",
    "DeleteRemark",
    "SubmitContactMessage",
    "UpdateRemark",
    "UploadReferenceAsset",
]


class UploadReferenceAsset:
    """Attach a blueprint, render, or reference document to a project."""

    def __init__(
        self,
        assets: ReferenceAssetRepository,
        storage: ObjectStorage,
        *,
        max_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._assets = assets
        self._storage = storage
        self._max_bytes = max_bytes

    async def execute(
        self,
        project_id: UUID,
        *,
        uploaded_by: UUID,
        payload: bytes,
        filename: str,
        kind: AssetKind,
        notes: str | None = None,
        is_public: bool = False,
    ) -> ReferenceAsset:
        """Validate and store an uploaded file.

        The file is identified by its **magic bytes**, not by its extension or
        the browser's ``Content-Type`` — both are attacker-controlled, and
        renaming ``payload.exe`` to ``plan.pdf`` changes neither the bytes nor
        what happens when somebody opens it later.

        The storage key is generated. The client's filename is kept only for
        display, after being stripped of path separators.

        Args:
            project_id: The owning project.
            uploaded_by: Who uploaded it.
            payload: The complete file content.
            filename: The client's filename, for display only.
            kind: Blueprint, 3-D render, reference photo, or document.
            notes: Optional description.
            is_public: Whether anonymous visitors may see it.

        Returns:
            The recorded asset.

        Raises:
            ValidationFailedError: If the file is empty, oversized, or not an
                allowed type.
        """
        try:
            detected = validate_asset_upload(
                payload,
                declared_filename=filename,
                kind=kind,
                max_bytes=self._max_bytes,
            )
        except FileValidationError as exc:
            raise ValidationFailedError(str(exc), code="INVALID_FILE") from exc

        asset_id = uuid4()
        key = build_asset_key(str(project_id), str(asset_id), detected.extension)
        stored = await self._storage.put(
            key,
            payload,
            content_type=detected.mime_type,
            metadata={"project_id": str(project_id), "kind": kind.value},
        )

        return await self._assets.add(
            ReferenceAsset(
                id=asset_id,
                project_id=project_id,
                uploaded_by=uploaded_by,
                kind=kind,
                storage_key=stored.key,
                original_filename=safe_filename(filename),
                # The *detected* type, never the declared one.
                mime_type=detected.mime_type,
                size_bytes=stored.size_bytes,
                notes=notes,
                is_public=is_public,
            )
        )


class DeleteAsset:
    """Remove a reference asset and its stored bytes."""

    def __init__(self, assets: ReferenceAssetRepository, storage: ObjectStorage) -> None:
        """Wire the use case to its collaborators."""
        self._assets = assets
        self._storage = storage

    async def execute(self, project_id: UUID, asset_id: UUID) -> bool:
        """Delete the asset.

        The database row goes first. If the blob delete then fails, the result
        is an orphaned file — wasted space, but nothing user-visible. The
        reverse order would leave a row pointing at bytes that no longer exist,
        which breaks the UI.

        Raises:
            NotFoundError: If the asset does not belong to this project.
        """
        asset = await self._assets.get(asset_id)
        if asset is None or asset.project_id != project_id:
            msg = "Asset not found."
            raise NotFoundError(msg)

        deleted = await self._assets.delete(asset_id)
        if deleted:
            await self._storage.delete(asset.storage_key)
        return deleted


class CreateRemark:
    """Write a note on a project."""

    def __init__(self, remarks: RemarkRepository) -> None:
        """Wire the use case to its collaborators."""
        self._remarks = remarks

    async def execute(
        self,
        project_id: UUID,
        *,
        author_id: UUID,
        message: str,
        remark_type: RemarkType = RemarkType.MANUAL,
        severity: Severity = Severity.INFO,
        is_public: bool = False,
        effective_from: object = None,
        effective_to: object = None,
    ) -> Remark:
        """Create a remark.

        Weather remarks carry an effective window, so "work suspended for the
        typhoon" appears beside the delay it explains rather than as an
        undated note.

        Raises:
            ValidationFailedError: If the message is empty or the dates are
                inverted.
        """
        from datetime import date as date_type

        cleaned = message.strip()
        if not cleaned:
            msg = "A remark needs a message."
            raise ValidationFailedError(msg)

        start = effective_from if isinstance(effective_from, date_type) else None
        end = effective_to if isinstance(effective_to, date_type) else None
        if start and end and end < start:
            msg = "The remark's end date cannot precede its start date."
            raise ValidationFailedError(msg)

        return await self._remarks.add(
            Remark(
                id=uuid4(),
                project_id=project_id,
                remark_type=remark_type,
                severity=severity,
                message=cleaned,
                author_id=author_id,
                is_public=is_public,
                effective_from=start,
                effective_to=end,
            )
        )


class UpdateRemark:
    """Edit a remark."""

    def __init__(self, remarks: RemarkRepository) -> None:
        """Wire the use case to its collaborators."""
        self._remarks = remarks

    async def execute(
        self,
        project_id: UUID,
        remark_id: UUID,
        *,
        message: str | None = None,
        severity: Severity | None = None,
        is_public: bool | None = None,
    ) -> Remark:
        """Apply a partial update.

        Raises:
            NotFoundError: If the remark does not belong to this project.
            ValidationFailedError: If the remark is system-generated.
        """
        from dataclasses import replace

        remark = await self._remarks.get(remark_id)
        if remark is None or remark.project_id != project_id:
            msg = "Remark not found."
            raise NotFoundError(msg)
        if remark.is_system_generated:
            # System remarks are evidence of what the system observed. Letting a
            # user rewrite "progress regression detected" would undermine the
            # audit value of the whole feed.
            msg = "System-generated remarks cannot be edited."
            raise ValidationFailedError(msg, code="SYSTEM_REMARK_IMMUTABLE")

        return await self._remarks.update(
            replace(
                remark,
                message=message.strip() if message is not None else remark.message,
                severity=severity if severity is not None else remark.severity,
                is_public=is_public if is_public is not None else remark.is_public,
            )
        )


class DeleteRemark:
    """Remove a remark."""

    def __init__(self, remarks: RemarkRepository) -> None:
        """Wire the use case to its collaborators."""
        self._remarks = remarks

    async def execute(self, project_id: UUID, remark_id: UUID) -> bool:
        """Delete the remark.

        Raises:
            NotFoundError: If the remark does not belong to this project.
            ValidationFailedError: If it is system-generated.
        """
        remark = await self._remarks.get(remark_id)
        if remark is None or remark.project_id != project_id:
            msg = "Remark not found."
            raise NotFoundError(msg)
        if remark.is_system_generated:
            msg = "System-generated remarks cannot be deleted."
            raise ValidationFailedError(msg, code="SYSTEM_REMARK_IMMUTABLE")
        return await self._remarks.delete(remark_id)


class SubmitContactMessage:
    """Record a message from the public Contact Us form."""

    #: Shorter than this and there is nothing to act on.
    MIN_MESSAGE_LENGTH = 10

    def __init__(self, messages: ContactMessageRepository) -> None:
        """Wire the use case to its collaborators."""
        self._messages = messages

    async def execute(
        self,
        *,
        name: str,
        email: str,
        subject: str,
        message: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ContactMessage:
        """Store the message.

        Persisted rather than emailed: v1 has no mail delivery, and a contact
        form that silently discards messages is broken rather than deferred.
        The owner reads them from the database until delivery exists.

        Raises:
            ValidationFailedError: If the message is too short to act on.
        """
        cleaned = message.strip()
        if len(cleaned) < self.MIN_MESSAGE_LENGTH:
            msg = "Please write a little more so we can help."
            raise ValidationFailedError(msg)

        return await self._messages.add(
            ContactMessage(
                id=uuid4(),
                name=name.strip(),
                email=email.strip(),
                subject=subject.strip(),
                message=cleaned,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
