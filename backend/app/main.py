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
from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.error_handlers import build_error_response, register_exception_handlers
from app.core.config import Settings, get_settings
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.rate_limit import get_limiter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from contextlib import AbstractAsyncContextManager

    from app.infrastructure.realtime import RealtimeSubscriber

logger = logging.getLogger(__name__)

DESCRIPTION = """
**GeoVision** - Smart Construction Monitoring Using AI and Geotagging.

An ESP32-CAM captures geotagged construction site photos on a schedule; the
server classifies the construction stage (ResNet18), corroborates with object
detection (YOLOv8), computes a temporally smoothed progress percentage, and
serves it to a public site and an authenticated owner dashboard.

Design documentation lives in the project's Obsidian vault (`GeoVision-Vault/`).
"""


async def _rate_limit_handler(_: Request, exc: Exception) -> JSONResponse:
    """Render an exceeded rate limit in the project's standard error envelope.

    slowapi's default response is a bare string, which would be the only
    endpoint in the API not returning ``{"error": {...}}``.
    """
    detail = getattr(exc, "detail", "rate limit exceeded")
    return build_error_response(
        HTTPStatus.TOO_MANY_REQUESTS,
        "RATE_LIMITED",
        "Too many requests. Please slow down and try again shortly.",
        {"limit": str(detail)},
    )


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
        subscriber = _start_realtime(settings)
        if subscriber is not None:
            await subscriber.start()
        try:
            yield
        finally:
            if subscriber is not None:
                await subscriber.stop()
            logger.info("shutting down %s", settings.app_name)

    return lifespan


def _start_realtime(settings: Settings) -> RealtimeSubscriber | None:
    """Build the Redis subscriber, or ``None`` when no broker is configured.

    Tied to the application lifespan so its life is exactly the app's: no
    orphaned task surviving a reload, and no socket receiving events after
    shutdown has begun. Without a broker the app still serves — realtime is an
    optimisation, and the dashboard polls.
    """
    if settings.task_queue_backend != "celery":
        return None
    from app.infrastructure.realtime import get_hub

    return RealtimeSubscriber(settings.redis_url, get_hub())


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

    # Rate limiting. slowapi stores the limiter on app.state and needs its own
    # exception handler; without the handler an exceeded limit surfaces as a
    # 500 instead of a 429.
    limiter = get_limiter()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

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
    from app.api.v1.routers import (
        auth,
        content,
        devices,
        health,
        ingest,
        members,
        models,
        predictions,
        progress,
        projects,
        public,
        public_users,
        reports,
        users,
        ws,
    )

    app.include_router(health.router)

    prefix = settings.api_v1_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(public_users.router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(members.router, prefix=prefix)
    app.include_router(content.router, prefix=prefix)
    app.include_router(public.router, prefix=prefix)
    app.include_router(devices.router, prefix=prefix)
    app.include_router(ingest.router, prefix=prefix)
    # Progress before predictions: both declare routes under /projects/{id}, and
    # registration order is match order. Keeping the narrower, literal paths
    # first means a future /projects/{id}/images/{id} pattern cannot shadow them.
    app.include_router(progress.router, prefix=prefix)
    app.include_router(predictions.router, prefix=prefix)
    app.include_router(models.router, prefix=prefix)
    app.include_router(reports.router, prefix=prefix)
    app.include_router(ws.router, prefix=prefix)

    # Mounted as the corresponding modules land:
    #   Module 14  ws


app = create_app()
