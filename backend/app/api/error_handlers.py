"""HTTP rendering for exceptions.

Split from :mod:`app.core.exceptions` because that module must stay
framework-free: the application layer raises those types, and importing FastAPI
there would make every use case depend on the web framework. The
``application-independence`` contract in ``backend/.importlinter`` enforces the
separation.

Every failure path — domain errors, validation errors, framework 404s, and
unhandled exceptions — is normalised into the single envelope described in
``GeoVision-Vault/04-API/API-Contract.md``, so clients parse exactly one error
shape.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import DomainError
from app.core.logging import get_request_id

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["build_error_response", "register_exception_handlers"]

logger = logging.getLogger(__name__)


def build_error_response(
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> JSONResponse:
    """Build a JSONResponse in the standard error shape."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = jsonable_encoder(details)
    request_id = get_request_id()
    if request_id:
        error["request_id"] = request_id
    return JSONResponse(status_code=status_code, content={"error": error})


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers so every error path returns the same envelope.

    Args:
        app: The FastAPI application to configure.
    """

    @app.exception_handler(DomainError)
    async def _handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
        # Expected failures: log at INFO, they are not defects.
        assert isinstance(exc, DomainError)  # noqa: S101 - narrowed by the decorator
        logger.info("domain_error code=%s status=%s", exc.code, exc.status_code)
        return build_error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)  # noqa: S101
        return build_error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "UNPROCESSABLE_ENTITY",
            "Request validation failed.",
            {"fields": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
        # Normalise framework-raised 404/405 into our envelope so clients only
        # ever parse one error shape.
        assert isinstance(exc, StarletteHTTPException)  # noqa: S101
        code = {
            HTTPStatus.NOT_FOUND: "NOT_FOUND",
            HTTPStatus.METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
            HTTPStatus.UNAUTHORIZED: "UNAUTHENTICATED",
            HTTPStatus.FORBIDDEN: "FORBIDDEN",
        }.get(HTTPStatus(exc.status_code), "HTTP_ERROR")
        return build_error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Unexpected: log the traceback, return nothing internal to the client.
        logger.exception("unhandled_exception", exc_info=exc)
        return build_error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "An unexpected error occurred. The incident has been logged.",
        )
