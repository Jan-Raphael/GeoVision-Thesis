"""What a reporting period actually means.

"Weekly" is a business rule, not a formatting detail, and getting it wrong is
the kind of error nobody notices until a report quietly covers eight days. Kept
pure and here so Module 15 can test it against a table of dates without a
database, and so the same answer is used by the API, the worker, and the beat
job that will schedule reports later.

The governing choice: a period is always **complete**. A weekly report run on a
Wednesday covers the previous Monday-to-Sunday, not the three days so far this
week. A partial period would show a progress curve that appears to flatten
simply because the week has not finished yet, and a reader comparing two reports
would be comparing a full week against a fragment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from app.domain.enums import ReportKind

if TYPE_CHECKING:
    from datetime import tzinfo

__all__ = [
    "MAX_CUSTOM_PERIOD_DAYS",
    "ReportPeriod",
    "resolve_period",
]

#: A custom period may not exceed a year. Beyond that the image gallery and the
#: per-image CSV grow without bound, and a report nobody can open is not a
#: report.
MAX_CUSTOM_PERIOD_DAYS: Final = 366


@dataclass(frozen=True, slots=True)
class ReportPeriod:
    """An inclusive span of calendar days, and the zone it was computed in."""

    start: date
    end: date
    timezone: str

    def __post_init__(self) -> None:
        """Reject an inverted span."""
        if self.end < self.start:
            msg = f"report period end ({self.end}) cannot precede start ({self.start})"
            raise ValueError(msg)

    @property
    def days(self) -> int:
        """How many calendar days the period covers, inclusive."""
        return (self.end - self.start).days + 1

    @property
    def label(self) -> str:
        """Human-readable span for the report cover."""
        return f"{self.start:%d %b %Y} to {self.end:%d %b %Y}"

    def bounds_utc(self) -> tuple[datetime, datetime]:
        """Half-open ``[start, end)`` in UTC, for querying captures.

        The conversion matters: a project in ``Asia/Manila`` starts its day eight
        hours before UTC does, so a naive UTC range would pull the first eight
        hours of the day *after* the period and drop the first eight of the day
        it should have covered.
        """
        zone = _zone(self.timezone)
        begin = datetime.combine(self.start, time.min, tzinfo=zone)
        finish = datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=zone)
        return begin.astimezone(ZoneInfo("UTC")), finish.astimezone(ZoneInfo("UTC"))


def resolve_period(
    kind: ReportKind,
    *,
    now: datetime,
    timezone: str,
    period_start: date | None = None,
    period_end: date | None = None,
) -> ReportPeriod:
    """Work out which days a report covers.

    Args:
        kind: Weekly, monthly, or custom.
        now: Current time; converted into *timezone* before any date arithmetic.
        timezone: The **project's** zone, not the server's or the caller's. A
            report is about a construction site, and the site is where the days
            are.
        period_start: Required for ``CUSTOM``.
        period_end: Required for ``CUSTOM``.

    Returns:
        The resolved period.

    Raises:
        ValueError: If a custom period is incomplete, inverted, or longer than
            :data:`MAX_CUSTOM_PERIOD_DAYS`.
    """
    today = now.astimezone(_zone(timezone)).date()

    if kind is ReportKind.WEEKLY:
        # `weekday()` is 0 for Monday, so this lands on the Monday of the
        # current week; step back one week for the last *complete* one.
        this_monday = today - timedelta(days=today.weekday())
        start = this_monday - timedelta(days=7)
        return ReportPeriod(start=start, end=start + timedelta(days=6), timezone=timezone)

    if kind is ReportKind.MONTHLY:
        first_of_this_month = today.replace(day=1)
        end = first_of_this_month - timedelta(days=1)
        return ReportPeriod(start=end.replace(day=1), end=end, timezone=timezone)

    if period_start is None or period_end is None:
        msg = "a custom report requires both period_start and period_end"
        raise ValueError(msg)
    period = ReportPeriod(start=period_start, end=period_end, timezone=timezone)
    if period.days > MAX_CUSTOM_PERIOD_DAYS:
        msg = f"custom period spans {period.days} days; the maximum is {MAX_CUSTOM_PERIOD_DAYS}"
        raise ValueError(msg)
    return period


def _zone(name: str) -> tzinfo:
    """Resolve a zone name, falling back to UTC rather than failing a report.

    A project row with a mistyped zone should not make its reports
    ungeneratable — the period is then a day out at worst, and the report states
    the zone it used.
    """
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")
