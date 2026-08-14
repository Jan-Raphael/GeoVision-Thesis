"""The progress algorithm — the thesis contribution.

Every rule in ``Progress-Calculation.md`` gets a test that demonstrates it from
a table of numbers. That is deliberate: this is the module walked through during
the defense, and "the system produces sensible output" is not an argument. The
worked six-day example from §8 is reproduced exactly, so the table printed in the
thesis and the code that runs in production are verified to be the same thing.

Required-test list: ``Progress-Calculation.md`` §10.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai.progress.aggregator import (
    DeviceReading,
    WindowInput,
    WindowResult,
    aggregate_window,
    compute_series,
    device_value,
    macro_stage_for,
    raw_project_value,
    stage_percentages,
)
from ai.progress.constants import MACHINE_CEILING_PCT, MIN_CONFIDENCE
from ai.progress.estimator import ImageProgress, estimate
from ai.progress.mapping import MacroStage, reference_for_name

DAY_ONE = datetime(2026, 8, 1, tzinfo=UTC)


def image(
    token: str,
    *,
    device: str = "cam-fd",
    confidence: float = 0.95,
    image_id: str | None = None,
) -> ImageProgress:
    """One classified image, by stage token."""
    reference = reference_for_name(token)
    return estimate(
        image_id=image_id or f"{device}-{token}-{confidence}",
        device_id=device,
        class_index=reference.index,
        confidence=confidence,
    )


def window(
    day: int, *images: ImageProgress, weights: dict[str, float] | None = None
) -> WindowInput:
    """One daily window."""
    start = DAY_ONE + timedelta(days=day - 1)
    return WindowInput(
        window_start=start,
        window_end=start + timedelta(days=1),
        images=images,
        device_weights=weights or {},
    )


class TestPerDeviceMedian:
    """§2 — median, not mean."""

    def test_median_of_eligible_images(self) -> None:
        assert device_value((image("COL"), image("COL"), image("SLB"))) == 28.0

    def test_one_bad_frame_cannot_drag_the_reading(self) -> None:
        """The whole reason it is a median.

        Four frames agree on Walls (40) and one misfires as Site Clearing (4).
        The mean would be 32.8 — a stage and a half of damage from one frame.
        """
        images = (image("WAL"), image("WAL"), image("WAL"), image("WAL"), image("CLR"))
        assert device_value(images) == 40.0

    def test_low_confidence_images_are_excluded(self) -> None:
        """§1 — stored and badged, but never counted."""
        images = (image("COL"), image("ROF", confidence=MIN_CONFIDENCE - 0.01))
        assert device_value(images) == 28.0

    def test_a_device_with_nothing_eligible_returns_none(self) -> None:
        """None, not zero.

        A camera that saw nothing has no opinion. Scoring it 0 % would drag the
        project average down every time a lens fogged up — asserting the
        building was demolished because nobody looked at it.
        """
        assert device_value((image("WAL", confidence=0.2),)) is None

    def test_an_empty_window_returns_none(self) -> None:
        assert device_value(()) is None

    def test_even_counts_average_the_middle_two(self) -> None:
        assert device_value((image("COL"), image("SLB"))) == 31.0


class TestMultiCameraFusion:
    """§3 — weighted mean across cameras."""

    def test_equal_weights_reduce_to_a_plain_average(self) -> None:
        """The spec's original (Cam1 + Cam2) / 2."""
        readings = (
            DeviceReading("a", 28.0, 1.0, 2),
            DeviceReading("b", 40.0, 1.0, 2),
        )
        assert raw_project_value(readings) == 34.0

    def test_a_diagonal_camera_counts_for_more(self) -> None:
        """It sees two façades; a single-face view sees one."""
        readings = (
            DeviceReading("fd", 40.0, 1.5, 3),
            DeviceReading("back", 20.0, 1.0, 3),
        )
        assert raw_project_value(readings) == pytest.approx(32.0)

    def test_no_cameras_reporting_yields_none(self) -> None:
        assert raw_project_value(()) is None

    def test_zero_weighted_devices_are_ignored(self) -> None:
        """Setting a weight to 0 is how an owner mutes a misaimed camera."""
        readings = (
            DeviceReading("good", 40.0, 1.0, 2),
            DeviceReading("muted", 4.0, 0.0, 2),
        )
        assert raw_project_value(readings) == 40.0

    def test_a_silent_camera_does_not_count_as_zero(self) -> None:
        """One camera offline must not halve the project's progress."""
        both = aggregate_window(window(1, image("WAL", device="a"), image("WAL", device="b")))
        one = aggregate_window(window(1, image("WAL", device="a")))

        assert both.raw_pct == one.raw_pct == 40.0


