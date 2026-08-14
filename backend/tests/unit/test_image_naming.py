"""Filenames and storage keys.

Worth pinning tightly. A filename here is read back months later by a person
reconciling a timeline against a site diary, and the storage key decides whether
a bucket stays browsable over a multi-year project. Both are cheap to get wrong
and expensive to change once thousands of objects carry the old shape.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.enums import CameraFace
from app.domain.services.image_naming import (
    build_image_filename,
    build_original_key,
    build_preprocessed_key,
    build_thumbnail_key,
)
from app.domain.value_objects import ProjectCode

pytestmark = pytest.mark.unit

CODE = ProjectCode("NG_00")
MOMENT = datetime(2026, 8, 14, 7, 0, 0, tzinfo=UTC)


class TestFilename:
    """``<CODE>_<YYYYMMDDTHHMMSSZ>_<NNN>.jpg`` (Naming-Conventions §3)."""

    def test_shape(self) -> None:
        assert build_image_filename(CODE, MOMENT, 1) == "NG_00_20260814T070000Z_001.jpg"

    def test_sequence_is_zero_padded_to_three(self) -> None:
        """So filenames sort lexicographically the same way they sort by time."""
        names = [build_image_filename(CODE, MOMENT, seq) for seq in (1, 12, 123)]
        assert [name[-7:-4] for name in names] == ["001", "012", "123"]

    def test_a_non_utc_capture_is_converted(self) -> None:
        """The suffix is ``Z``, so the value had better actually be UTC.

        This is the Module 02 bug that would have stamped every Manila capture
        eight hours late while still labelling it Z — silent, and only visible
        as a timeline that disagreed with the site diary.
        """
        manila = datetime(2026, 8, 14, 15, 0, tzinfo=timezone(timedelta(hours=8)))
        assert build_image_filename(CODE, manila, 1) == "NG_00_20260814T070000Z_001.jpg"

    def test_a_naive_capture_is_treated_as_utc(self) -> None:
        """The firmware stamps from GPS or the DS3231; both are UTC."""
        naive = datetime(2026, 8, 14, 7, 0)  # noqa: DTZ001 - the case under test
        assert build_image_filename(CODE, naive, 1) == "NG_00_20260814T070000Z_001.jpg"

    def test_seconds_are_included(self) -> None:
        """Two cameras firing in the same minute must not collide on name."""
        first = build_image_filename(CODE, MOMENT, 1)
        second = build_image_filename(CODE, MOMENT + timedelta(seconds=30), 2)
        assert first != second


class TestStorageKeys:
    """Date- and face-partitioned, so listings stay fast and browsable."""

    def test_original_key_layout(self) -> None:
        key = build_original_key("p-1", "NG_00_20260814T070000Z_001.jpg", MOMENT, CameraFace.FRONT)
        assert key == "projects/p-1/images/2026/08/14/front/NG_00_20260814T070000Z_001.jpg"

    def test_the_key_is_partitioned_by_the_capture_day_not_today(self) -> None:
        """A backlog uploaded a week late still files under the day it was taken."""
        old = datetime(2026, 1, 3, 6, 0, tzinfo=UTC)
        assert "/2026/01/03/" in build_original_key("p-1", "x.jpg", old, CameraFace.BACK)

    def test_a_manual_upload_has_no_face(self) -> None:
        """Module 07 lets an owner upload by hand; those have no camera."""
        assert "/manual/" in build_original_key("p-1", "x.jpg", MOMENT, None)

    def test_each_face_gets_its_own_prefix(self) -> None:
        keys = {build_original_key("p-1", "x.jpg", MOMENT, face) for face in CameraFace}
        assert len(keys) == len(CameraFace)

    def test_a_non_utc_capture_partitions_by_utc_day(self) -> None:
        """07:00 in Manila is the *previous* UTC day."""
        manila = datetime(2026, 8, 14, 7, 0, tzinfo=timezone(timedelta(hours=8)))
        assert "/2026/08/13/" in build_original_key("p-1", "x.jpg", manila, CameraFace.FRONT)

    def test_derived_keys_do_not_collide_with_originals(self) -> None:
        """Preprocessed frames and thumbnails must never overwrite an original."""
        original = build_original_key("p-1", "x.jpg", MOMENT, CameraFace.FRONT)
        derived = {
            build_preprocessed_key("p-1", "img-1"),
            build_thumbnail_key("p-1", "img-1"),
        }
        assert original not in derived
        assert len(derived) == 2

    def test_every_key_is_scoped_to_its_project(self) -> None:
        """One project's prefix can be listed, exported, or deleted on its own."""
        keys = [
            build_original_key("p-1", "x.jpg", MOMENT, CameraFace.FRONT),
            build_preprocessed_key("p-1", "img-1"),
            build_thumbnail_key("p-1", "img-1"),
        ]
        assert all(key.startswith("projects/p-1/") for key in keys)

    def test_keys_are_relative(self) -> None:
        """A leading slash creates an empty-named top-level folder on S3."""
        assert not build_original_key("p-1", "x.jpg", MOMENT, CameraFace.FRONT).startswith("/")
