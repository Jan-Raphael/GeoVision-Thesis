"""The automatic-remark table, exercised against numbers.

The wording and the thresholds in ``Project-Status-Rules.md`` are a thesis
artifact — they are what an examiner will ask about — so they are pinned here as
a pure function of a project's signals, with no database in sight.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.enums import ApprovalState, RemarkType, Severity
from app.domain.services.remarks import (
    REJECTION_STREAK,
    due_remarks,
    offline_remark,
)
from app.domain.services.status import ProjectSignals

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _signals(**overrides: object) -> ProjectSignals:
    """A healthy, on-schedule project unless told otherwise."""
    values: dict[str, object] = {
        "start_date": date(2026, 6, 1),
        "deadline_date": date(2026, 12, 31),
        "displayed_pct": 30.0,
        "approval_state": ApprovalState.NOT_READY,
        "last_capture_at": NOW - timedelta(hours=2),
        "archived_at": None,
    }
    values.update(overrides)
    return ProjectSignals(**values)  # type: ignore[arg-type]


def _types(signals: ProjectSignals, **kwargs: int) -> set[RemarkType]:
    """The remark types currently due."""
    return {due.remark_type for due in due_remarks(signals, NOW, **kwargs)}


class TestHealthyProject:
    """A project doing fine warrants nothing."""

    def test_says_nothing(self) -> None:
        assert due_remarks(_signals(), NOW) == ()


class TestInactivity:
    """No captures for more than a fortnight."""

    def test_silent_for_sixteen_days_warrants_a_remark(self) -> None:
        signals = _signals(last_capture_at=NOW - timedelta(days=16))
        due = due_remarks(signals, NOW)
        assert RemarkType.INACTIVITY in {item.remark_type for item in due}
        message = next(i for i in due if i.remark_type is RemarkType.INACTIVITY).message
        assert "16 days" in message
        assert "power source" in message

    def test_fourteen_days_is_not_yet_inactive(self) -> None:
        """The rule is *more than* 14 days; the boundary must not creep."""
        assert RemarkType.INACTIVITY not in _types(
            _signals(last_capture_at=NOW - timedelta(days=14))
        )

    def test_a_project_that_never_captured_is_not_nagged(self) -> None:
        """A brand-new project has no camera yet; that is not a fault."""
        assert RemarkType.INACTIVITY not in _types(_signals(last_capture_at=None))


class TestDelay:
    """Behind schedule, and past the deadline, are different conversations."""

    def test_drifting_behind_earns_a_warning(self) -> None:
        # Half-way through the schedule, expected ~40 %, sitting at 5 %.
        signals = _signals(displayed_pct=5.0)
        due = [item for item in due_remarks(signals, NOW) if item.remark_type is RemarkType.DELAY]
        assert len(due) == 1
        assert due[0].severity is Severity.WARNING
        assert "pp behind" in due[0].message

    def test_a_passed_deadline_is_critical(self) -> None:
        signals = _signals(deadline_date=date(2026, 7, 1), displayed_pct=70.0)
        due = [item for item in due_remarks(signals, NOW) if item.remark_type is RemarkType.DELAY]
        assert len(due) == 1
        assert due[0].severity is Severity.CRITICAL
        assert "01 Jul 2026" in due[0].message

    def test_a_passed_deadline_does_not_also_emit_the_warning(self) -> None:
        """One remark about the schedule, not two saying the same thing."""
        signals = _signals(deadline_date=date(2026, 7, 1), displayed_pct=2.0)
        delays = [i for i in due_remarks(signals, NOW) if i.remark_type is RemarkType.DELAY]
        assert len(delays) == 1

    def test_within_tolerance_says_nothing(self) -> None:
        """10 pp of drift is tolerated before anybody is told."""
        assert RemarkType.DELAY not in _types(_signals(displayed_pct=30.0))


class TestRejectionStreak:
    """Three refused captures in a row usually means a dirty or moved lens."""

    def test_three_in_a_row_warrants_a_remark(self) -> None:
        assert RemarkType.SYSTEM in _types(_signals(), consecutive_rejections=REJECTION_STREAK)

    def test_two_is_not_enough(self) -> None:
        assert RemarkType.SYSTEM not in _types(_signals(), consecutive_rejections=2)


class TestSilencedProjects:
    """Some projects should never be nagged."""

    def test_an_archived_project_warrants_nothing(self) -> None:
        """It was retired deliberately; complaining is noise about a decision."""
        signals = _signals(
            archived_at=NOW - timedelta(days=1),
            last_capture_at=NOW - timedelta(days=90),
            displayed_pct=1.0,
        )
        assert due_remarks(signals, NOW) == ()

    def test_an_approved_project_warrants_nothing(self) -> None:
        """Finished. Schedule drift is moot once a human signed it off."""
        signals = _signals(
            approval_state=ApprovalState.APPROVED,
            last_capture_at=NOW - timedelta(days=90),
            deadline_date=date(2026, 7, 1),
        )
        assert due_remarks(signals, NOW) == ()


class TestOfflineRemark:
    """The hardware message reads correctly for one camera and for several."""

    def test_singular_for_one_camera(self) -> None:
        assert "camera has been offline for 50 hours" in offline_remark(50, camera_count=1).message

    def test_plural_for_several(self) -> None:
        assert "cameras have been offline" in offline_remark(50, camera_count=3).message

    def test_is_a_warning_not_a_failure(self) -> None:
        assert offline_remark(50, camera_count=1).severity is Severity.WARNING
