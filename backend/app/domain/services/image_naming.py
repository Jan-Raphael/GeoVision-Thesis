"""Filenames and storage keys for captured images.

Pure functions. The rules come from
``GeoVision-Vault/01-Architecture/Naming-Conventions.md`` §3 and §5, and the
reason they live in the domain layer is that getting them wrong is expensive and
silent: a filename carries the project code and the capture instant, and both are
read back later by humans reconciling a timeline against a site diary.

.. important::
   **The device never chooses its own filename.** It may send a ``seq_hint``,
   which is advisory only. A device that could name its own files could
   overwrite another camera's captures, or claim a capture time it did not have.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from app.domain.entities.image import Image
from app.domain.enums import CameraFace
from app.domain.value_objects import ProjectCode

__all__ = [
    "build_image_filename",
    "build_original_key",
    "build_preprocessed_key",
    "build_thumbnail_key",
]

#: Three digits, so at most 999 captures per project per UTC day. A camera on
#: the recommended schedule takes two.
MAX_DAILY_SEQUENCE: Final = 999


def build_image_filename(code: ProjectCode, captured_at: datetime, seq: int) -> str:
    """Assemble the canonical capture filename.

    ``<CODE>_<YYYYMMDDTHHMMSSZ>_<NNN>.jpg`` — for example
    ``NG_00_20260814T070000Z_001.jpg``.

    Delegates to :meth:`~app.domain.entities.image.Image.build_filename` so
    there is exactly one implementation; this module exists to group naming
    with the storage-key builders that accompany it.
    """
    return Image.build_filename(code, captured_at, seq)


def build_original_key(
    project_id: str,
    filename: str,
    captured_at: datetime,
    face: CameraFace | None = None,
) -> str:
    """Storage key for an uploaded original.

    ``projects/{id}/images/{yyyy}/{mm}/{dd}/{face}/{filename}``

    Date-partitioned and face-partitioned so the bucket stays browsable by a
    human: "show me what the front-diagonal camera saw last Tuesday" is a
    prefix listing rather than a scan. It also keeps any single prefix small
    enough that object-store listings stay fast over a multi-year project.
    """
    moment = _as_utc(captured_at)
    face_segment = face.value if face is not None else "manual"
    return f"projects/{project_id}/images/{moment:%Y/%m/%d}/{face_segment}/{filename}"


def build_preprocessed_key(project_id: str, image_id: str) -> str:
    """Storage key for the preprocessed frame the classifier sees (Module 06)."""
    return f"projects/{project_id}/preprocessed/{image_id}.jpg"


def build_thumbnail_key(project_id: str, image_id: str) -> str:
    """Storage key for the dashboard thumbnail."""
    return f"projects/{project_id}/thumbs/{image_id}.webp"


def _as_utc(moment: datetime) -> datetime:
    """Normalise to UTC, treating a naive datetime as already UTC."""
    return moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
