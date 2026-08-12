"""Small typing helpers shared by the repository implementations."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sqlalchemy import CursorResult
    from sqlalchemy.engine import Result

__all__ = ["affected_rows", "to_decimal"]


def affected_rows(result: Result[Any]) -> int:
    """Return how many rows a DML statement touched.

    ``AsyncSession.execute`` is annotated as returning ``Result``, but an
    ``UPDATE``/``DELETE`` actually yields a ``CursorResult``, which is the only
    one carrying ``rowcount``. Narrowing it here keeps the cast in one place
    instead of scattering ``type: ignore`` through every repository.
    """
    return cast("CursorResult[Any]", result).rowcount or 0


def to_decimal(value: float | Decimal) -> Decimal:
    """Convert a domain float to the ``Decimal`` a numeric column expects.

    Routed through ``str`` deliberately: ``Decimal(0.1)`` captures the binary
    float's error (``0.1000000000000000055511151231257827``), while
    ``Decimal("0.1")`` is exact.
    """
    return value if isinstance(value, Decimal) else Decimal(str(value))
