"""Tests for the application factory's isolation guarantees.

The factory only earns its keep if the settings it is handed are the settings
its endpoints actually observe. A regression here is silent and nasty: the app
appears configured, while every route reads the process-wide cached settings
instead - so tests would start depending on whatever ``.env`` exists on the
developer's machine.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Environment, Settings, get_settings
from app.main import create_app

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    """Hermetic settings: `_env_file=None` keeps a local `.env` out of the test."""
    values: dict[str, object] = {
        "environment": Environment.CI,
        "debug": False,
        "jwt_secret_key": "x" * 64,
        "postgres_password": "y" * 32,
        "s3_secret_key": "z" * 32,
        # Encrypts device secrets at rest (Module 05, ADR-020).
        "device_secret_key": "w" * 32,
        # Deployed environments must name a real storage backend.
        "storage_backend": "s3",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


async def test_injected_settings_reach_the_endpoints() -> None:
    """Endpoints observe the settings passed to ``create_app``."""
    app = create_app(_settings(app_name="GeoVision-Test"))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        body = (await client.get("/health")).json()

    assert body["app"] == "GeoVision-Test"
    assert body["environment"] == "ci"


async def test_two_apps_do_not_share_settings() -> None:
    """Each built app is independent, so tests cannot leak into one another."""
    first = create_app(_settings(app_name="First"))
    second = create_app(_settings(app_name="Second"))

    async with AsyncClient(transport=ASGITransport(app=first), base_url="http://a") as client_a:
        first_body = (await client_a.get("/health")).json()
    async with AsyncClient(transport=ASGITransport(app=second), base_url="http://b") as client_b:
        second_body = (await client_b.get("/health")).json()

    assert first_body["app"] == "First"
    assert second_body["app"] == "Second"


def test_get_settings_is_overridden_in_the_dependency_graph() -> None:
    """The override is registered explicitly rather than relied upon by luck."""
    settings = _settings()
    app = create_app(settings)

    assert get_settings in app.dependency_overrides
    assert app.dependency_overrides[get_settings]() is settings


def test_docs_are_exposed_outside_production() -> None:
    app = create_app(_settings(environment=Environment.LOCAL))
    assert app.docs_url == "/docs"


def test_docs_are_hidden_in_production() -> None:
    """Schema and Swagger must not be public on a deployed instance."""
    app = create_app(_settings(environment=Environment.PRODUCTION))
    assert app.docs_url is None
    assert app.openapi_url is None


async def test_unknown_route_uses_the_standard_error_envelope() -> None:
    """Framework 404s are normalised so clients parse exactly one error shape."""
    app = create_app(_settings())
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/does-not-exist")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert "message" in error
    # The correlation id is echoed into the body as well as the headers, so a
    # user reporting an error gives you something greppable.
    assert error["request_id"] == response.headers["X-Request-ID"]
