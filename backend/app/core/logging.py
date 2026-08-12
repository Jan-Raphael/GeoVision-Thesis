"""Structured logging and request correlation.

Two formats, chosen by ``GV_LOG_FORMAT``:

``console``
    Human-readable, for local development.
``json``
    One JSON object per line, for production log aggregation.

Every log record carries a ``request_id``. It is generated (or taken from an
inbound ``X-Request-ID`` header) by :class:`RequestIDMiddleware`, stored in a
:class:`~contextvars.ContextVar`, and returned to the client in the response
headers. That single identifier is what lets you follow one ESP32 upload from
the ingest request, through the Celery task, to the WebSocket event it emits.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from pythonjsonlogger.json import JsonFormatter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

#: Correlation id for the in-flight request. Empty outside a request context.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

REQUEST_ID_HEADER = "X-Request-ID"


def get_request_id() -> str:
    """Return the current request's correlation id, or ``""`` if unset."""
    return request_id_ctx.get()


class RequestIDFilter(logging.Filter):
    """Attach the current ``request_id`` to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Always returns ``True``; this filter enriches rather than excludes."""
        record.request_id = request_id_ctx.get() or "-"
        return True


class ConsoleFormatter(logging.Formatter):
    """Compact, readable formatter for local development."""

    _FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"

    def __init__(self) -> None:
        """Configure the compact console format with short timestamps."""
        super().__init__(fmt=self._FORMAT, datefmt="%H:%M:%S")


def configure_logging(*, level: str = "INFO", log_format: str = "console") -> None:
    """Configure the root logger. Safe to call more than once.

    Args:
        level: Minimum level name, e.g. ``"INFO"``.
        log_format: ``"json"`` or ``"console"``.
    """
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(RequestIDFilter())

    if log_format == "json":
        handler.setFormatter(
            JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
                rename_fields={"asctime": "timestamp", "levelname": "level"},
                timestamp=True,
            )
        )
    else:
        handler.setFormatter(ConsoleFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn installs its own handlers; route them through ours so that
    # access logs also carry the request id.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # SQLAlchemy echo is controlled by GV_DB_ECHO, not by the root level.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign a correlation id to each request and echo it back.

    Honours an inbound ``X-Request-ID`` so a reverse proxy or the ESP32 client
    can supply its own, which makes cross-system tracing possible.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap *app* so every request receives a correlation id."""
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Set the context variable, call the app, and stamp the response."""
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            request_id_ctx.reset(token)


def get_logger(name: str, **context: Any) -> logging.LoggerAdapter[logging.Logger]:
    """Return a logger pre-bound with structured context.

    Args:
        name: Logger name, conventionally ``__name__``.
        **context: Extra key/value pairs attached to every record.

    Returns:
        A logger adapter that merges *context* into each call's ``extra``.
    """
    return logging.LoggerAdapter(logging.getLogger(name), extra=context)
