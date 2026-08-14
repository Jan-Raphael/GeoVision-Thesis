"""Reporting periods and the two document builders.

The period rules get a table of dates because "weekly" is a business rule and
off-by-one-week is the kind of error nobody notices until a report quietly
covers the wrong seven days. The builders get rendered for real — a PDF that
imports but does not build is worth nothing, and the failure only appears when
somebody clicks Report during a demo.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.entities import (
    Device,
    Image,
    Prediction,
    ProgressSnapshot,
    Project,
    Remark,
    User,
)
from app.domain.enums import (
    ApprovalState,
    CameraFace,
    ImageSource,
    ImageStatus,
    MacroStage,
    ProfessionalRole,
    ProjectStatus,
    RemarkType,
    ReportKind,
    Severity,
    Visibility,
)
from app.domain.reporting import CaptureRow, ReportData
from app.domain.services.reporting import (
    MAX_CUSTOM_PERIOD_DAYS,
    ReportPeriod,
    resolve_period,
)
from app.domain.value_objects import Confidence, GeoPoint, ProgressPct, ProjectCode
from app.infrastructure.reports import build_csv, build_pdf

pytestmark = pytest.mark.unit

MANILA = "Asia/Manila"


class TestWeeklyPeriod:
    """A weekly report covers the last *complete* Monday-Sunday."""

    @pytest.mark.parametrize(
        ("today", "expected_start", "expected_end"),
        [
            # Run on a Wednesday -> the week before, not the three days so far.
            (date(2026, 8, 12), date(2026, 8, 3), date(2026, 8, 9)),
            # Run on a Monday -> the week that just ended yesterday.
            (date(2026, 8, 10), date(2026, 8, 3), date(2026, 8, 9)),
            # Run on a Sunday -> still the previous week; today is not over.
            (date(2026, 8, 16), date(2026, 8, 3), date(2026, 8, 9)),
        ],
    )
    def test_covers_the_previous_full_week(
        self, today: date, expected_start: date, expected_end: date
    ) -> None:
        now = datetime(today.year, today.month, today.day, 12, 0, tzinfo=UTC)
        period = resolve_period(ReportKind.WEEKLY, now=now, timezone="UTC")
        assert (period.start, period.end) == (expected_start, expected_end)
        assert period.days == 7

    def test_uses_the_projects_timezone_not_the_servers(self) -> None:
        """08:00 UTC Monday is already 16:00 Monday in Manila — same week."""
        now = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
        assert resolve_period(ReportKind.WEEKLY, now=now, timezone=MANILA).end == date(2026, 8, 9)

    def test_late_utc_sunday_is_already_monday_in_manila(self) -> None:
        """23:00 UTC Sunday is 07:00 Monday on site, so the week has rolled."""
        now = datetime(2026, 8, 9, 23, 0, tzinfo=UTC)
        utc = resolve_period(ReportKind.WEEKLY, now=now, timezone="UTC")
        manila = resolve_period(ReportKind.WEEKLY, now=now, timezone=MANILA)
        assert utc.end == date(2026, 8, 2)
        assert manila.end == date(2026, 8, 9)


class TestMonthlyPeriod:
    """A monthly report covers the last complete calendar month."""

    @pytest.mark.parametrize(
        ("today", "start", "end"),
        [
            (date(2026, 8, 14), date(2026, 7, 1), date(2026, 7, 31)),
            (date(2026, 1, 5), date(2025, 12, 1), date(2025, 12, 31)),
            (date(2024, 3, 2), date(2024, 2, 1), date(2024, 2, 29)),  # leap year
        ],
    )
    def test_covers_the_previous_month(self, today: date, start: date, end: date) -> None:
        now = datetime(today.year, today.month, today.day, 12, 0, tzinfo=UTC)
        period = resolve_period(ReportKind.MONTHLY, now=now, timezone="UTC")
        assert (period.start, period.end) == (start, end)


class TestCustomPeriod:
    """Caller-supplied spans, validated."""

    def test_accepts_a_valid_span(self) -> None:
        period = resolve_period(
            ReportKind.CUSTOM,
            now=datetime(2026, 8, 14, tzinfo=UTC),
            timezone=MANILA,
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 15),
        )
        assert period.days == 15

    def test_requires_both_dates(self) -> None:
        with pytest.raises(ValueError, match="requires both"):
            resolve_period(
                ReportKind.CUSTOM,
                now=datetime(2026, 8, 14, tzinfo=UTC),
                timezone=MANILA,
                period_start=date(2026, 7, 1),
            )

    def test_rejects_an_inverted_span(self) -> None:
        with pytest.raises(ValueError, match="cannot precede"):
            resolve_period(
                ReportKind.CUSTOM,
                now=datetime(2026, 8, 14, tzinfo=UTC),
                timezone=MANILA,
                period_start=date(2026, 7, 15),
                period_end=date(2026, 7, 1),
            )

    def test_rejects_a_span_longer_than_a_year(self) -> None:
        """Otherwise the gallery and per-image CSV grow without bound."""
        start = date(2025, 1, 1)
        with pytest.raises(ValueError, match="maximum"):
            resolve_period(
                ReportKind.CUSTOM,
                now=datetime(2026, 8, 14, tzinfo=UTC),
                timezone=MANILA,
                period_start=start,
                period_end=start + timedelta(days=MAX_CUSTOM_PERIOD_DAYS),
            )


class TestPeriodBounds:
    """Querying captures needs UTC instants, not local dates."""

    def test_manila_bounds_are_shifted_off_midnight_utc(self) -> None:
        """A Manila day starts at 16:00 UTC the day before."""
        period = ReportPeriod(date(2026, 8, 3), date(2026, 8, 9), MANILA)
        start, end = period.bounds_utc()
        assert start == datetime(2026, 8, 2, 16, 0, tzinfo=UTC)
        assert end == datetime(2026, 8, 9, 16, 0, tzinfo=UTC)

    def test_an_unknown_timezone_degrades_to_utc(self) -> None:
        """A mistyped zone must not make a project's reports ungeneratable."""
        period = ReportPeriod(date(2026, 8, 3), date(2026, 8, 3), "Mars/Olympus")
        start, _ = period.bounds_utc()
        assert start == datetime(2026, 8, 3, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _report_data(*, empty: bool = False) -> ReportData:
    """A week of captures on a real-looking project."""
    owner = User(
        id=uuid4(),
        username="jrm",
        email="jrm@gvmail.com",
        full_name="Jan Raphael Macabulos",
        professional_role=ProfessionalRole.ENGINEER,
    )
    project = Project(
        id=uuid4(),
        owner_id=owner.id,
        name="Jollibee Naga Branch",
        code=ProjectCode("NG_00"),
        location_label="Panganiban Dr, Naga City",
        location=GeoPoint(13.6218, 123.1948),
        start_date=date(2026, 6, 1),
        deadline_date=date(2026, 12, 31),
        visibility=Visibility.PUBLIC,
        progress_pct=ProgressPct.from_float(38.5),
        macro_stage=MacroStage.FRAMING,
        approval_state=ApprovalState.NOT_READY,
        timezone=MANILA,
    )
    device = Device(
        id=uuid4(),
        project_id=project.id,
        device_name="ESP_NG_00_FD",
        face=CameraFace.FRONT_DIAGONAL,
        weight=1.0,
        last_seen_at=datetime(2026, 8, 9, 8, 0, tzinfo=UTC),
        last_battery_mv=3870,
    )
    period = ReportPeriod(date(2026, 8, 3), date(2026, 8, 9), MANILA)

    if empty:
        return ReportData(
            project=project,
            owner=owner,
            period=period,
            generated_at=datetime.now(UTC),
            devices=(device,),
            status=ProjectStatus.INACTIVE,
            status_reason="No captures in 21 days.",
            expected_pct=32.9,
        )

    snapshots: list[ProgressSnapshot] = []
    captures: list[CaptureRow] = []
    for n in range(7):
        day = datetime(2026, 8, 3, 4, 0, tzinfo=UTC) + timedelta(days=n)
        pct = 30.0 + n * 1.4
        snapshots.append(
            ProgressSnapshot(
                id=uuid4(),
                project_id=project.id,
                window_start=day,
                window_end=day + timedelta(days=1),
                raw_pct=ProgressPct.from_float(pct),
                ema_pct=ProgressPct.from_float(pct),
                displayed_pct=ProgressPct.from_float(pct),
                macro_stage=MacroStage.FRAMING,
                foundation_pct=100.0,
                framing_pct=min(pct * 2, 100.0),
                eligible_image_count=2,
                device_weights={"ESP_NG_00_FD": 1.0},
            )
        )
        for seq in (1, 2):
            rejected = n == 4 and seq == 2
            image = Image(
                id=uuid4(),
                project_id=project.id,
                device_id=device.id,
                filename=f"NG_00_202608{3 + n:02d}T0{6 + seq}0000Z_00{seq}.jpg",
                storage_key=f"projects/{project.id}/{uuid4().hex}.jpg",
                captured_at=day + timedelta(hours=seq),
                sha256=uuid4().hex * 2,
                source=ImageSource.DEVICE,
                status=ImageStatus.REJECTED if rejected else ImageStatus.INFERRED,
                seq_number=seq,
                location=GeoPoint(13.6218, 123.1948),
                rejected_reason="blurry" if rejected else None,
            )
            prediction = (
                None
                if rejected
                else Prediction(
                    id=uuid4(),
                    image_id=image.id,
                    model_id=uuid4(),
                    fine_class_index=6,
                    fine_class="Walls",
                    confidence=Confidence.from_float(0.91),
                    macro_stage=MacroStage.FRAMING,
                    raw_progress_pct=ProgressPct.from_float(40.0),
                )
            )
            captures.append(
                CaptureRow(image=image, prediction=prediction, device_name=device.device_name)
            )

    return ReportData(
        project=project,
        owner=owner,
        period=period,
        generated_at=datetime.now(UTC),
        snapshots=tuple(snapshots),
        captures=tuple(captures),
        devices=(device,),
        remarks=(
            Remark(
                id=uuid4(),
                project_id=project.id,
                author_id=owner.id,
                remark_type=RemarkType.WEATHER,
                severity=Severity.WARNING,
                message="Heavy rain on 6 Aug halted exterior work for a day.",
                is_public=True,
                created_at=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
            ),
        ),
        status=ProjectStatus.ACTIVE,
        status_reason="On track; last capture 2 hours ago.",
        expected_pct=32.9,
        detection_counts={"wall": 41, "column": 18, "worker": 7},
    )


class TestReportData:
    """The aggregate's derived answers."""

    def test_counts_rejections_separately_from_captures(self) -> None:
        data = _report_data()
        assert len(data.captures) == 14
        assert data.rejected_count == 1
        assert len(data.eligible_captures) == 13

    def test_empty_period_reports_no_data(self) -> None:
        assert _report_data(empty=True).has_data is False

    def test_progress_comes_from_the_last_snapshot(self) -> None:
        data = _report_data()
        assert data.displayed_pct == pytest.approx(30.0 + 6 * 1.4)


class TestCsvBuilder:
    """Two tables, one file."""

    def test_contains_both_tables_with_their_headers(self) -> None:
        text = build_csv(_report_data()).decode()
        lines = text.splitlines()
        assert lines[0].startswith("window_start,displayed_pct")
        blank = lines.index("")
        assert lines[blank + 1].startswith("filename,captured_at")
        assert len(lines) == 1 + 7 + 1 + 1 + 14

    def test_a_rejected_capture_has_blank_prediction_columns(self) -> None:
        """Blank, not `false` — it was never judged, not judged ineligible."""
        rows = [
            line for line in build_csv(_report_data()).decode().splitlines() if ",rejected," in line
        ]
        assert len(rows) == 1
        assert rows[0].endswith(",rejected,,,,,")

    def test_uses_rfc4180_line_endings(self) -> None:
        assert b"\r\n" in build_csv(_report_data())

    def test_empty_period_still_emits_both_headers(self) -> None:
        """An empty file is indistinguishable from a failed export."""
        text = build_csv(_report_data(empty=True)).decode()
        assert "window_start,displayed_pct" in text
        assert "filename,captured_at" in text


class TestPdfBuilder:
    """The document actually builds, and says what it must."""

    def test_produces_a_multi_page_pdf(self) -> None:
        payload = build_pdf(_report_data())
        assert payload.startswith(b"%PDF-")
        assert payload.endswith(b"%%EOF\n") or payload.rstrip().endswith(b"%%EOF")
        assert len(payload) > 20_000

    def test_an_empty_period_still_renders(self) -> None:
        """ "No captures for three weeks" is one of the more important things a
        report can say, so it must produce a document rather than an error."""
        payload = build_pdf(_report_data(empty=True))
        assert payload.startswith(b"%PDF-")

    def test_carries_the_required_disclaimer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The document must never present an AI estimate as a measurement.

        Rendered with compression off so the text is greppable; ReportLab
        compresses page streams by default, which is why a naive byte search on
        a normal build finds nothing.
        """
        import reportlab.rl_config as rl_config

        monkeypatch.setattr(rl_config, "pageCompression", 0)
        payload = build_pdf(_report_data())

        for phrase in (
            b"estimate produced by a computer-vision model",
            b"not a survey",
            b"physical inspection",
            b"Interior work is invisible",
        ):
            assert phrase in payload, f"missing from the PDF: {phrase!r}"

    def test_renders_timestamps_in_the_projects_timezone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A report that says "07:00" without a zone is ambiguous evidence."""
        import reportlab.rl_config as rl_config

        monkeypatch.setattr(rl_config, "pageCompression", 0)
        payload = build_pdf(_report_data())
        assert b"PST" in payload or b"UTC+0800" in payload
