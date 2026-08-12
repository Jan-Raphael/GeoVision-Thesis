"""Shared pytest fixtures.

Tests build the app through :func:`app.main.create_app` with explicit settings
rather than importing the module-level singleton. That keeps each test isolated
and means no test depends on whatever ``.env`` happens to exist on the machine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Environment, Settings
from app.main import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI


@pytest.fixture
def settings() -> Settings:
    """Deterministic settings for tests.

    Values are explicit so a developer's local ``.env`` can never change a test
    outcome. Credentials here are obviously fake and unused.
    """
    return Settings(
        environment=Environment.CI,
        debug=False,
        log_format="console",
        jwt_secret_key="test-only-secret-key-not-used-outside-tests",
        postgres_password="test-password",
        s3_secret_key="test-s3-secret",
        cors_origins=["http://localhost:5173"],
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """A freshly built application instance."""
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client wired directly to the ASGI app (no network, no port)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