class TestEmaSmoothing:
    """§4.1 — the exponential moving average."""

    def test_the_first_window_seeds_from_raw(self) -> None:
        result = aggregate_window(window(1, image("COL")))
        assert result.ema_pct == result.raw_pct == 28.0

    def test_subsequent_windows_blend(self) -> None:
        """ema = 0.3 * raw + 0.7 * previous."""
        first = aggregate_window(window(1, image("COL")))
        second = aggregate_window(window(2, image("WAL")), previous=first)

        assert second.ema_pct == pytest.approx(0.3 * 40.0 + 0.7 * 28.0)

    def test_it_lags_deliberately(self) -> None:
        """A jump in raw must not become a jump in the headline number."""
        first = aggregate_window(window(1, image("CLR")))
        second = aggregate_window(window(2, image("FIN")), previous=first)

        assert second.raw_pct == 80.0
        assert second.ema_pct < 30.0

    def test_it_converges_on_sustained_evidence(self) -> None:
        """Lag, not refusal: enough consistent windows and it arrives."""
        windows = tuple(window(day, image("WAL")) for day in range(1, 21))
        series = compute_series(windows)

        assert series[-1].displayed_pct == pytest.approx(40.0, abs=0.1)


class TestMonotonicRatchet:
    """§4.3 — the rule that makes the number trustworthy."""

    def test_a_single_dip_is_held(self) -> None:
        """One occluded day must not move the headline number backwards."""
        series = compute_series(
            (
                window(1, image("WAL")),
                window(2, image("WAL")),
                window(3, image("CLR")),  # truck in front of the lens
            )
        )

        assert series[2].ema_pct < series[1].ema_pct
        assert series[2].displayed_pct == series[1].displayed_pct
        assert not series[2].regressed

    def test_it_releases_after_three_consecutive_drops(self) -> None:
        """Construction genuinely can go backwards — rework, typhoon damage.

        A hard monotonic constraint would be a lie; the system must be able to
        represent a real regression, just not a transient one.
        """
        series = compute_series(
            (
                window(1, image("WAL")),
                window(2, image("WAL")),
                window(3, image("CLR")),
                window(4, image("CLR")),
                window(5, image("CLR")),
            )
        )

        assert series[4].displayed_pct < series[1].displayed_pct
        assert series[4].regressed

    def test_the_release_is_flagged_exactly_once(self) -> None:
        """The caller writes one system remark, not one per subsequent window."""
        series = compute_series(
            tuple(
                [window(1, image("WAL")), window(2, image("WAL"))]
                + [window(day, image("CLR")) for day in range(3, 9)]
            )
        )

        assert sum(1 for result in series if result.regressed) == 1

    def test_an_empty_window_never_triggers_a_regression(self) -> None:
        """A camera going offline is not the building being demolished."""
        series = compute_series(
            (
                window(1, image("WAL")),
                window(2),
                window(3),
                window(4),
                window(5),
            )
        )

        assert all(not result.regressed for result in series)
        assert series[-1].displayed_pct == series[0].displayed_pct

    def test_progress_holds_through_a_gap_in_captures(self) -> None:
        """Rain for a week: the timeline is flat, not zero and not missing."""
        series = compute_series(
            (window(1, image("ROF")), window(2), window(3), window(4, image("ROF")))
        )

        assert [round(r.displayed_pct, 1) for r in series[:3]] == [60.0, 60.0, 60.0]
        assert not series[1].had_evidence


