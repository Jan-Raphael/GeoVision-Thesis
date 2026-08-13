"""Upload validation by content rather than by claim.

The point of these tests is the renamed-executable case: a filename and a
browser-supplied Content-Type are both attacker-controlled, and neither changes
what the bytes actually are.
"""

from __future__ import annotations

import pytest

from app.domain.enums import AssetKind
from app.domain.services.file_validation import (
    MAX_ASSET_BYTES,
    FileValidationError,
    detect_file_type,
    safe_filename,
    validate_asset_upload,
)

pytestmark = pytest.mark.unit

PDF = b"%PDF-1.7\n" + b"x" * 200
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 200
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"x" * 200
# MZ header - a Windows executable.
EXE = b"MZ\x90\x00" + b"x" * 200


class TestDetection:
    """Magic-byte identification."""

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (PDF, "application/pdf"),
            (JPEG, "image/jpeg"),
            (PNG, "image/png"),
            (WEBP, "image/webp"),
        ],
    )
    def test_known_formats(self, payload: bytes, expected: str) -> None:
        detected = detect_file_type(payload)
        assert detected is not None
        assert detected.mime_type == expected

    @pytest.mark.parametrize("payload", [EXE, b"", b"just some text", b"\x00\x01\x02\x03"])
    def test_unknown_formats_return_none(self, payload: bytes) -> None:
        assert detect_file_type(payload) is None

    def test_riff_that_is_not_webp_is_not_accepted(self) -> None:
        """A WAV file is also RIFF; only the WEBP tag counts."""
        wav = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"x" * 200
        assert detect_file_type(wav) is None


class TestValidation:
    """The full upload check."""

    def test_valid_pdf_is_accepted(self) -> None:
        detected = validate_asset_upload(
            PDF, declared_filename="plan.pdf", kind=AssetKind.BLUEPRINT
        )
        assert detected.mime_type == "application/pdf"
        assert detected.extension == ".pdf"

    def test_executable_renamed_as_pdf_is_rejected(self) -> None:
        """The headline case. The name says PDF; the bytes say otherwise."""
        with pytest.raises(FileValidationError, match="not an accepted file type"):
            validate_asset_upload(EXE, declared_filename="blueprint.pdf", kind=AssetKind.BLUEPRINT)

    def test_extension_alone_never_decides(self) -> None:
        """A real PDF with a misleading name is still a PDF."""
        detected = validate_asset_upload(
            PDF, declared_filename="notes.txt", kind=AssetKind.DOCUMENT
        )
        assert detected.mime_type == "application/pdf"

    def test_empty_file_is_rejected(self) -> None:
        with pytest.raises(FileValidationError, match="empty or truncated"):
            validate_asset_upload(b"", declared_filename="x.pdf", kind=AssetKind.BLUEPRINT)

    def test_oversized_file_is_rejected(self) -> None:
        oversized = PDF + b"x" * MAX_ASSET_BYTES
        with pytest.raises(FileValidationError, match="too large"):
            validate_asset_upload(oversized, declared_filename="huge.pdf", kind=AssetKind.BLUEPRINT)

    def test_inspection_photo_must_be_an_image(self) -> None:
        """An inspection record should show the site, not a document."""
        with pytest.raises(FileValidationError, match="must be an image"):
            validate_asset_upload(
                PDF, declared_filename="report.pdf", kind=AssetKind.INSPECTION_PHOTO
            )

    def test_inspection_photo_accepts_a_jpeg(self) -> None:
        detected = validate_asset_upload(
            JPEG, declared_filename="site.jpg", kind=AssetKind.INSPECTION_PHOTO
        )
        assert detected.mime_type == "image/jpeg"


class TestSafeFilename:
    """The displayed name is sanitised; it is never a storage key."""

    @pytest.mark.parametrize(
        ("raw", "forbidden"),
        [
            ("../../etc/passwd", "/"),
            (r"..\..\windows\system32", "\\"),
            ("plan\x00.pdf", "\x00"),
        ],
    )
    def test_path_separators_and_control_bytes_are_stripped(self, raw: str, forbidden: str) -> None:
        assert forbidden not in safe_filename(raw)

    def test_leading_dots_are_removed(self) -> None:
        assert not safe_filename("...hidden").startswith(".")

    def test_ordinary_names_survive(self) -> None:
        assert safe_filename("Ground Floor Plan v2.pdf") == "Ground Floor Plan v2.pdf"

    def test_empty_result_falls_back(self) -> None:
        assert safe_filename("///") == "upload"

    def test_length_is_capped(self) -> None:
        assert len(safe_filename("a" * 500)) <= 120
