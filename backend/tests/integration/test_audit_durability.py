"""Audit rows for *refused* requests must survive the refusal.

Module 05 promises that a device authentication failure is "logged and audited
server-side" — the log line is what an operator reads, and the audit row is what
makes a brute-force or replay attempt queryable afterwards.

It was not true. The audit row is written by a dependency, the dependency then
raises, and the session rolls the whole request back — including the row that
recorded why. The failure is silent in the worst way: the endpoint behaves
exactly as designed (an identical 401 every time), the log line appears, and only
the durable evidence is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

INGEST = "/api/v1/ingest/images"


async def _auth_failures(session: AsyncSession) -> int:
    """How many device-auth failures are recorded."""
    return int(
        (
            await session.execute(
                text("SELECT count(*) FROM audit_logs WHERE action = 'device.auth_failed'")
            )
        ).scalar_one()
    )


class TestDeviceAuthAuditing:
    """A refused device upload leaves a trail."""

    async def test_an_unsigned_upload_is_refused_with_a_generic_401(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            INGEST, files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")}
        )
        assert response.status_code == 401
        # Deliberately uninformative: telling the caller which half of their
        # forgery to fix is the one thing this endpoint must never do.
        assert "signature" not in response.text.lower()

    async def test_the_refusal_is_recorded_durably(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        """The row must outlive the rollback that the 401 triggers."""
        before = await _auth_failures(session)

        await client.post(INGEST, files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")})

        assert await _auth_failures(session) == before + 1

    async def test_repeated_attempts_each_leave_a_row(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        """Counting attempts is the whole point of auditing them."""
        before = await _auth_failures(session)

        for _ in range(3):
            await client.post(
                INGEST,
                headers={"X-Device-Id": "not-a-uuid"},
                files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")},
            )

        assert await _auth_failures(session) == before + 3
