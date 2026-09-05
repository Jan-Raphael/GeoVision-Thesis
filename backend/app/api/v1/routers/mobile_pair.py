"""Serves the phone/webcam pairing page at ``GET /pair``.

Deliberately unauthenticated and outside the ``/api/v1`` JSON API prefix — this
is a human-facing HTML page, not a versioned API resource, the same reasoning
that keeps ``/health`` unprefixed. It exists because a phone's QR scanner opens
a *link*, not raw JSON: the ESP32 provisioning QR (``build_provisioning_qr``)
encodes JSON for a human to read and retype into a captive portal, and a phone
scanning it "helpfully" extracts the embedded server address and tries to open
that instead, landing on a bare API endpoint with nothing to render. This route
gives that link something real to open.

The page itself does all the pairing and signing client-side in vanilla JS
(see ``app/static/mobile_pair.html``) — this router only ever returns the
static file.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["mobile-pair"])

_PAGE_PATH = Path(__file__).resolve().parents[3] / "static" / "mobile_pair.html"


@router.get("/pair", include_in_schema=False, response_class=HTMLResponse)
async def mobile_pair_page() -> HTMLResponse:
    """Return the self-contained phone/webcam pairing + capture page.

    Reads the file on every request rather than caching its contents in
    memory: it is a few KB, disk I/O for it is not a real cost, and it means
    an edit to the page takes effect without restarting the process.
    """
    return HTMLResponse(_PAGE_PATH.read_text(encoding="utf-8"))
