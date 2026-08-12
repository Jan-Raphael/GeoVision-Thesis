"""SQLAlchemy implementations for images, predictions, and progress snapshots."""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.domain.entities import Image, Prediction, ProgressSnapshot
from app.domain.enums import ImageStatus
from app.domain.repositories.base import Page
from app.infrastructure.db import models
from app.infrastructure.repositories._result import affected_rows
from app.infrastructure.repositories.mappers import to_image, to_prediction, to_snapshot

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SqlAlchemyImageRepository",
    "SqlAlchemyPredictionRepository",
    "SqlAlchemySnapshotRepository",
]


def _encode_cursor(moment: datetime, image_id: UUID) -> str:
    """Encode a keyset cursor for the image feed."""
    return base64.urlsafe_b64encode(f"{moment.isoformat()}|{image_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID] | None:
    """Decode a keyset cursor, tolerating malformed input."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        moment_str, _, id_str = raw.partition("|")
        return datetime.fromisoformat(moment_str), UUID(id_str)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


class SqlAlchemyImageRepository:
    """Captured frames, backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def get(self, image_id: UUID) -> Image | None:
        """Return an image by id."""
        row = await self._session.get(models.ImageModel, image_id)
        return to_image(row) if row else None

    async def get_by_hash(self, project_id: UUID, sha256: str) -> Image | None:
        """Look up by content hash — the ingest idempotency check.

        A device that retries after a lost ACK re-sends identical bytes; this
        lookup is what turns that into a 200 instead of a duplicate row.
        """
        stmt = select(models.ImageModel).where(
            models.ImageModel.project_id == project_id,
            models.ImageModel.sha256 == sha256,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_image(row) if row else None

    async def list_for_project(
        self,
        project_id: UUID,
        *,
        limit: int = 50,
        cursor: str | None = None,
        device_id: UUID | None = None,
        status: ImageStatus | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Page[Image]:
        """Paginated image feed, newest capture first."""
        stmt = select(models.ImageModel).where(models.ImageModel.project_id == project_id)
        if device_id:
            stmt = stmt.where(models.ImageModel.device_id == device_id)
        if status:
            stmt = stmt.where(models.ImageModel.status == status)
        if since:
            stmt = stmt.where(models.ImageModel.captured_at >= since)
        if until:
            stmt = stmt.where(models.ImageModel.captured_at < until)

        if cursor and (decoded := _decode_cursor(cursor)):
            cursor_moment, cursor_id = decoded
            stmt = stmt.where(
                or_(
                    models.ImageModel.captured_at < cursor_moment,
                    (models.ImageModel.captured_at == cursor_moment)
                    & (models.ImageModel.id < cursor_id),
                )
            )

        stmt = stmt.order_by(
            models.ImageModel.captured_at.desc(), models.ImageModel.id.desc()
        ).limit(limit + 1)
        rows = list((await self._session.execute(stmt)).scalars().all())

        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = _encode_cursor(rows[-1].captured_at, rows[-1].id)
        return Page(items=tuple(to_image(row) for row in rows), next_cursor=next_cursor)

    async def list_in_window(
        self, project_id: UUID, start: datetime, end: datetime
    ) -> tuple[Image, ...]:
        """Images captured in ``[start, end)`` — the aggregation input."""
        stmt = (
            select(models.ImageModel)
            .where(
                models.ImageModel.project_id == project_id,
                models.ImageModel.captured_at >= start,
                models.ImageModel.captured_at < end,
            )
            .order_by(models.ImageModel.captured_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_image(row) for row in rows)

    async def latest_for_project(self, project_id: UUID) -> Image | None:
        """The most recent capture, shown on the public feed card."""
        stmt = (
            select(models.ImageModel)
            .where(models.ImageModel.project_id == project_id)
            .order_by(models.ImageModel.captured_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalars().first()
        return to_image(row) if row else None

    async def next_sequence_number(self, project_id: UUID, day: date) -> int:
        """Allocate the next daily sequence number for a filename.

        Race-free by design: a transaction-scoped PostgreSQL **advisory lock**
        keyed on ``(project, day)`` serialises concurrent allocations, so two
        cameras uploading simultaneously cannot both receive ``001``. The lock
        is released automatically when the transaction ends.
        """
        lock_key = hash((str(project_id), day.isoformat())) % (2**31)
        await self._session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = datetime.combine(day, time.max, tzinfo=UTC)
        stmt = select(func.coalesce(func.max(models.ImageModel.seq_number), 0)).where(
            models.ImageModel.project_id == project_id,
            models.ImageModel.captured_at >= start,
            models.ImageModel.captured_at <= end,
        )
        current = int((await self._session.execute(stmt)).scalar_one() or 0)
        return current + 1

    async def add(self, image: Image) -> Image:
        """Record an ingested image."""
        row = models.ImageModel(
            id=image.id,
            project_id=image.project_id,
            device_id=image.device_id,
            filename=image.filename,
            storage_key=image.storage_key,
            preprocessed_key=image.preprocessed_key,
            thumb_key=image.thumb_key,
            source=image.source,
            status=image.status,
            captured_at=image.captured_at,
            seq_number=image.seq_number,
            latitude=image.location.latitude if image.location else None,
            longitude=image.location.longitude if image.location else None,
            gps_accuracy_m=image.gps_accuracy_m,
            altitude_m=image.altitude_m,
            satellites=image.satellites,
            width=image.width,
            height=image.height,
            size_bytes=image.size_bytes,
            sha256=image.sha256,
            exif=image.exif,
            quality_flags=image.quality_flags,
            rejected_reason=image.rejected_reason,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_image(row)

    async def update(self, image: Image) -> Image:
        """Persist status or derived-key changes."""
        row = await self._session.get(models.ImageModel, image.id)
        if row is None:
            msg = f"image {image.id} not found"
            raise LookupError(msg)
        row.status = image.status
        row.preprocessed_key = image.preprocessed_key
        row.thumb_key = image.thumb_key
        row.width = image.width
        row.height = image.height
        row.quality_flags = image.quality_flags
        row.rejected_reason = image.rejected_reason
        await self._session.flush()
        await self._session.refresh(row)
        return to_image(row)

    async def delete(self, image_id: UUID) -> bool:
        """Delete an image and its prediction/detections (cascade)."""
        row = await self._session.get(models.ImageModel, image_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


class SqlAlchemyPredictionRepository:
    """Classifier outputs, backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def get_for_image(self, image_id: UUID) -> Prediction | None:
        """Return the prediction for an image."""
        stmt = select(models.PredictionModel).where(models.PredictionModel.image_id == image_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_prediction(row) if row else None

    async def add(self, prediction: Prediction) -> Prediction:
        """Store a prediction."""
        row = models.PredictionModel(
            id=prediction.id,
            image_id=prediction.image_id,
            model_id=prediction.model_id,
            fine_class_index=prediction.fine_class_index,
            fine_class=prediction.fine_class,
            confidence=prediction.confidence.value,
            macro_stage=prediction.macro_stage,
            raw_progress_pct=prediction.raw_progress_pct.value,
            is_eligible=prediction.is_eligible,
            low_confidence=prediction.low_confidence,
            class_probabilities=prediction.class_probabilities,
            inference_ms=prediction.inference_ms,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_prediction(row)

    async def list_eligible_in_window(
        self, project_id: UUID, start: datetime, end: datetime
    ) -> tuple[Prediction, ...]:
        """Confidence-passing predictions in a window, for aggregation.

        Joins through ``images`` because the window is defined by *capture*
        time (device clock), not by when inference happened.
        """
        stmt = (
            select(models.PredictionModel)
            .join(models.ImageModel, models.PredictionModel.image_id == models.ImageModel.id)
            .where(
                models.ImageModel.project_id == project_id,
                models.ImageModel.captured_at >= start,
                models.ImageModel.captured_at < end,
                models.PredictionModel.is_eligible.is_(True),
            )
            .order_by(models.ImageModel.captured_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_prediction(row) for row in rows)


class SqlAlchemySnapshotRepository:
    """Progress snapshots — the timeline graph's source of truth."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def get_for_window(
        self, project_id: UUID, window_start: datetime
    ) -> ProgressSnapshot | None:
        """Return one window's snapshot."""
        stmt = select(models.ProgressSnapshotModel).where(
            models.ProgressSnapshotModel.project_id == project_id,
            models.ProgressSnapshotModel.window_start == window_start,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_snapshot(row) if row else None

    async def latest(self, project_id: UUID) -> ProgressSnapshot | None:
        """The most recent snapshot, i.e. current progress."""
        stmt = (
            select(models.ProgressSnapshotModel)
            .where(models.ProgressSnapshotModel.project_id == project_id)
            .order_by(models.ProgressSnapshotModel.window_start.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalars().first()
        return to_snapshot(row) if row else None

    async def list_series(
        self,
        project_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[ProgressSnapshot, ...]:
        """Ordered series for the timeline chart."""
        stmt = select(models.ProgressSnapshotModel).where(
            models.ProgressSnapshotModel.project_id == project_id
        )
        if since:
            stmt = stmt.where(models.ProgressSnapshotModel.window_start >= since)
        if until:
            stmt = stmt.where(models.ProgressSnapshotModel.window_start <= until)
        stmt = stmt.order_by(models.ProgressSnapshotModel.window_start)
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_snapshot(row) for row in rows)

    async def upsert(self, snapshot: ProgressSnapshot) -> ProgressSnapshot:
        """Insert or replace a window's snapshot.

        ``ON CONFLICT DO UPDATE`` on ``(project_id, window_start)``, because
        recomputation must be idempotent: re-running aggregation for a window
        replaces its row rather than accumulating duplicates.
        """
        values = {
            "project_id": snapshot.project_id,
            "window_start": snapshot.window_start,
            "window_end": snapshot.window_end,
            "raw_pct": snapshot.raw_pct.value,
            "ema_pct": snapshot.ema_pct.value,
            "displayed_pct": snapshot.displayed_pct.value,
            "macro_stage": snapshot.macro_stage,
            "foundation_pct": snapshot.foundation_pct,
            "framing_pct": snapshot.framing_pct,
            "roofing_pct": snapshot.roofing_pct,
            "finishing_pct": snapshot.finishing_pct,
            "approval_pct": snapshot.approval_pct,
            "eligible_image_count": snapshot.eligible_image_count,
            "contributing_image_ids": list(snapshot.contributing_image_ids),
            "device_weights": snapshot.device_weights,
            "algorithm_version": snapshot.algorithm_version,
        }
        stmt = (
            pg_insert(models.ProgressSnapshotModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["project_id", "window_start"],
                set_={k: v for k, v in values.items() if k not in {"project_id", "window_start"}},
            )
            .returning(models.ProgressSnapshotModel)
        )
        row = (await self._session.execute(stmt)).scalar_one()
        await self._session.flush()
        return to_snapshot(row)

    async def delete_for_project(self, project_id: UUID) -> int:
        """Remove every snapshot, for a full timeline recompute."""
        from sqlalchemy import delete as sa_delete

        stmt = sa_delete(models.ProgressSnapshotModel).where(
            models.ProgressSnapshotModel.project_id == project_id
        )
        result = await self._session.execute(stmt)
        return affected_rows(result)
