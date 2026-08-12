"""Domain exception hierarchy and the HTTP error envelope.

Every error the API returns has the shape defined in
``GeoVision-Vault/04-API/API-Contract.md``::

    {"error": {"code": "PROJECT_CODE_TAKEN", "message": "...", "details": {...}}}

Design notes
------------
* :class:`DomainError` and its subclasses live here (in ``core``) rather than in
  ``domain/`` so that any layer may raise them, but they carry **no FastAPI
  import** - the domain layer must stay framework-free.
* ``status_code`` is an attribute of the exception, so use cases express intent
  ("this is a conflict") without importing HTTP machinery.
* Private resources raise :class:`NotFoundError`, never :class:`ForbiddenError`,
  so the API cannot leak the existence of a private project or profile.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_request_id

if TYPE_CHECKING:
    from collections.abc import Mapping


class DomainError(Exception):
    """Base class for every expected, business-meaningful failure.

    Attributes:
        code: Stable machine-readable identifier, e.g. ``PROJECT_CODE_TAKEN``.
            Clients switch on this; never change one without a version bump.
        message: Human-readable explanation, safe to show a user.
        status_code: HTTP status the API layer should return.
        details: Optional structured payload (field errors, suggestions...).
    """

    code: str = "DOMAIN_ERROR"
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Create a domain error.

        Args:
            message: Human-readable explanation, safe to show a user.
            code: Overrides the class-level ``code`` for one-off cases.
            status_code: Overrides the class-level HTTP status.
            details: Structured payload, e.g. field errors or suggestions.
        """
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details: dict[str, Any] = dict(details or {})

    def to_payload(self) -> dict[str, Any]:
        """Render the exception as the API error envelope."""
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        request_id = get_request_id()
        if request_id:
            error["request_id"] = request_id
        return {"error": error}


class ValidationFailedError(DomainError):
    """Input failed a business rule (as opposed to a schema rule)."""

    code = "VALIDATION_FAILED"
    status_code = status.HTTP_400_BAD_REQUEST


class UnauthenticatedError(DomainError):
    """No valid credentials were supplied."""

    code = "UNAUTHENTICATED"
    status_code = status.HTTP_401_UNAUTHORIZED


class ForbiddenError(DomainError):
    """Authenticated, but not permitted to perform this action.

    Use only when the caller is allowed to know the resource exists. For
    visibility-restricted resources raise :class:`NotFoundError` instead.
    """

    code = "FORBIDDEN"
    status_code = status.HTTP_403_FORBIDDEN


class NotFoundError(DomainError):
    """The resource does not exist, or the caller may not know that it does."""

    code = "NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND


class ConflictError(DomainError):
    """The request conflicts with current state (duplicate code, used token)."""

    code = "CONFLICT"
    status_code = status.HTTP_409_CONFLICT


class PayloadTooLargeError(DomainError):
    """Upload exceeded the configured size limit."""

    code = "PAYLOAD_TOO_LARGE"
    status_code = 413


class RateLimitedError(DomainError):
    """Too many requests from this caller."""

    code = "RATE_LIMITED"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS


class ServiceUnavailableError(DomainError):
    """A dependency (database, storage, queue) is unreachable."""

    code = "SERVICE_UNAVAILABLE"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


def _envelope(
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
    import logging

    logger = logging.getLogger(__name__)

    @app.exception_handler(DomainError)
    async def _handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        # Expected failures: log at INFO, they are not defects.
        logger.info("domain_error code=%s status=%s", exc.code, exc.status_code)
        return _envelope(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "UNPROCESSABLE_ENTITY",
            "Request validation failed.",
            {"fields": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Normalise framework-raised 404/405 into our envelope so clients only
        # ever parse one error shape.
        code = {
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
            status.HTTP_401_UNAUTHORIZED: "UNAUTHENTICATED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
        }.get(exc.status_code, "HTTP_ERROR")
        return _envelope(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Unexpected: log the traceback, return nothing internal to the client.
        logger.exception("unhandled_exception", exc_info=exc)
        return _envelope(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "An unexpected error occurred. The incident has been logged.",
        )
