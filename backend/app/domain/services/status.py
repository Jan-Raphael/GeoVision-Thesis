"""Derivation of a project's status from observable signals.

``projects.status`` is **computed, never hand-set** (except ``ARCHIVED``). This
is the executable form of ``GeoVision-Vault/02-Domain/Project-Status-Rules.md``.

Pure functions with an explicit "now" argument: Module 10 runs the same rules on
a schedule, and both callers must be testable without waiting for real time to
pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final

from app.domain.enums import ApprovalState, ProjectStatus

__all__ = [
    "DELAY_TOLERANCE_PP",
    "INACTIVE_AFTER_DAYS",
    "ProjectSignals",
    "derive_status",
    "explain_status",
]

#: No capture for longer than this and the project is considered inactive.
INACTIVE_AFTER_DAYS: Final = 14

#: How far behind the planned curve a project may drift before it is "delayed".
#: Percentage *points*, not a percentage of a percentage.
DELAY_TOLERANCE_PP: Final = 10.0


@dataclass(frozen=True, slots=True)
class ProjectSignals:
    """Everything the status rules need, and nothing else.

    A plain value object rather than the ``Project`` entity so the rules can be
    exercised with a handful of numbers, and so Module 10's batch job can build
    signals for many projects from one query.
    """

    start_date: date
    deadline_date: date
    displayed_pct: float
    approval_state: ApprovalState
    last_capture_at: datetime | None = None
    archived_at: datetime | None = None

    def days_since_last_capture(self, now: datetime) -> int | None:
        """Days since the most recent capture, or ``None`` if there never was one."""
        if self.last_capture_at is None:
            return None
        return max((now - self.last_capture_at).days, 0)

    def expected_pct_at(self, moment: date) -> float:
        """Progress a linear schedule predicts by *moment*.

        Capped at the 80 % machine ceiling: the final 20 % is a human
        inspection, and no schedule can predict when somebody will walk the
        site. Treating it as scheduled work would mark every finished-but-
        unapproved project as "delayed".
        """
        span = max((self.deadline_date - self.start_date).days, 1)
        elapsed = (moment - self.start_date).days
        ratio = min(max(elapsed / span, 0.0), 1.0)
        return ratio * 80.0

    def is_behind_schedule(self, now: datetime) -> bool:
        """Whether the project has drifted past the delay tolerance."""
        if self.approval_state is ApprovalState.APPROVED:
            return False
        today = now.date()
        if today > self.deadline_date:
            return True
        return self.displayed_pct < self.expected_pct_at(today) - DELAY_TOLERANCE_PP


def derive_status(signals: ProjectSignals, now: datetime) -> ProjectStatus:
    """Compute a project's status.

    First match wins; the ordering is the rule, not an implementation detail:

    1. ``ARCHIVED`` — an explicit owner action, overrides everything.
    2. ``COMPLETED`` — a human approved it, so schedule drift is moot.
    3. ``INACTIVE`` — no captures for two weeks. Checked *before* delay because
       "the camera stopped" is more actionable than "you are behind", and a
       silent project is behind almost by definition.
    4. ``DELAYED`` — behind the planned curve, or past the deadline.
    5. ``ACTIVE`` — none of the above.

    Args:
        signals: The observable state.
        now: Current UTC moment.

    Returns:
        The derived status.
    """
    if signals.archived_at is not None:
        return ProjectStatus.ARCHIVED
    if signals.approval_state is ApprovalState.APPROVED:
        return ProjectStatus.COMPLETED

    idle_days = signals.days_since_last_capture(now)
    if idle_days is not None and idle_days > INACTIVE_AFTER_DAYS:
        return ProjectStatus.INACTIVE

    if signals.is_behind_schedule(now):
        return ProjectStatus.DELAYED
    return ProjectStatus.ACTIVE


def explain_status(signals: ProjectSignals, now: datetime) -> str:
    """A one-line reason for the current status.

    The dashboard shows this beside the badge. "Delayed" on its own invites a
    support question; "18 pp behind the expected schedule" does not.
    """
    status = derive_status(signals, now)
    if status is ProjectStatus.ARCHIVED:
        return "This project has been archived."
    if status is ProjectStatus.COMPLETED:
        return "Completed and signed off after physical inspection."

    if status is ProjectStatus.INACTIVE:
        idle = signals.days_since_last_capture(now)
        return f"No new captures in {idle} days. Check the camera and its power source."

    if status is ProjectStatus.DELAYED:
        today = now.date()
        if today > signals.deadline_date:
            overdue = (today - signals.deadline_date).days
            return (
                f"The deadline of {signals.deadline_date.isoformat()} passed "
                f"{overdue} day{'s' if overdue != 1 else ''} ago."
            )
        gap = signals.expected_pct_at(today) - signals.displayed_pct
        return f"Progress is {gap:.0f} pp behind the expected schedule."

    remaining = (signals.deadline_date - now.date()).days
    if remaining < 0:
        return "On track."
    return f"On track, {remaining} day{'s' if remaining != 1 else ''} until the deadline."


def next_review_at(now: datetime) -> datetime:
    """When the status should next be recomputed.

    Module 10's beat job uses this; six hours is frequent enough that a project
    never looks stale for a working day, and rare enough to be free.
    """
    return now + timedelta(hours=6)
