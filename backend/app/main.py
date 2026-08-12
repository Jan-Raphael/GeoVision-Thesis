"""FastAPI application factory.

Built as a factory rather than a module-level singleton so that tests can
construct an isolated app with overridden settings and dependencies, instead of
importing whatever global state happened to exist at import time.

Run locally::

    uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import RequestIDMiddleware, configure_logging

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from contextlib import AbstractAsyncContextManager

logger = logging.getLogger(__name__)

DESCRIPTION = """
**GeoVision** - Smart Construction Monitoring Using AI and Geotagging.

An ESP32-CAM captures geotagged construction site photos on a schedule; the
server classifies the construction stage (ResNet18), corroborates with object
detection (YOLOv8), computes a temporally smoothed progress percentage, and
serves it to a public site and an authenticated owner dashboard.

Design documentation lives in the project's Obsidian vault (`GeoVision-Vault/`).
"""


def _build_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Create the lifespan handler bound to *settings*."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Run startup and shutdown work around the application's lifetime."""
        logger.info(
            "starting %s v%s environment=%s",
            settings.app_name,
            settings.version,
            settings.environment,
        )
        # Module 02+ will open the database engine here.
        # Module 05+ will ensure the object-storage bucket exists.
        # Module 09+ will warm the inference service in the worker (not here).
        # Module 14+ will start the Redis pub/sub subscriber task.
        yield
        logger.info("shutting down %s", settings.app_name)

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Optional settings override. Defaults to the cached
            process-wide settings; tests pass their own instance.

    Returns:
        A fully configured :class:`~fastapi.FastAPI` instance.
    """
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=settings.version,
        docs_url=settings.docs_url,
        redoc_url=None,
        openapi_url=settings.openapi_url,
        lifespan=_build_lifespan(settings),
    )

    # Middleware order matters: the request id must be set before anything else
    # logs, so RequestIDMiddleware is added last (Starlette applies the last
    # added middleware first, outermost).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIDMiddleware)

    # Bind the *injected* settings to the DI graph. Without this, routes calling
    # `Depends(get_settings)` would silently read the cached process-wide
    # settings instead, so `create_app(custom_settings)` would configure the app
    # while its endpoints ignored the override - the factory pattern would be
    # only half real, and tests would depend on whatever .env exists locally.
    app.dependency_overrides[get_settings] = lambda: settings

    register_exception_handlers(app)
    _register_routers(app, settings)

    return app


def _register_routers(app: FastAPI, settings: Settings) -> None:
    """Mount every router.

    Health endpoints are mounted at the root (unversioned) because probes must
    not move when the API version changes. Everything else lives under
    ``/api/v1`` - see ``GeoVision-Vault/04-API/API-Contract.md``.
    """
    from app.api.v1.routers import health

    app.include_router(health.router)

    # Mounted as the corresponding modules land:
    #   Module 03  auth, users, public_users
    #   Module 04  projects, members, assets, remarks, public, search, contact
    #   Module 05  pairing, ingest, devices
    #   Module 09  predictions, progress, models
    #   Module 10  reports
    #   Module 14  ws
    _ = settings.api_v1_prefix


app = create_app()
