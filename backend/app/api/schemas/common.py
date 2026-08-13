"""Response envelopes shared across every router.

Defined once here so Modules 04-16 do not each invent their own pagination
shape — three different cursor field names across four endpoints is the kind of
inconsistency that surfaces as frontend bugs.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ErrorEnvelope", "MessageResponse", "PageResponse"]

ItemT = TypeVar("ItemT")


class PageResponse(BaseModel, Generic[ItemT]):
    """One page of results plus the cursor for the next.

    Cursor pagination rather than offset: the image and project feeds grow
    while a user scrolls them, and ``OFFSET`` silently skips or repeats rows as
    new entries arrive.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[ItemT]
    next_cursor: str | None = Field(
        default=None,
        description="Pass as ?cursor= to fetch the next page. Null when exhausted.",
    )
    has_more: bool = False


class MessageResponse(BaseModel):
    """A bare acknowledgement for endpoints with nothing else to return."""

    message: str
    success: bool = True


class ErrorDetail(BaseModel):
    """The body of an error response."""

    code: str = Field(description="Stable machine-readable identifier")
    message: str = Field(description="Human-readable explanation")
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    """The error shape every failing endpoint returns.

    Declared so it appears in the OpenAPI schema and the frontend can generate
    one error type instead of guessing per endpoint.
    """

    error: ErrorDetail
