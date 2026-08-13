"""An injectable source of the current time.

Calling :func:`datetime.now` directly makes code untestable: token expiry,
schedule derivation, the aggregation windows in Module 09, and the delay rules
in Module 10 all depend on "now", and none of them can be tested deterministically
if "now" is a hidden global.

Everything in GeoVision that needs the current moment takes a :class:`Clock`.
Production passes :data:`SYSTEM_CLOCK`; tests pass :class:`FrozenClock`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

__all__ = ["SYSTEM_CLOCK", "Clock", "FrozenClock", "SystemClock", "utcnow"]


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Never returns a naive datetime. Every timestamp in this system is
    ``TIMESTAMPTZ`` in UTC, and mixing naive and aware datetimes raises at
    runtime in the least convenient place.
    """
    return datetime.now(UTC)


class Clock(Protocol):
    """Something that can tell the time."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC moment."""
        ...


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        """Return the current UTC moment."""
        return utcnow()


class FrozenClock:
    """A controllable clock for tests.

    Lets a test assert on expiry, rotation windows, and staleness without
    sleeping::

        clock = FrozenClock(datetime(2026, 8, 13, tzinfo=UTC))
        clock.advance(timedelta(minutes=16))  # access token now expired
    """

    def __init__(self, moment: datetime) -> None:
        """Freeze the clock at *moment*.

        Args:
            moment: A timezone-aware datetime.

        Raises:
            ValueError: If *moment* is naive.
        """
        if moment.tzinfo is None:
            msg = "FrozenClock requires a timezone-aware datetime"
            raise ValueError(msg)
        self._moment = moment.astimezone(UTC)

    def now(self) -> datetime:
        """Return the frozen moment."""
        return self._moment

    def advance(self, delta: timedelta) -> datetime:
        """Move the clock forward and return the new moment."""
        self._moment += delta
        return self._moment

    def set(self, moment: datetime) -> None:
        """Jump the clock to *moment*."""
        self._moment = moment.astimezone(UTC)


#: The process-wide real clock.
SYSTEM_CLOCK: Clock = SystemClock()
