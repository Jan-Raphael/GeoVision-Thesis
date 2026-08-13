"""File type validation by content, not by claim.

A browser-supplied ``Content-Type`` and a filename extension are both attacker
controlled: renaming ``payload.exe`` to ``blueprint.pdf`` changes neither the
bytes nor what happens when somebody later opens it. So uploads are identified
by their **magic bytes**, and anything that does not match the allowlist is
rejected regardless of what the request said it was.

Pure and dependency-free, so the rules can be tested with byte literals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.domain.enums import AssetKind

__all__ = [
    "ALLOWED_ASSET_TYPES",
    "MAX_ASSET_BYTES",
    "DetectedFileType",
    "detect_file_type",
    "validate_asset_upload",
]

#: 25 MB. A blueprint PDF or a 3-D render comfortably fits; a video does not.
MAX_ASSET_BYTES: Final = 25 * 1024 * 1024

#: Smallest plausible upload — below this it is a truncated or empty file.
MIN_ASSET_BYTES: Final = 64


@dataclass(frozen=True, slots=True)
class DetectedFileType:
    """What a file actually is, according to its leading bytes."""

    mime_type: str
    extension: str
    description: str


#: (offset, signature, detected type). Ordered most specific first: the WebP
#: check must precede any generic RIFF match.
_SIGNATURES: Final[tuple[tuple[int, bytes, DetectedFileType], ...]] = (
    (0, b"%PDF-", DetectedFileType("application/pdf", ".pdf", "PDF document")),
    (0, b"\xff\xd8\xff", DetectedFileType("image/jpeg", ".jpg", "JPEG image")),
    (
        0,
        b"\x89PNG\r\n\x1a\n",
        DetectedFileType("image/png", ".png", "PNG image"),
    ),
)

#: Formats whose signature is not a simple prefix.
_WEBP_RIFF: Final = b"RIFF"
_WEBP_TAG: Final = b"WEBP"

#: The only types an owner may attach to a project.
ALLOWED_ASSET_TYPES: Final[frozenset[str]] = frozenset(
    {"application/pdf", "image/jpeg", "image/png", "image/webp"}
)


class FileValidationError(ValueError):
    """An upload was rejected. The message is safe to show a user."""


def detect_file_type(payload: bytes) -> DetectedFileType | None:
    """Identify a file from its leading bytes.

    Args:
        payload: The file content, or at least its first 16 bytes.

    Returns:
        The detected type, or ``None`` if it matches nothing known.
    """
    for offset, signature, detected in _SIGNATURES:
        if payload[offset : offset + len(signature)] == signature:
            return detected

    # WebP is a RIFF container: "RIFF" .... "WEBP" at byte 8.
    riff_header_length = 12
    if (
        len(payload) >= riff_header_length
        and payload[:4] == _WEBP_RIFF
        and payload[8:12] == _WEBP_TAG
    ):
        return DetectedFileType("image/webp", ".webp", "WebP image")

    return None


def validate_asset_upload(
    payload: bytes,
    *,
    declared_filename: str,
    kind: AssetKind,
    max_bytes: int = MAX_ASSET_BYTES,
) -> DetectedFileType:
    """Check an uploaded reference asset and return what it really is.

    Args:
        payload: The complete file content.
        declared_filename: The client's filename. Used only for the error
            message — never to decide the type, and never as a storage key.
        kind: What the uploader says this is (blueprint, render, ...).
        max_bytes: Size ceiling.

    Returns:
        The detected file type.

    Raises:
        FileValidationError: If the file is empty, oversized, or not an allowed
            type.
    """
    size = len(payload)
    if size < MIN_ASSET_BYTES:
        msg = "That file is empty or truncated."
        raise FileValidationError(msg)
    if size > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        msg = f"File is too large. The limit is {limit_mb} MB."
        raise FileValidationError(msg)

    detected = detect_file_type(payload)
    if detected is None or detected.mime_type not in ALLOWED_ASSET_TYPES:
        msg = (
            f"{declared_filename!r} is not an accepted file type. Upload a PDF, JPEG, PNG, or WebP."
        )
        raise FileValidationError(msg)

    # An inspection photo should be a photo, not a document. Checked here rather
    # than at the router so the rule travels with the validation.
    if kind is AssetKind.INSPECTION_PHOTO and detected.mime_type == "application/pdf":
        msg = "An inspection photo must be an image, not a PDF."
        raise FileValidationError(msg)

    return detected


def safe_filename(original: str, *, fallback: str = "upload") -> str:
    """Reduce a client filename to something safe to echo back.

    Never used as a storage key — keys are generated — but the original name is
    shown in the UI and included in reports, so it must not carry path
    separators or control characters.
    """
    cleaned = "".join(char for char in original if char.isalnum() or char in " ._-").strip()
    cleaned = cleaned.replace("..", ".").lstrip(".")
    return cleaned[:120] or fallback