class TestStageAdvanceGuard:
    """§4.2 — the label waits for confirmation even when the number moves."""

    @staticmethod
    def _settled_then_jump(jump_days: int) -> tuple[WindowResult, ...]:
        """Eight windows settled on Slab (34, framing), then a jump to Completed.

        The jump is large enough that the EMA crosses into the roofing band in a
        single window, which is exactly the situation the guard exists for.
        """
        settled = [window(day, image("SLB")) for day in range(1, 9)]
        jumped = [window(9 + offset, image("CMP")) for offset in range(jump_days)]
        return compute_series(tuple(settled + jumped))

    def test_one_good_day_does_not_advance_the_stage(self) -> None:
        """The number enters the new band; the label does not follow yet."""
        series = self._settled_then_jump(1)

        assert macro_stage_for(series[-1].displayed_pct) is MacroStage.ROOFING
        assert series[-1].macro_stage is MacroStage.FRAMING

    def test_two_consecutive_windows_do_advance_it(self) -> None:
        series = self._settled_then_jump(2)

        assert series[-1].macro_stage is MacroStage.ROOFING

    def test_sustained_roof_readings_settle_at_the_finishing_floor(self) -> None:
        """A quirk worth pinning rather than discovering during a defense.

        `ROF` has nominal 60, and 60 is simultaneously the roofing ceiling and
        the finishing floor. So a project whose classifier says "Roof" forever
        converges to exactly 60.0 and reads as *Finishing 0 %* — which is right:
        nominal 60 means roofing is complete.
        """
        series = compute_series(tuple(window(day, image("ROF")) for day in range(1, 20)))

        assert series[-1].displayed_pct == pytest.approx(60.0, abs=0.05)
        assert series[-1].macro_stage is MacroStage.FINISHING
        assert series[-1].stage_pcts[MacroStage.ROOFING] == 100.0
        assert series[-1].stage_pcts[MacroStage.FINISHING] == 0.0

    def test_the_number_may_rise_while_the_label_waits(self) -> None:
        """The EMA is not guarded; only the label people read at a glance is."""
        first = aggregate_window(window(1, image("FDN")))
        second = aggregate_window(window(2, image("ROF")), previous=first)

        assert second.displayed_pct > first.displayed_pct

    def test_the_stage_is_not_guarded_downward(self) -> None:
        """The ratchet already governs falling.

        Double-guarding would strand the label above a number that has genuinely
        and repeatedly dropped.
        """
        series = compute_series(
            tuple(
                [window(day, image("ROF")) for day in range(1, 8)]
                + [window(day, image("CLR")) for day in range(8, 16)]
            )
        )

        assert series[-1].macro_stage is MacroStage.FOUNDATION


class TestMachineCeiling:
    """ADR-007 — the AI cannot mark a project complete."""

    def test_progress_never_exceeds_eighty(self) -> None:
        series = compute_series(tuple(window(day, image("CMP")) for day in range(1, 40)))

        assert all(result.displayed_pct <= MACHINE_CEILING_PCT for result in series)
        assert series[-1].displayed_pct == pytest.approx(MACHINE_CEILING_PCT, abs=0.01)

    def test_reaching_the_ceiling_is_flagged_once(self) -> None:
        """The caller raises `awaiting_inspection` and notifies — exactly once."""
        series = compute_series(tuple(window(day, image("CMP")) for day in range(1, 40)))

        assert sum(1 for result in series if result.reached_ceiling) == 1

    def test_completed_maps_to_eighty_not_one_hundred(self) -> None:
        """Detecting a finished-looking building is not a completion decision."""
        assert reference_for_name("CMP").nominal_progress_pct == 80.0


