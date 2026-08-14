"""Reading, re-running, and demonstrating predictions.

The write path — an ingested image becoming a stored prediction — belongs to the
worker (``app.worker.inference``). What lives here is everything a *person*
does with the result afterwards: open one image and see why the model said what
it said, scroll the project's history, ask for an image to be scored again, and
run the stateless demo that persists nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from app.application.ports.task_queue import QUEUE_INFERENCE, TASK_PROCESS_IMAGE
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationFailedError,
)
from app.domain.enums import ImageStatus

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from app.application.ports.inference_gateway import AdHocPrediction, InferenceGateway
    from app.application.ports.storage import ObjectStorage
    from app.application.ports.task_queue import TaskQueue
    from app.domain.entities import (
        Detection,
        DetectionSummary,
        Image,
        Prediction,
    )
    from app.domain.repositories import (
        DetectionRepository,
        ImageRepository,
        PredictionRepository,
    )

__all__ = [
    "GetImageDetail",
    "GetProjectHistory",
    "HistoryEntry",
    "HistoryPage",
    "ImageDetail",
    "PredictAdHoc",
    "ReprocessImage",
]

#: Signatures of the formats the pipeline can decode, checked against the bytes
#: rather than against the declared content type. A browser will happily label a
#: text file `image/jpeg`, and the worker would then spend a queue slot to
#: discover it cannot be decoded.
_MAGIC_NUMBERS: tuple[bytes, ...] = (
    b"\xff\xd8\xff",  # JPEG
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"BM",  # BMP
)


@dataclass(frozen=True, slots=True)
class ImageDetail:
    """One capture with everything known about it."""

    image: Image
    prediction: Prediction | None
    detections: tuple[Detection, ...]
    summary: DetectionSummary | None
    original_url: str | None
    thumb_url: str | None
    preprocessed_url: str | None


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """One row of the project history: a capture and its verdict."""

    image: Image
    prediction: Prediction | None


@dataclass(frozen=True, slots=True)
class HistoryPage:
    """A page of history, with the cursor for the next."""

    entries: tuple[HistoryEntry, ...]
    next_cursor: str | None


class GetImageDetail:
    """Assemble one image, its prediction, its detections, and signed URLs."""

    def __init__(
        self,
        images: ImageRepository,
        predictions: PredictionRepository,
        detections: DetectionRepository,
        storage: ObjectStorage,
    ) -> None:
        """Bind the repositories and storage this read needs."""
        self._images = images
        self._predictions = predictions
        self._detections = detections
        self._storage = storage

    async def execute(self, image_id: UUID, project_id: UUID) -> ImageDetail:
        """Return everything the image detail view and lightbox render.

        Args:
            image_id: The capture to load.
            project_id: The project the caller has already been authorised
                against.

        Returns:
            The assembled detail.

        Raises:
            NotFoundError: If no such image exists, **or** it belongs to another
                project. The two are deliberately indistinguishable: a caller
                authorised for project A must not be able to confirm that an
                image id exists in project B by the shape of the error.
        """
        image = await self._images.get(image_id)
        if image is None or image.project_id != project_id:
            msg = "Image not found."
            raise NotFoundError(msg)

        return ImageDetail(
            image=image,
            prediction=await self._predictions.get_for_image(image_id),
            detections=await self._detections.list_for_image(image_id),
            summary=await self._detections.get_summary(image_id),
            original_url=await self._signed(image.storage_key),
            thumb_url=await self._signed(image.thumb_key),
            preprocessed_url=await self._signed(image.preprocessed_key),
        )

    async def _signed(self, key: str | None) -> str | None:
        """Sign a key, tolerating a missing object.

        A thumbnail that was never generated must not break the whole detail
        view — the photograph and its prediction are still the point.
        """
        if not key:
            return None
        try:
            return await self._storage.signed_url(key)
        except Exception:
            return None


class GetProjectHistory:
    """The original ``/history``: captures joined to their predictions."""

    def __init__(self, images: ImageRepository, predictions: PredictionRepository) -> None:
        """Bind the image and prediction repositories."""
        self._images = images
        self._predictions = predictions

    async def execute(
        self,
        project_id: UUID,
        *,
        limit: int = 50,
        cursor: str | None = None,
        device_id: UUID | None = None,
        status: ImageStatus | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> HistoryPage:
        """Return one page of history, newest capture first.

        Images without a prediction are **included**, with ``prediction=None``.
        A pending, rejected, or failed capture is part of the history of the
        site: a timeline that quietly omitted every image the gate threw away
        would misrepresent how much was actually captured.
        """
        page = await self._images.list_for_project(
            project_id,
            limit=limit,
            cursor=cursor,
            device_id=device_id,
            status=status,
            since=since,
            until=until,
        )
        found = await self._predictions.list_for_images([image.id for image in page.items])
        return HistoryPage(
            entries=tuple(
                HistoryEntry(image=image, prediction=found.get(image.id)) for image in page.items
            ),
            next_cursor=page.next_cursor,
        )


class ReprocessImage:
    """Queue an already-ingested image to be scored again.

    Used after a retrain, or when a prediction is visibly wrong and somebody
    wants the current model's opinion instead.
    """

    def __init__(
        self,
        images: ImageRepository,
        predictions: PredictionRepository,
        detections: DetectionRepository,
        queue: TaskQueue,
    ) -> None:
        """Bind the repositories and the queue to hand the image back to."""
        self._images = images
        self._predictions = predictions
        self._detections = detections
        self._queue = queue

    async def execute(self, image_id: UUID, project_id: UUID) -> Image:
        """Clear the old result and re-enqueue.

        The previous prediction and detections are **deleted** first, for two
        reasons. The worker skips any image already marked ``inferred``, so the
        status has to be reset for the task to do anything at all; and two
        prediction rows for one photograph would both satisfy the aggregation
        query, letting a single image vote twice in its own window.

        Raises:
            NotFoundError: If the image does not exist or is not in this project.
            ConflictError: If it is still waiting to be processed the first time.
        """
        image = await self._images.get(image_id)
        if image is None or image.project_id != project_id:
            msg = "Image not found."
            raise NotFoundError(msg)
        if image.status is ImageStatus.PENDING:
            msg = "This image has not been processed yet; it is already queued."
            raise ConflictError(msg)

        await self._predictions.delete_for_image(image_id)
        await self._detections.delete_for_image(image_id)
        reset = await self._images.update(replace(image, status=ImageStatus.PENDING))
        await self._queue.enqueue(
            TASK_PROCESS_IMAGE, {"image_id": str(image_id)}, queue=QUEUE_INFERENCE
        )
        return reset


class PredictAdHoc:
    """The stateless ``POST /predict`` demo path.

    Runs the identical pipeline and stores nothing, so a prediction made during
    a demonstration cannot end up in a real project's progress history — which
    would be both a correctness problem and, in a thesis, an integrity one.
    """

    def __init__(self, gateway: InferenceGateway, *, max_bytes: int) -> None:
        """Bind the worker channel and the accepted upload size."""
        self._gateway = gateway
        self._max_bytes = max_bytes

    async def execute(self, image_bytes: bytes) -> AdHocPrediction:
        """Validate the upload, then have a worker score it.

        Raises:
            PayloadTooLargeError: If the upload exceeds the configured limit.
                Checked here rather than in the worker because the bytes travel
                base64-encoded through Redis — a refusal after that trip has
                already cost the broker the memory.
            ValidationFailedError: If the bytes are not a decodable image.
            ServiceUnavailableError: If no worker answered (raised by the
                gateway).
        """
        if len(image_bytes) > self._max_bytes:
            raise PayloadTooLargeError(
                "Image is larger than the configured limit.",
                details={"max_bytes": self._max_bytes, "received_bytes": len(image_bytes)},
            )
        _require_image(image_bytes)
        return await self._gateway.predict(image_bytes)


def _require_image(payload: bytes) -> None:
    """Reject anything that is not a supported image, by its magic number.

    Raises:
        ValidationFailedError: If the bytes carry no recognised signature.
    """
    if not any(payload.startswith(signature) for signature in _MAGIC_NUMBERS):
        msg = "Uploaded file is not a JPEG, PNG, or BMP image."
        raise ValidationFailedError(msg)
