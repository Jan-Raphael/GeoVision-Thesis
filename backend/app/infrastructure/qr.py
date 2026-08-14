"""QR code generation for device provisioning.

The pairing modal shows the code as both large text and a QR. The QR exists so a
technician on a roof can point a phone at the screen instead of transcribing
eight characters into an ESP32 captive portal with cold hands — the single most
error-prone step in the whole pairing flow.
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any

__all__ = ["build_provisioning_qr", "render_qr_png"]

#: Error-correction level M tolerates ~15 % damage. Chosen over the maximum (H)
#: because the payload is small, and a denser code is harder to scan off a
#: laptop screen at an angle in daylight - which is the actual use case.
_ERROR_CORRECTION = "M"


def render_qr_png(payload: str, *, box_size: int = 8, border: int = 2) -> bytes:
    """Render *payload* as a PNG.

    Args:
        payload: The text to encode.
        box_size: Pixels per QR module.
        border: Quiet-zone width in modules. Two is below the spec's four, which
            is fine on screen where the surrounding UI is already white.

    Returns:
        PNG bytes.
    """
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    code = qrcode.QRCode(
        version=None,  # smallest version that fits
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    code.add_data(payload)
    code.make(fit=True)

    buffer = io.BytesIO()
    code.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def build_provisioning_qr(payload: dict[str, Any], *, server_url: str) -> str:
    """Build the base64 PNG the pairing modal displays.

    The encoded JSON carries the server URL as well as the code, so the firmware
    learns where to send its uploads from the same scan. Compact separators are
    used because every byte saved lowers the QR version, and a lower version is
    a larger, more scannable module size at the same pixel width.

    Args:
        payload: The provisioning fields (code, project code, face, device name).
        server_url: Base URL the device should upload to.

    Returns:
        A ``data:``-ready base64 string, without the URI prefix.
    """
    document = {**payload, "server": server_url.rstrip("/")}
    encoded = json.dumps(document, separators=(",", ":"))
    return base64.b64encode(render_qr_png(encoded)).decode()