class TestStagePercentages:
    """§6 — the five bars."""

    def test_the_worked_example_from_the_spec(self) -> None:
        """47 % shows Foundation 100, Framing 100, Roofing 35, rest 0."""
        stages = stage_percentages(47.0)

        assert stages[MacroStage.FOUNDATION] == 100.0
        assert stages[MacroStage.FRAMING] == 100.0
        assert stages[MacroStage.ROOFING] == pytest.approx(35.0)
        assert stages[MacroStage.FINISHING] == 0.0
        assert stages[MacroStage.APPROVAL] == 0.0

    def test_the_approval_bar_stays_empty_at_the_ceiling(self) -> None:
        """The fifth bar is the human's, and the machine never fills it."""
        assert stage_percentages(MACHINE_CEILING_PCT)[MacroStage.APPROVAL] == 0.0

    def test_every_bar_is_bounded(self) -> None:
        for value in (0.0, 13.7, 40.0, 79.9, 100.0):
            assert all(0.0 <= pct <= 100.0 for pct in stage_percentages(value).values())

    @pytest.mark.parametrize(
        ("pct", "expected"),
        [
            (0.0, MacroStage.FOUNDATION),
            (19.99, MacroStage.FOUNDATION),
            (20.0, MacroStage.FRAMING),
            (39.99, MacroStage.FRAMING),
            (40.0, MacroStage.ROOFING),
            (60.0, MacroStage.FINISHING),
            (80.0, MacroStage.APPROVAL),
        ],
    )
    def test_band_boundaries_belong_to_the_stage_being_entered(
        self, pct: float, expected: MacroStage
    ) -> None:
        assert macro_stage_for(pct) is expected


class TestWorkedExample:
    """§8 — the table printed in the thesis.

    This is the highest-value test in the module. If the code and the table ever
    disagree, one of them is a lie told to an examiner.
    """

    @staticmethod
    def _series() -> tuple[WindowResult, ...]:
        weights = {"fd": 1.5, "back": 1.0}
        return compute_series(
            (
                # Day 1: COL 28, COL 28 -> 28  |  COL 28 -> 28
                window(
                    1,
                    image("COL", device="fd", image_id="d1-fd-1"),
                    image("COL", device="fd", image_id="d1-fd-2"),
                    image("COL", device="back", image_id="d1-b-1"),
                    weights=weights,
                ),
                # Day 2: SLB 34, COL 28 -> 31  |  SLB 34 -> 34
                window(
                    2,
                    image("SLB", device="fd", image_id="d2-fd-1"),
                    image("COL", device="fd", image_id="d2-fd-2"),
                    image("SLB", device="back", image_id="d2-b-1"),
                    weights=weights,
                ),
                # Day 3: SLB 34 | SLB 34
                window(
                    3,
                    image("SLB", device="fd", image_id="d3-fd-1"),
                    image("SLB", device="back", image_id="d3-b-1"),
                    weights=weights,
                ),
                # Day 4: rain, FD all rejected | SLB 34
                window(4, image("SLB", device="back", image_id="d4-b-1"), weights=weights),
                # Day 5: WAL 40 | SLB 34
                window(
                    5,
                    image("WAL", device="fd", image_id="d5-fd-1"),
                    image("SLB", device="back", image_id="d5-b-1"),
                    weights=weights,
                ),
                # Day 6: truck occludes FD -> COL 28 | WAL 40
                window(
                    6,
                    image("COL", device="fd", image_id="d6-fd-1"),
                    image("WAL", device="back", image_id="d6-b-1"),
                    weights=weights,
                ),
            )
        )

    @pytest.mark.parametrize(
        ("day", "raw", "ema", "displayed"),
        [
            (1, 28.0, 28.0, 28.0),
            (2, 32.2, 29.3, 29.3),
            (3, 34.0, 30.7, 30.7),
            (4, 34.0, 31.7, 31.7),
            (5, 37.6, 33.5, 33.5),
            (6, 32.8, 33.3, 33.5),  # ratchet held
        ],
    )
    def test_matches_the_published_table(
        self, day: int, raw: float, ema: float, displayed: float
    ) -> None:
        result = self._series()[day - 1]

        assert result.raw_pct == pytest.approx(raw, abs=0.05)
        assert result.ema_pct == pytest.approx(ema, abs=0.05)
        assert result.displayed_pct == pytest.approx(displayed, abs=0.05)

    def test_day_six_demonstrates_the_design(self) -> None:
        """One occluded camera pulled raw down and the EMA dipped — and the
        displayed number held, because only one window regressed."""
        series = self._series()

        assert series[5].raw_pct < series[4].raw_pct
        assert series[5].ema_pct < series[4].ema_pct
        assert series[5].displayed_pct == series[4].displayed_pct
        assert not series[5].regressed

    def test_day_four_shows_a_silent_camera_is_not_a_zero(self) -> None:
        """Rain rejected every front-diagonal frame. The back camera alone
        carries the window, at its own value — not halved."""
        assert self._series()[3].raw_pct == pytest.approx(34.0)


