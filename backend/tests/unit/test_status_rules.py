"""Project status derivation, covering every branch of the vault's rules.

Reference: ``GeoVision-Vault/02-Domain/Project-Status-Rules.md``. Pure functions
with an injected "now", so a two-week inactivity rule is tested in
microseconds rather than by waiting.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.enums import ApprovalState, ProjectStatus
from app.domain.services.status import (
    DELAY_TOLERANCE_PP,
    INACTIVE_AFTER_DAYS,
    ProjectSignals,
    derive_status,
    explain_status,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _signals(**overrides: object) -> ProjectSignals:
    """A healthy, on-schedule project unless told otherwise."""
    values: dict[str, object] = {
        # Halfway through a 200-day schedule, so ~40 % is expected.
        "start_date": date(2026, 5, 5),
        "deadline_date": date(2026, 11, 21),
        "displayed_pct": 40.0,
        "approval_state": ApprovalState.NOT_READY,
        "last_capture_at": NOW - timedelta(hours=3),
    }
    values.update(overrides)
    return ProjectSignals(**values)  # type: ignore[arg-type]


class TestPrecedence:
    """First match wins; the ordering is the rule, not an accident."""

    def test_archived_beats_everything(self) -> None:
        signals = _signals(
            archived_at=NOW,
            approval_state=ApprovalState.APPROVED,
            last_capture_at=NOW - timedelta(days=60),
        )
        assert derive_status(signals, NOW) is ProjectStatus.ARCHIVED

    def test_approved_beats_inactive_and_delayed(self) -> None:
        """An approved project is finished; schedule drift is moot."""
        signals = _signals(
            approval_state=ApprovalState.APPROVED,
            displayed_pct=100.0,
            last_capture_at=NOW - timedelta(days=90),
        )
        assert derive_status(signals, NOW) is ProjectStatus.COMPLETED

    def test_inactive_beats_delayed(self) -> None:
        """ "The camera stopped" is more actionable than "you are behind".

        A silent project is behind almost by definition, so reporting the
        silence is the more useful of the two.
        """
        signals = _signals(displayed_pct=0.0, last_capture_at=NOW - timedelta(days=30))
        assert derive_status(signals, NOW) is ProjectStatus.INACTIVE


class TestInactivity:
    """No captures for two weeks."""

    def test_recent_capture_is_active(self) -> None:
        assert derive_status(_signals(), NOW) is ProjectStatus.ACTIVE

    def test_exactly_at_the_threshold_is_still_active(self) -> None:
        signals = _signals(last_capture_at=NOW - timedelta(days=INACTIVE_AFTER_DAYS))
        assert derive_status(signals, NOW) is ProjectStatus.ACTIVE

    def test_one_day_past_the_threshold_is_inactive(self) -> None:
        signals = _signals(last_capture_at=NOW - timedelta(days=INACTIVE_AFTER_DAYS + 1))
        assert derive_status(signals, NOW) is ProjectStatus.INACTIVE

    def test_a_project_with_no_captures_yet_is_not_inactive(self) -> None:
        """A brand-new project has never had a camera; that is not a fault."""
        signals = _signals(last_capture_at=None)
        assert derive_status(signals, NOW) is ProjectStatus.ACTIVE


class TestDelay:
    """Behind the planned curve, or past the deadline."""

    def test_on_schedule_is_active(self) -> None:
        assert derive_status(_signals(displayed_pct=40.0), NOW) is ProjectStatus.ACTIVE

    def test_within_tolerance_is_still_active(self) -> None:
        """Small drift is normal on a construction site, not an alarm."""
        expected = _signals().expected_pct_at(NOW.date())
        signals = _signals(displayed_pct=expected - (DELAY_TOLERANCE_PP - 1))
        assert derive_status(signals, NOW) is ProjectStatus.ACTIVE

    def test_beyond_tolerance_is_delayed(self) -> None:
        expected = _signals().expected_pct_at(NOW.date())
        signals = _signals(displayed_pct=expected - (DELAY_TOLERANCE_PP + 1))
        assert derive_status(signals, NOW) is ProjectStatus.DELAYED

    def test_past_deadline_and_unapproved_is_delayed(self) -> None:
        signals = _signals(deadline_date=NOW.date() - timedelta(days=1), displayed_pct=80.0)
        assert derive_status(signals, NOW) is ProjectStatus.DELAYED

    def test_past_deadline_but_approved_is_completed(self) -> None:
        signals = _signals(
            deadline_date=NOW.date() - timedelta(days=30),
            approval_state=ApprovalState.APPROVED,
        )
        assert derive_status(signals, NOW) is ProjectStatus.COMPLETED


class TestExpectedCurve:
    """The linear planned curve, capped at the machine ceiling."""

    def test_expected_is_zero_before_the_start(self) -> None:
        signals = _signals(start_date=date(2027, 1, 1), deadline_date=date(2027, 6, 1))
        assert signals.expected_pct_at(date(2026, 1, 1)) == 0.0

    def test_expected_is_half_of_eighty_at_the_midpoint(self) -> None:
        signals = _signals(start_date=date(2026, 1, 1), deadline_date=date(2026, 1, 11))
        assert signals.expected_pct_at(date(2026, 1, 6)) == pytest.approx(40.0)

    def test_expected_never_exceeds_the_machine_ceiling(self) -> None:
        """The final 20 % is a human inspection and cannot be scheduled.

        Without this cap, every finished-but-unapproved project would be
        reported as delayed for the gap the AI is not allowed to close.
        """
        signals = _signals(start_date=date(2026, 1, 1), deadline_date=date(2026, 1, 11))
        assert signals.expected_pct_at(date(2027, 1, 1)) == pytest.approx(80.0)

    def test_same_day_project_does_not_divide_by_zero(self) -> None:
        """A start == deadline project must not blow up.

        Day zero of a same-day schedule expects 0 %: no time has elapsed yet.
        The guard is the `max(span, 1)`, not the value.
        """
        signals = _signals(start_date=date(2026, 8, 13), deadline_date=date(2026, 8, 13))
        assert signals.expected_pct_at(date(2026, 8, 13)) == pytest.approx(0.0)
        assert signals.expected_pct_at(date(2026, 8, 14)) == pytest.approx(80.0)


class TestExplanations:
    """The reason shown beside the status badge."""

    def test_inactive_names_the_number_of_days(self) -> None:
        signals = _signals(last_capture_at=NOW - timedelta(days=20))
        assert "20 days" in explain_status(signals, NOW)

    def test_delayed_quantifies_the_gap(self) -> None:
        """ "Delayed" alone invites a support question; a number does not."""
        expected = _signals().expected_pct_at(NOW.date())
        signals = _signals(displayed_pct=expected - 25)
        message = explain_status(signals, NOW)
        assert "pp behind" in message

    def test_overdue_names_the_deadline(self) -> None:
        signals = _signals(deadline_date=date(2026, 8, 1), displayed_pct=80.0)
        assert "2026-08-01" in explain_status(signals, NOW)

    def test_active_counts_down_to_the_deadline(self) -> None:
        assert "until the deadline" in explain_status(_signals(), NOW)

    def test_completed_mentions_the_inspection(self) -> None:
        signals = _signals(approval_state=ApprovalState.APPROVED)
        assert "inspection" in explain_status(signals, NOW).lower()
