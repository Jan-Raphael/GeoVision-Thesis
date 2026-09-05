"""QR generation for device provisioning and phone/webcam pairing."""

from __future__ import annotations

import base64

from app.infrastructure.qr import build_pair_page_qr, build_provisioning_qr, render_qr_png

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class TestRenderQrPng:
    def test_produces_a_real_png(self) -> None:
        png = render_qr_png("hello")
        assert png.startswith(PNG_MAGIC)


class TestBuildProvisioningQr:
    def test_encodes_valid_base64_png(self) -> None:
        encoded = build_provisioning_qr(
            {"v": 1, "code": "K7M29XQF"}, server_url="http://192.168.1.10:8000"
        )
        assert base64.b64decode(encoded).startswith(PNG_MAGIC)


class TestBuildPairPageQr:
    """Encodes a real URL, not JSON -- a phone's camera app opens a URL as a
    link, which is the entire point (see Progress-Log, 2026-09-05: the
    provisioning QR's raw JSON made a phone scanner "helpfully" open its
    embedded server address as a bare, unusable API endpoint)."""

    def test_produces_a_real_png(self) -> None:
        encoded = build_pair_page_qr("K7M29XQF", server_url="http://192.168.1.10:8000")
        assert base64.b64decode(encoded).startswith(PNG_MAGIC)

    def test_strips_trailing_slash_from_server_url(self) -> None:
        """A quick way to confirm the URL construction without a QR decoder:
        two server URLs differing only by a trailing slash must encode to the
        exact same image, since the resolved pairing URL is identical."""
        with_slash = build_pair_page_qr("K7M29XQF", server_url="http://192.168.1.10:8000/")
        without_slash = build_pair_page_qr("K7M29XQF", server_url="http://192.168.1.10:8000")
        assert with_slash == without_slash

    def test_different_codes_produce_different_images(self) -> None:
        first = build_pair_page_qr("K7M29XQF", server_url="http://192.168.1.10:8000")
        second = build_pair_page_qr("AAAA1111", server_url="http://192.168.1.10:8000")
        assert first != second