class TestReplayability:
    """§7 — recomputation must reproduce history exactly."""

    def test_recomputing_is_deterministic(self) -> None:
        windows = tuple(window(day, image("COL")) for day in range(1, 8))

        first = compute_series(windows)
        second = compute_series(windows)

        assert [r.displayed_pct for r in first] == [r.displayed_pct for r in second]

    def test_window_order_does_not_matter(self) -> None:
        """Snapshots are rebuilt from stored rows, which arrive unordered."""
        windows = [window(day, image("COL")) for day in range(1, 6)]
        shuffled = (windows[3], windows[0], windows[4], windows[1], windows[2])

        assert [r.displayed_pct for r in compute_series(tuple(windows))] == [
            r.displayed_pct for r in compute_series(shuffled)
        ]

    def test_every_result_records_its_algorithm_version(self) -> None:
        """So a chart drawn from mixed versions is identifiable, not just wrong."""
        result = aggregate_window(window(1, image("COL")))
        assert result.algorithm_version == "progress-v1"

    def test_contributing_images_are_recorded(self) -> None:
        """An owner asking "why is it 34 %?" gets an answer, not a shrug."""
        result = aggregate_window(
            window(
                1,
                image("COL", image_id="a"),
                image("SLB", image_id="b"),
                image("ROF", image_id="c", confidence=0.1),
            )
        )

        assert set(result.contributing_image_ids) == {"a", "b"}
        assert result.eligible_image_count == 2


class TestPurity:
    """The constraint that makes this defensible."""

    def test_the_module_imports_nothing_heavy(self) -> None:
        """No I/O, no ORM, no torch — ever.

        Pinned as a test because the constraint is easy to violate by accident
        (one convenience import of a DB session) and impossible to notice.
        """
        import ai.progress.aggregator as module

        source = module.__file__
        assert source is not None
        text = __import__("pathlib").Path(source).read_text(encoding="utf-8")

        for banned in ("import torch", "sqlalchemy", "requests", "open(", "psycopg"):
            assert banned not in text, f"aggregator.py must stay pure; found {banned!r}"

    def test_aggregate_does_not_mutate_its_input(self) -> None:
        weights = {"cam-fd": 1.5}
        source = window(1, image("COL"), weights=weights)
        aggregate_window(source)

        assert weights == {"cam-fd": 1.5}
        assert source.images[0].raw_progress_pct == 28.0


class TestEstimator:
    """§1 — per-image scoring."""

    def test_the_confidence_gate(self) -> None:
        assert image("WAL", confidence=MIN_CONFIDENCE).is_eligible
        assert not image("WAL", confidence=MIN_CONFIDENCE - 0.001).is_eligible

    def test_a_low_confidence_prediction_is_still_scored(self) -> None:
        """Stored and badged, not discarded — the owner should see the camera
        saw something, even if it does not count."""
        result = image("WAL", confidence=0.3)

        assert result.raw_progress_pct == 40.0
        assert result.low_confidence

    def test_a_logit_is_refused(self) -> None:
        """Passing a raw logit would sail through the gate and make every
        prediction eligible — silently."""
        with pytest.raises(ValueError, match="probability"):
            estimate(image_id="x", device_id="d", class_index=0, confidence=7.4)

    def test_an_unknown_class_index_is_refused(self) -> None:
        """A checkpoint emitting an index this table does not know was trained
        against a different vocabulary; guessing would corrupt history."""
        with pytest.raises(KeyError):
            estimate(image_id="x", device_id="d", class_index=99, confidence=0.9)
