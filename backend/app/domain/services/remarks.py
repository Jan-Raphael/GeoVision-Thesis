"""Which automatic remarks a project is currently owed.

The message table in ``Project-Status-Rules.md`` lives here, as a pure function
of a project's signals. Keeping it pure is what makes it arguable: the rules can
be exercised against a handful of numbers, the wording is reviewable in one
place, and the scheduled job that writes them does no deciding of its own.

**Deduplication is not this module's job.** It reports what is *true now*; the
caller checks whether the same thing was already said recently and stays quiet
if so. Mixing the two would mean a rule could not be tested without a database,
and the 72-hour window is a delivery concern rather than a statement about the
project.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from app.domain.enums import ApprovalState, RemarkType, Severity
from app.domain.services.status import INACTIVE_AFTER_DAYS

if TYPE_CHECKING:
    from datetime import datetime

    from app.domain.services.status import ProjectSignals

__all__ = [
    "DEDUPE_WINDOW_HOURS",
    "REJECTION_STREAK",
    "DueRemark",
    "due_remarks",
    "offline_remark",
]

#: A system remark of the same ``(project, type)`` is not repeated inside this
#: window. Long enough that a project which is simply idle does not accumulate a
#: daily complaint; short enough that a persisting problem is restated.
DEDUPE_WINDOW_HOURS: Final = 72

#: How many consecutive rejected captures before the owner is told. Three,
#: because one blurred frame is weather and two is bad luck, but three in a row
#: usually means the lens is dirty, obstructed, or knocked.
REJECTION_STREAK: Final = 3


@dataclass(frozen=True, slots=True)
class DueRemark:
    """A remark the project currently warrants."""

    remark_type: RemarkType
    severity: Severity
    message: str


def due_remarks(
    signals: ProjectSignals,
    now: datetime,
    *,
    consecutive_rejections: int = 0,
) -> tuple[DueRemark, ...]:
    """Every automatic remark this project currently warrants.

    Args:
        signals: The project's status inputs.
        now: Current time.
        consecutive_rejections: How many of the most recent captures the quality
            gate refused, counting back from the newest.

    Returns:
        The due remarks, in the order they should be written. An archived
        project warrants none — it has been retired deliberately, and telling
        its owner it is behind schedule would be noise about a decision they
        already made.
    """
    if signals.archived_at is not None:
        return ()
    if signals.approval_state is ApprovalState.APPROVED:
        return ()

    due: list[DueRemark] = []
    today = now.date()

    idle_days = signals.days_since_last_capture(now)
    if idle_days is not None and idle_days > INACTIVE_AFTER_DAYS:
        due.append(
            DueRemark(
                RemarkType.INACTIVITY,
                Severity.WARNING,
                f"No new captures in {idle_days} days. Check the camera and its power source.",
            )
        )

    if today > signals.deadline_date:
        # Critical rather than warning: the deadline has *passed*, which is a
        # different conversation from drifting towards it.
        due.append(
            DueRemark(
                RemarkType.DELAY,
                Severity.CRITICAL,
                f"Deadline of {signals.deadline_date:%d %b %Y} has passed and the "
                "project is not yet marked complete.",
            )
        )
    elif signals.is_behind_schedule(now):
        behind = signals.expected_pct_at(today) - signals.displayed_pct
        due.append(
            DueRemark(
                RemarkType.DELAY,
                Severity.WARNING,
                f"Progress is {behind:.0f} pp behind the expected schedule for the set deadline.",
            )
        )

    if consecutive_rejections >= REJECTION_STREAK:
        due.append(
            DueRemark(
                RemarkType.SYSTEM,
                Severity.INFO,
                f"The last {consecutive_rejections} captures were rejected for image "
                "quality (blur, darkness, or obstruction).",
            )
        )

    return tuple(due)


def offline_remark(hours: int, *, camera_count: int) -> DueRemark:
    """The remark for a site whose cameras have all gone quiet.

    Separate from :func:`due_remarks` because it is a fact about *hardware*, not
    about the project's schedule, and it is produced by the device sweep on a
    much tighter cadence.
    """
    cameras = "camera has" if camera_count == 1 else "cameras have"
    return DueRemark(
        RemarkType.SYSTEM,
        Severity.WARNING,
        f"All paired {cameras} been offline for {hours} hours. "
        "Progress cannot be updated until a camera reports again.",
    )
