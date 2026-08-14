"""Prediction endpoints: image detail, history, reprocessing, and the demo path.

Image routes are **nested under their project** rather than sitting at
``/images/{id}``, for the same reason the device routes are (see the note in
``API-Contract.md``): the permission guard resolves authority from
``(caller, project)``, so a project-less path would have to look the image up
before it could decide whether the caller may know the image exists — and a
403-where-a-404-belonged there discloses other people's capture history. Nesting
makes the guard structural instead of something each handler remembers (ADR-027).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Path, Query, Request, UploadFile, status

from app.api.deps import (
    AccessContextDep,
    AuditDep,
    ClientIPDep,
    CurrentUser,
    DetectionRepoDep,
    ImageRepoDep,
    InferenceGatewayDep,
    PredictionRepoDep,
    SettingsDep,
    StorageDep,
    TaskQueueDep,
    require_permission,
)
from app.api.route import TransactionalRoute
from app.api.schemas.common import PageResponse
from app.api.schemas.predictions import (
    AdHocPredictionResponse,
    HistoryEntryResponse,
    ImageDetailResponse,
    PredictionResponse,
)
from app.api.v1.presenters_ai import (
    present_adhoc,
    present_history_entry,
    present_image_detail,
    present_prediction,
)
from app.application.use_cases.predictions import (
    GetImageDetail,
    GetProjectHistory,
    PredictAdHoc,
    ReprocessImage,
)
from app.core.exceptions import NotFoundError
from app.core.rate_limit import get_limiter
from app.domain.enums import ImageStatus, Permission
from app.domain.services.authorization import AccessContext
from app.infrastructure.audit import AuditAction

router = APIRouter(tags=["predictions"], route_class=TransactionalRoute)
limiter = get_limiter()

ProjectId = Annotated[UUID, Path(description="Project id")]
ImageId = Annotated[UUID, Path(description="Image id")]


@router.get(
    "/projects/{project_id}/images/{image_id}",
    summary="Image detail with prediction and detections",
    response_model=ImageDetailResponse,
    responses={404: {"description": "No such image in this project"}},
)
async def get_image_detail(
    project_id: ProjectId,
    image_id: ImageId,
    access: AccessContextDep,
    images: ImageRepoDep,
    predictions: PredictionRepoDep,
    detections: DetectionRepoDep,
    storage: StorageDep,
) -> ImageDetailResponse:
    """One capture, everything known about it, and signed URLs to the files.

    This is what the lightbox in Module 12 renders: the photograph, the
    predicted stage with its full probability distribution, and the detection
    boxes to overlay on it.
    """
    _ = access
    detail = await GetImageDetail(images, predictions, detections, storage).execute(
        image_id, project_id
    )
    return present_image_detail(detail)


@router.get(
    "/projects/{project_id}/images/{image_id}/prediction",
    summary="Stored prediction for one image",
    response_model=PredictionResponse,
    responses={404: {"description": "No such image, or it has no prediction yet"}},
)
async def get_image_prediction(
    project_id: ProjectId,
    image_id: ImageId,
    access: AccessContextDep,
    images: ImageRepoDep,
    predictions: PredictionRepoDep,
) -> PredictionResponse:
    """Just the classifier's verdict, without the image payload around it.

    Raises:
        NotFoundError: If the image is not in this project, or has not been
            scored yet. A pending image genuinely has no prediction to return,
            and inventing an empty one would let a caller mistake "not yet" for
            "no stage detected".
    """
    _ = access
    image = await images.get(image_id)
    if image is None or image.project_id != project_id:
        msg = "Image not found."
        raise NotFoundError(msg)

    prediction = await predictions.get_for_image(image_id)
    if prediction is None:
        raise NotFoundError(
            "This image has no prediction yet.",
            details={"image_status": image.status.value},
        )
    return present_prediction(prediction)


@router.post(
    "/projects/{project_id}/images/{image_id}/reprocess",
    summary="Re-run the AI over one image",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ImageDetailResponse,
)
async def reprocess_image(
    project_id: ProjectId,
    image_id: ImageId,
    access: Annotated[AccessContext, Depends(require_permission(Permission.PROGRESS_RECOMPUTE))],
    images: ImageRepoDep,
    predictions: PredictionRepoDep,
    detections: DetectionRepoDep,
    storage: StorageDep,
    queue: TaskQueueDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIPDep,
) -> ImageDetailResponse:
    """Discard the stored result and queue the image to be scored again.

    Returns **202** with the image back at ``pending``: the new prediction does
    not exist yet, and returning the old one would look like the request had
    silently done nothing.
    """
    _ = access
    await ReprocessImage(images, predictions, detections, queue).execute(image_id, project_id)
    await audit.record(
        AuditAction.IMAGE_REPROCESSED,
        entity_type="image",
        entity_id=image_id,
        actor_user_id=user.id,
        ip_address=client_ip,
        metadata={"project_id": str(project_id)},
    )
    detail = await GetImageDetail(images, predictions, detections, storage).execute(
        image_id, project_id
    )
    return present_image_detail(detail)


@router.get(
    "/projects/{project_id}/history",
    summary="Captures joined to their predictions",
    response_model=PageResponse[HistoryEntryResponse],
)
async def get_project_history(
    project_id: ProjectId,
    access: AccessContextDep,
    images: ImageRepoDep,
    predictions: PredictionRepoDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    device_id: Annotated[UUID | None, Query()] = None,
    image_status: Annotated[ImageStatus | None, Query(alias="status")] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> PageResponse[HistoryEntryResponse]:
    """The original ``/history``: chronological captures with their verdicts.

    Includes captures that were rejected or have not been scored — the rejection
    rate is a real property of the site and of the quality gate, and a history
    that hid it would overstate how much usable data exists.
    """
    _ = access
    page = await GetProjectHistory(images, predictions).execute(
        project_id,
        limit=limit,
        cursor=cursor,
        device_id=device_id,
        status=image_status,
        since=since,
        until=until,
    )
    return PageResponse[HistoryEntryResponse](
        items=[present_history_entry(entry) for entry in page.entries],
        next_cursor=page.next_cursor,
        has_more=page.next_cursor is not None,
    )


@router.post(
    "/predict",
    summary="Ad-hoc inference (nothing is stored)",
    response_model=AdHocPredictionResponse,
    responses={
        503: {"description": "No inference worker answered"},
        413: {"description": "Image larger than the configured limit"},
    },
)
@limiter.limit("10/minute")
async def predict_adhoc(
    request: Request,
    user: CurrentUser,
    gateway: InferenceGatewayDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="JPEG, PNG, or BMP")],
) -> AdHocPredictionResponse:
    """Run one uploaded image through the full pipeline and store nothing.

    The demo path for the defense: upload a photograph, see the stage, the
    confidence, the detections, and the timings — without it touching any
    project's progress history.

    Authenticated and rate-limited. It is the only endpoint that will run a
    model on arbitrary uploaded bytes, so leaving it open would be an invitation
    to use the worker as free compute.
    """
    _ = request, user
    payload = await file.read()
    result = await PredictAdHoc(gateway, max_bytes=settings.max_image_upload_bytes).execute(payload)
    return present_adhoc(result)
