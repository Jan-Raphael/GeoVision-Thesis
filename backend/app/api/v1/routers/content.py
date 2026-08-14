"""Reference assets and remarks on a project."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Path, Response, UploadFile, status

from app.api.deps import (
    AccessContextDep,
    AssetRepoDep,
    CurrentUser,
    RemarkRepoDep,
    SettingsDep,
    StorageDep,
    require_permission,
)
from app.api.route import TransactionalRoute
from app.api.schemas.common import MessageResponse
from app.api.schemas.projects import (
    AssetResponse,
    CreateRemarkRequest,
    RemarkResponse,
    UpdateRemarkRequest,
)
from app.api.v1.presenters import present_asset, present_remark
from app.application.ports.storage import StorageError
from app.application.use_cases.content import (
    CreateRemark,
    DeleteAsset,
    DeleteRemark,
    UpdateRemark,
    UploadReferenceAsset,
)
from app.core.exceptions import NotFoundError, PayloadTooLargeError
from app.domain.enums import AssetKind, Permission
from app.domain.services.authorization import AccessContext

router = APIRouter(
    prefix="/projects/{project_id}", tags=["content"], route_class=TransactionalRoute
)

ProjectId = Annotated[UUID, Path(description="Project id")]
AssetId = Annotated[UUID, Path(description="Asset id")]
RemarkId = Annotated[UUID, Path(description="Remark id")]


# ---------------------------------------------------------------------------
# Reference assets
# ---------------------------------------------------------------------------


@router.get("/assets", summary="List reference assets", response_model=list[AssetResponse])
async def list_assets(
    project_id: ProjectId,
    access: AccessContextDep,
    assets: AssetRepoDep,
    storage: StorageDep,
) -> list[AssetResponse]:
    """Blueprints, 3-D renders, and reference documents."""
    _ = access
    found = await assets.list_for_project(project_id)
    return [present_asset(asset, await storage.signed_url(asset.storage_key)) for asset in found]


@router.post(
    "/assets",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a blueprint or 3-D render",
    response_model=AssetResponse,
)
async def upload_asset(
    project_id: ProjectId,
    access: Annotated[AccessContext, Depends(require_permission(Permission.ASSET_UPLOAD))],
    assets: AssetRepoDep,
    storage: StorageDep,
    settings: SettingsDep,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="PDF, JPEG, PNG, or WebP")],
    kind: Annotated[AssetKind, Form()] = AssetKind.BLUEPRINT,
    notes: Annotated[str | None, Form()] = None,
    is_public: Annotated[bool, Form()] = False,
) -> AssetResponse:
    """Attach a reference file to the project.

    The type is decided by the file's **magic bytes**, never by its extension or
    the browser's Content-Type - both are attacker-controlled. An executable
    renamed to ``.pdf`` is rejected.

    Note the scope boundary: the render or blueprint is stored, displayed, and
    included in reports, but **is not consumed by the model** in v1 (ADR-010).
    """
    _ = access
    payload = await file.read()
    if len(payload) > settings.max_asset_upload_bytes:
        limit_mb = settings.max_asset_upload_bytes // (1024 * 1024)
        msg = f"File is too large. The limit is {limit_mb} MB."
        raise PayloadTooLargeError(msg)

    asset = await UploadReferenceAsset(
        assets, storage, max_bytes=settings.max_asset_upload_bytes
    ).execute(
        project_id,
        uploaded_by=user.id,
        payload=payload,
        filename=file.filename or "upload",
        kind=kind,
        notes=notes,
        is_public=is_public,
    )
    return present_asset(asset, await storage.signed_url(asset.storage_key))


@router.get(
    "/assets/{asset_id}/download",
    summary="Download a reference asset",
    response_class=Response,
)
async def download_asset(
    project_id: ProjectId,
    asset_id: AssetId,
    access: AccessContextDep,
    assets: AssetRepoDep,
    storage: StorageDep,
) -> Response:
    """Stream an asset's bytes.

    Permission is re-checked here rather than trusted from the URL: the local
    storage backend cannot issue genuinely signed URLs, so the API stays the
    access-control boundary whichever backend is configured.
    """
    _ = access
    asset = await assets.get(asset_id)
    if asset is None or asset.project_id != project_id:
        msg = "Asset not found."
        raise NotFoundError(msg)

    try:
        payload = await storage.get(asset.storage_key)
    except StorageError as exc:
        msg = "That file is no longer available."
        raise NotFoundError(msg) from exc

    disposition = f'attachment; filename="{asset.original_filename}"'
    return Response(
        content=payload,
        media_type=asset.mime_type,
        headers={
            # `attachment`, not `inline`: serving a user-supplied PDF inline
            # lets it run script in the site's own origin in some viewers.
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/assets/{asset_id}", summary="Delete a reference asset", response_model=MessageResponse
)
async def delete_asset(
    project_id: ProjectId,
    asset_id: AssetId,
    access: Annotated[AccessContext, Depends(require_permission(Permission.ASSET_UPLOAD))],
    assets: AssetRepoDep,
    storage: StorageDep,
) -> MessageResponse:
    """Remove an asset and its stored bytes."""
    _ = access
    await DeleteAsset(assets, storage).execute(project_id, asset_id)
    return MessageResponse(message="Asset deleted.")


# ---------------------------------------------------------------------------
# Remarks
# ---------------------------------------------------------------------------


@router.get("/remarks", summary="List remarks", response_model=list[RemarkResponse])
async def list_remarks(
    project_id: ProjectId,
    access: AccessContextDep,
    remarks: RemarkRepoDep,
) -> list[RemarkResponse]:
    """Notes on the project, newest first - system-generated and manual."""
    _ = access
    found = await remarks.list_for_project(project_id)
    return [present_remark(remark) for remark in found]


@router.post(
    "/remarks",
    status_code=status.HTTP_201_CREATED,
    summary="Write a remark",
    response_model=RemarkResponse,
)
async def create_remark(
    project_id: ProjectId,
    payload: CreateRemarkRequest,
    access: Annotated[AccessContext, Depends(require_permission(Permission.REMARK_WRITE))],
    remarks: RemarkRepoDep,
    user: CurrentUser,
) -> RemarkResponse:
    """Add a note.

    Weather remarks accept an effective window, so "work suspended for the
    typhoon" appears beside the delay it explains rather than as an undated note.
    """
    _ = access
    remark = await CreateRemark(remarks).execute(
        project_id,
        author_id=user.id,
        message=payload.message,
        remark_type=payload.remark_type,
        severity=payload.severity,
        is_public=payload.is_public,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
    )
    return present_remark(remark)


@router.patch("/remarks/{remark_id}", summary="Edit a remark", response_model=RemarkResponse)
async def update_remark(
    project_id: ProjectId,
    remark_id: RemarkId,
    payload: UpdateRemarkRequest,
    access: Annotated[AccessContext, Depends(require_permission(Permission.REMARK_WRITE))],
    remarks: RemarkRepoDep,
) -> RemarkResponse:
    """Edit a manual remark.

    System-generated remarks are immutable: they record what the system
    observed, and letting a user rewrite "progress regression detected" would
    destroy the audit value of the whole feed.
    """
    _ = access
    remark = await UpdateRemark(remarks).execute(
        project_id,
        remark_id,
        message=payload.message,
        severity=payload.severity,
        is_public=payload.is_public,
    )
    return present_remark(remark)


@router.delete("/remarks/{remark_id}", summary="Delete a remark", response_model=MessageResponse)
async def delete_remark(
    project_id: ProjectId,
    remark_id: RemarkId,
    access: Annotated[AccessContext, Depends(require_permission(Permission.REMARK_WRITE))],
    remarks: RemarkRepoDep,
) -> MessageResponse:
    """Delete a manual remark."""
    _ = access
    await DeleteRemark(remarks).execute(project_id, remark_id)
    return MessageResponse(message="Remark deleted.")
