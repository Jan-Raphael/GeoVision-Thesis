"""Tests for domain entity invariants and derived properties.

These run with no database: entities are pure data plus rules, which is exactly
why the stage-breakdown and visibility logic can be verified this cheaply.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.entities import (
    BoundingBox,
    CaptureSchedule,
    Device,
    Image,
    Project,
    ProjectMember,
    Remark,
    StageBreakdown,
    User,
)
from app.domain.enums import (
    CameraFace,
    DeviceStatus,
    MembershipRole,
    MembershipStatus,
    ProfessionalRole,
    RemarkType,
    Severity,
    Visibility,
)
from app.domain.value_objects import GeoPoint, ProgressPct, ProjectCode

pytestmark = pytest.mark.unit


def _project(**overrides: object) -> Project:
    """Build a valid project, overriding selected fields."""
    values: dict[str, object] = {
        "id": uuid4(),
        "owner_id": uuid4(),
        "name": "Jollibee Naga",
        "code": ProjectCode("NG_00"),
        "location_label": "Naga City",
        "location": GeoPoint(13.6218, 123.1948),
        "start_date": date(2026, 1, 1),
        "deadline_date": date(2026, 12, 31),
    }
    values.update(overrides)
    return Project(**values)  # type: ignore[arg-type]


class TestProject:
    """Project invariants and schedule maths."""

    def test_deadline_before_start_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot precede"):
            _project(start_date=date(2026, 6, 1), deadline_date=date(2026, 1, 1))

    def test_negative_worker_count_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="worker_count"):
            _project(worker_count=-1)

    def test_worker_count_may_be_skipped(self) -> None:
        """The Create Project form allows skipping it and editing later."""
        assert _project(worker_count=None).worker_count is None

    def test_is_public_requires_public_and_unarchived(self) -> None:
        assert _project(visibility=Visibility.PUBLIC).is_public is True
        assert _project(visibility=Visibility.PRIVATE).is_public is False
        archived = _project(visibility=Visibility.PUBLIC, archived_at=datetime.now(UTC))
        assert archived.is_public is False

    def test_expected_progress_is_linear_to_the_machine_ceiling(self) -> None:
        """Halfway through the schedule, a linear plan expects 40 % (half of 80)."""
        project = _project(start_date=date(2026, 1, 1), deadline_date=date(2026, 1, 11))
        assert project.expected_pct_at(date(2026, 1, 6)).as_float() == pytest.approx(40.0)

    def test_expected_progress_clamps_at_both_ends(self) -> None:
        project = _project(start_date=date(2026, 1, 1), deadline_date=date(2026, 1, 11))
        assert project.expected_pct_at(date(2025, 12, 1)).as_float() == 0.0
        # Never exceeds 80: the last 20 % is a human action, not a scheduled one.
        assert project.expected_pct_at(date(2027, 1, 1)).as_float() == pytest.approx(80.0)

    def test_planned_duration_is_at_least_one_day(self) -> None:
        """Avoids a divide-by-zero for a same-day project."""
        project = _project(start_date=date(2026, 1, 1), deadline_date=date(2026, 1, 1))
        assert project.planned_duration_days == 1


class TestStageBreakdown:
    """The five bars rendered on the project folder page."""

    def test_worked_example_from_the_vault(self) -> None:
        """47 % => Foundation and Framing done, Roofing 35 %, rest zero.

        This is the exact example in ``Progress-Calculation.md`` §6.
        """
        bars = StageBreakdown.from_progress(ProgressPct(Decimal("47")))
        assert bars.foundation_pct == pytest.approx(100.0)
        assert bars.framing_pct == pytest.approx(100.0)
        assert bars.roofing_pct == pytest.approx(35.0)
        assert bars.finishing_pct == pytest.approx(0.0)
        assert bars.approval_pct == pytest.approx(0.0)

    def test_zero_progress(self) -> None:
        bars = StageBreakdown.from_progress(ProgressPct.zero())
        assert bars.foundation_pct == 0.0
        assert bars.approval_pct == 0.0

    def test_machine_ceiling_leaves_approval_empty(self) -> None:
        """At 80 % the AI is done and the approval bar has not started."""
        bars = StageBreakdown.from_progress(ProgressPct(Decimal("80")))
        assert bars.finishing_pct == pytest.approx(100.0)
        assert bars.approval_pct == pytest.approx(0.0)

    def test_full_completion_fills_every_bar(self) -> None:
        bars = StageBreakdown.from_progress(ProgressPct(Decimal("100")))
        assert bars.approval_pct == pytest.approx(100.0)


class TestUser:
    """Profile visibility (spec B.5)."""

    @staticmethod
    def _user(visibility: Visibility, *, active: bool = True) -> User:
        return User(
            id=uuid4(),
            username="alice_eng",
            email="alice@example.test",
            full_name="Alice Reyes",
            professional_role=ProfessionalRole.ENGINEER,
            profile_visibility=visibility,
            company="Reyes Construction",
            bio="Site engineer.",
            is_active=active,
        )

    def test_public_profile_exposes_details(self) -> None:
        profile = self._user(Visibility.PUBLIC).to_public_profile()
        assert profile.is_private is False
        assert profile.full_name == "Alice Reyes"
        assert profile.company == "Reyes Construction"

    def test_private_profile_exposes_only_the_username(self) -> None:
        """The redaction is structural, so a new field cannot leak by omission."""
        profile = self._user(Visibility.PRIVATE).to_public_profile()
        assert profile.is_private is True
        assert profile.username == "alice_eng"
        assert profile.full_name is None
        assert profile.company is None
        assert profile.bio is None
        assert profile.professional_role is None
        assert profile.avatar_key is None

    def test_deactivated_account_is_treated_as_private(self) -> None:
        profile = self._user(Visibility.PUBLIC, active=False).to_public_profile()
        assert profile.is_private is True


class TestDevice:
    """Device naming and liveness."""

    @staticmethod
    def _device(**overrides: object) -> Device:
        values: dict[str, object] = {
            "id": uuid4(),
            "project_id": uuid4(),
            "device_name": "ESP_NG_00_FD",
            "face": CameraFace.FRONT_DIAGONAL,
            "weight": 1.5,
        }
        values.update(overrides)
        return Device(**values)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("face", "expected"),
        [
            (CameraFace.FRONT, "ESP_NG_00_F"),
            (CameraFace.FRONT_DIAGONAL, "ESP_NG_00_FD"),
            (CameraFace.BACK, "ESP_NG_00_B"),
            (CameraFace.BACK_DIAGONAL, "ESP_NG_00_BD"),
        ],
    )
    def test_name_is_derived_never_typed(self, face: CameraFace, expected: str) -> None:
        assert Device.build_name(ProjectCode("NG_00"), face) == expected

    def test_diagonal_faces_carry_more_weight(self) -> None:
        """They see two façades, so they inform the aggregate more."""
        assert CameraFace.FRONT_DIAGONAL.default_weight == 1.5
        assert CameraFace.FRONT.default_weight == 1.0
        assert CameraFace.FRONT_DIAGONAL.faces_observed == 2

    def test_liveness_online_within_six_hours(self) -> None:
        now = datetime.now(UTC)
        device = self._device(last_seen_at=now - timedelta(hours=2))
        assert device.liveness_at(now) is DeviceStatus.ONLINE

    def test_liveness_offline_after_six_hours(self) -> None:
        now = datetime.now(UTC)
        device = self._device(last_seen_at=now - timedelta(hours=7))
        assert device.liveness_at(now) is DeviceStatus.OFFLINE

    def test_never_seen_stays_paired(self) -> None:
        device = self._device(last_seen_at=None)
        assert device.liveness_at(datetime.now(UTC)) is DeviceStatus.PAIRED

    def test_revoked_is_terminal(self) -> None:
        now = datetime.now(UTC)
        device = self._device(status=DeviceStatus.REVOKED, last_seen_at=now)
        assert device.liveness_at(now) is DeviceStatus.REVOKED

    def test_revoked_device_is_unusable(self) -> None:
        assert self._device(status=DeviceStatus.REVOKED).is_usable is False

    def test_uncalibrated_device_is_detected(self) -> None:
        """Without a homography the pipeline skips rectification, not fails."""
        assert self._device(homography=None).is_calibrated is False
        assert self._device(homography={"src": []}).is_calibrated is True


class TestCaptureSchedule:
    """Owner-configured capture times."""

    def test_default_is_twice_daily(self) -> None:
        schedule = CaptureSchedule()
        assert schedule.captures_per_day == 2
        assert schedule.times == ("07:00", "16:00")

    def test_empty_schedule_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one time"):
            CaptureSchedule(times=())

    def test_more_than_six_captures_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at most 6"):
            CaptureSchedule(times=tuple(f"{h:02d}:00" for h in range(7)))

    @pytest.mark.parametrize("bad", ["7:00pm", "25:00", "07:60", "0700", "abc"])
    def test_malformed_times_are_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError, match="capture time"):
            CaptureSchedule(times=(bad,))


class TestImage:
    """Runtime filename construction and geotag handling."""

    def test_filename_format(self) -> None:
        captured = datetime(2026, 8, 13, 7, 0, 0, tzinfo=UTC)
        name = Image.build_filename(ProjectCode("NG_00"), captured, 1)
        assert name == "NG_00_20260813T070000Z_001.jpg"

    def test_filename_never_contains_the_stage(self) -> None:
        """The stage is predicted, not known — putting it in a filename would
        eventually be mistaken for ground truth (ADR-002)."""
        captured = datetime(2026, 8, 13, 7, 0, 0, tzinfo=UTC)
        name = Image.build_filename(ProjectCode("NG_00"), captured, 1)
        for stage in ("FDN", "COL", "WAL", "foundation", "walls"):
            assert stage not in name

    def test_sequence_is_zero_padded_to_three(self) -> None:
        captured = datetime(2026, 8, 13, 16, 30, 0, tzinfo=UTC)
        assert Image.build_filename(ProjectCode("AYU_05"), captured, 42).endswith("_042.jpg")

    def test_non_utc_capture_time_is_converted_not_relabelled(self) -> None:
        """A Manila timestamp must become its true UTC equivalent.

        Regression test: an earlier implementation used
        ``astimezone(tz=None)``, which converts to the *server's* local zone
        while still writing a "Z" suffix. On a Manila-time host every capture
        would have been stamped eight hours late and filed into the wrong
        aggregation window.
        """
        manila = timezone(timedelta(hours=8))
        captured = datetime(2026, 8, 13, 15, 0, 0, tzinfo=manila)  # 07:00 UTC
        name = Image.build_filename(ProjectCode("NG_00"), captured, 1)
        assert name == "NG_00_20260813T070000Z_001.jpg"

    def test_naive_datetime_is_assumed_utc(self) -> None:
        captured = datetime(2026, 8, 13, 7, 0, 0)  # noqa: DTZ001 - deliberately naive
        assert Image.build_filename(ProjectCode("NG_00"), captured, 1) == (
            "NG_00_20260813T070000Z_001.jpg"
        )

    @pytest.mark.parametrize("seq", [0, -1, 1000])
    def test_out_of_range_sequence_is_rejected(self, seq: int) -> None:
        """The format has exactly three digits; 1000 would silently widen it."""
        captured = datetime(2026, 8, 13, 7, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="sequence number"):
            Image.build_filename(ProjectCode("NG_00"), captured, seq)

    def test_null_island_is_not_treated_as_geotagged(self) -> None:
        image = Image(
            id=uuid4(),
            project_id=uuid4(),
            filename="NG_00_20260813T070000Z_001.jpg",
            storage_key="k",
            captured_at=datetime.now(UTC),
            sha256="a" * 64,
            location=GeoPoint(0.0, 0.0),
        )
        assert image.is_geotagged is False


class TestBoundingBox:
    """Normalised detection boxes."""

    def test_valid_box(self) -> None:
        assert BoundingBox(0.1, 0.2, 0.3, 0.4).area == pytest.approx(0.12)

    @pytest.mark.parametrize(
        ("x", "y", "w", "h"),
        [(-0.1, 0.0, 0.5, 0.5), (0.0, 1.1, 0.5, 0.5), (0.0, 0.0, 0.0, 0.5), (0.0, 0.0, 0.5, -0.1)],
    )
    def test_invalid_boxes_are_rejected(self, x: float, y: float, w: float, h: float) -> None:
        with pytest.raises(ValueError, match="bounding box"):
            BoundingBox(x, y, w, h)


class TestProjectMember:
    """Membership activation."""

    @staticmethod
    def _member(status: MembershipStatus, role: MembershipRole) -> ProjectMember:
        return ProjectMember(
            id=uuid4(),
            project_id=uuid4(),
            user_id=uuid4(),
            membership_role=role,
            membership_status=status,
        )

    def test_pending_membership_confers_nothing(self) -> None:
        """An invitee has no authority until they accept."""
        member = self._member(MembershipStatus.PENDING, MembershipRole.MANAGER)
        assert member.is_active is False

    def test_accepted_membership_is_active(self) -> None:
        member = self._member(MembershipStatus.ACCEPTED, MembershipRole.VIEWER)
        assert member.is_active is True

    def test_pending_owner_is_not_an_owner(self) -> None:
        member = self._member(MembershipStatus.PENDING, MembershipRole.OWNER)
        assert member.is_owner is False


class TestRemark:
    """Remark authorship and effective windows."""

    @staticmethod
    def _remark(**overrides: object) -> Remark:
        values: dict[str, object] = {
            "id": uuid4(),
            "project_id": uuid4(),
            "remark_type": RemarkType.WEATHER,
            "severity": Severity.INFO,
            "message": "Typhoon expected.",
        }
        values.update(overrides)
        return Remark(**values)  # type: ignore[arg-type]

    def test_no_author_means_system_generated(self) -> None:
        assert self._remark(author_id=None).is_system_generated is True
        assert self._remark(author_id=uuid4()).is_system_generated is False

    def test_effective_window_bounds(self) -> None:
        remark = self._remark(effective_from=date(2026, 7, 12), effective_to=date(2026, 7, 15))
        assert remark.is_in_effect_on(date(2026, 7, 11)) is False
        assert remark.is_in_effect_on(date(2026, 7, 13)) is True
        assert remark.is_in_effect_on(date(2026, 7, 16)) is False

    def test_undated_remark_is_always_in_effect(self) -> None:
        assert self._remark().is_in_effect_on(date(2026, 1, 1)) is True
