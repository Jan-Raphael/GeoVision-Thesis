"""Domain exception hierarchy.

Deliberately **framework-free**. These types are raised by the domain and
application layers, so importing FastAPI here would drag the web framework into
every use case — a violation the ``application-independence`` contract in
``backend/.importlinter`` catches. HTTP rendering lives in
``app.api.error_handlers``.

Status codes come from :class:`http.HTTPStatus` (standard library) rather than
``fastapi.status`` for the same reason. They are plain integers; the API layer
decides what to do with them.

Every error the API returns has the shape defined in
``GeoVision-Vault/04-API/API-Contract.md``::

    {"error": {"code": "PROJECT_CODE_TAKEN", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from app.core.logging import get_request_id

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ConflictError",
    "DomainError",
    "ForbiddenError",
    "NotFoundError",
    "PayloadTooLargeError",
    "RateLimitedError",
    "ServiceUnavailableError",
    "UnauthenticatedError",
    "ValidationFailedError",
]


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
    status_code: int = HTTPStatus.BAD_REQUEST

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
    status_code = HTTPStatus.BAD_REQUEST


class UnauthenticatedError(DomainError):
    """No valid credentials were supplied."""

    code = "UNAUTHENTICATED"
    status_code = HTTPStatus.UNAUTHORIZED


class ForbiddenError(DomainError):
    """Authenticated, but not permitted to perform this action.

    Use only when the caller is allowed to know the resource exists. For
    visibility-restricted resources raise :class:`NotFoundError` instead — a
    403 confirms existence, which is itself a disclosure.
    """

    code = "FORBIDDEN"
    status_code = HTTPStatus.FORBIDDEN


class NotFoundError(DomainError):
    """The resource does not exist, or the caller may not know that it does."""

    code = "NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND


class ConflictError(DomainError):
    """The request conflicts with current state (duplicate code, used token)."""

    code = "CONFLICT"
    status_code = HTTPStatus.CONFLICT


class PayloadTooLargeError(DomainError):
    """Upload exceeded the configured size limit."""

    code = "PAYLOAD_TOO_LARGE"
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class RateLimitedError(DomainError):
    """Too many requests from this caller."""

    code = "RATE_LIMITED"
    status_code = HTTPStatus.TOO_MANY_REQUESTS


class ServiceUnavailableError(DomainError):
    """A dependency (database, storage, queue) is unreachable."""

    code = "SERVICE_UNAVAILABLE"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
