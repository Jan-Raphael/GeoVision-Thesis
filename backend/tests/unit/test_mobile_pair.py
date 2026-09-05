"""The phone/webcam pairing page (GET /pair)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.unit


async def test_pair_page_serves_html(client: AsyncClient) -> None:
    """Unauthenticated, unprefixed -- a phone scanning a QR must never hit a login wall."""
    response = await client.get("/pair")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_pair_page_works_with_a_code_query_param(client: AsyncClient) -> None:
    """The QR encodes /pair?code=..., so the same page must still load with one present."""
    response = await client.get("/pair?code=K7M29XQF")

    assert response.status_code == 200


async def test_pair_page_is_not_under_the_api_v1_prefix(client: AsyncClient) -> None:
    """Same reasoning as /health: a human-facing page, not a versioned API resource."""
    response = await client.get("/api/v1/pair")

    assert response.status_code == 404
