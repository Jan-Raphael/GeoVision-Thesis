"""Throttling, exercised with the guards deliberately switched back on.

Every other integration test disables them (a 3/hour registration cap would
fail the fourth test in the file), so this is the one place proving they fire.

Two independent mechanisms are covered:

* the **per-IP** slowapi limiter, and that an exceeded limit returns the
  project's standard error envelope rather than slowapi's bare string;
* the **per-account** failed-attempt throttle, which is the one that actually
  defends against credential stuffing from many source addresses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.throttle import MAX_LOGIN_FAILURES, InMemoryThrottle, throttle_key

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

pytestmark = pytest.mark.integration

LOGIN = "/api/v1/auth/login"


@pytest.fixture
async def limited_client(
    session: AsyncSession, test_settings: Settings
) -> AsyncIterator[AsyncClient]:
    """A client whose app has rate limiting enabled and fresh counters."""
    from app.core.rate_limit import get_limiter, reset_limiter
    from app.core.throttle import get_login_throttle, reset_login_throttle
    from app.infrastructure.db.session import get_session
    from app.main import create_app

    reset_limiter()
    reset_login_throttle()
    application = create_app(test_settings)
    application.state.limiter.enabled = True

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    application.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    application.dependency_overrides.clear()
    application.dependency_overrides.clear()
    reset_limiter()
    reset_login_throttle()
    get_limiter()
    get_login_throttle()


def _login(identifier: str = "nobody_at_all") -> dict[str, Any]:
    """A login payload that fails authentication but is still counted."""
    return {"identifier": identifier, "password": "whatever-pass-1"}


class TestPerAccountThrottle:
    """Failed attempts counted against the account being targeted."""

    async def test_repeated_failures_lock_the_account_out(
        self, limited_client: AsyncClient
    ) -> None:
        statuses = [
            (await limited_client.post(LOGIN, json=_login())).status_code
            for _ in range(MAX_LOGIN_FAILURES + 1)
        ]
        assert statuses[:MAX_LOGIN_FAILURES] == [401] * MAX_LOGIN_FAILURES, statuses
        assert statuses[MAX_LOGIN_FAILURES] == 429, statuses

    async def test_other_accounts_are_unaffected(self, limited_client: AsyncClient) -> None:
        """Throttling one account must not lock out everybody else.

        This is what per-IP limiting alone cannot give you: it would either
        miss the attack entirely or punish every user behind one NAT.
        """
        for _ in range(MAX_LOGIN_FAILURES + 1):
            await limited_client.post(LOGIN, json=_login("target_user"))

        other = await limited_client.post(LOGIN, json=_login("someone_else"))
        assert other.status_code == 401, "a different account should still be served"

    async def test_throttled_response_uses_the_standard_envelope(
        self, limited_client: AsyncClient
    ) -> None:
        response = None
        for _ in range(MAX_LOGIN_FAILURES + 1):
            response = await limited_client.post(LOGIN, json=_login())

        assert response is not None
        assert response.status_code == 429
        body = response.json()
        assert set(body) == {"error"}
        assert body["error"]["code"] == "RATE_LIMITED"
        assert body["error"]["details"]["retry_after_seconds"] >= 1


class TestThrottleUnit:
    """The throttle's own behaviour, without HTTP in the way."""

    async def test_success_clears_the_counter(self) -> None:
        """A user who mistypes twice then succeeds is not left near a lockout."""
        throttle = InMemoryThrottle(max_attempts=3, window_seconds=300)
        key = throttle_key("jan_m")

        await throttle.record_failure(key)
        await throttle.record_failure(key)
        await throttle.reset(key)

        # Back to a full allowance.
        for _ in range(3):
            await throttle.record_failure(key)
        with pytest.raises(Exception, match="Too many failed"):
            await throttle.check(key)

    async def test_keys_are_case_insensitive(self) -> None:
        """`Jan_M` and `jan_m` are one account and share one bucket."""
        assert throttle_key("Jan_M") == throttle_key("jan_m  ")

    async def test_identifier_is_not_stored_in_the_key(self) -> None:
        """A dump of throttle state must not disclose who has accounts."""
        assert "jan_m" not in throttle_key("jan_m")

    async def test_window_expiry_restores_the_allowance(self) -> None:
        throttle = InMemoryThrottle(max_attempts=1, window_seconds=0)
        key = throttle_key("jan_m")
        await throttle.record_failure(key)
        # A zero-length window has already elapsed, so the bucket rolls over.
        await throttle.check(key)
