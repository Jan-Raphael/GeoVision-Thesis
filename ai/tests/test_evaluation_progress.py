"""Unit tests for `ai.evaluation.progress_eval`.

Builds `WindowResult` rows directly rather than through the aggregator, so
these tests describe exactly the series they check — the aggregator's own
behaviour is `ai/tests/test_aggregator.py`'s job, and the worked-example
reconstruction that ties the two together lives in `test_run_all.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ai.evaluation.progress_eval import (
    GroundTruthPoint,
    evaluate_against_ground_truth,
    jitter_reduction,
    monotonicity_violations,
    stage_transition_lag,
)
from ai.progress.aggregator import WindowResult
from ai.progress.mapping import MacroStage


def _window(
    day: int,
    raw_pct: float,
    displayed_pct: float,
    *,
    ema_pct: float | None = None,
    regressed: bool = False,
    stage: MacroStage = MacroStage.FRAMING,
    had_evidence: bool = True,
) -> WindowResult:
    return WindowResult(
        window_start=datetime(2026, 1, day, tzinfo=UTC),
        window_end=datetime(2026, 1, day, tzinfo=UTC),
        raw_pct=raw_pct,
        ema_pct=ema_pct if ema_pct is not None else raw_pct,
        displayed_pct=displayed_pct,
        macro_stage=stage,
        stage_pcts={},
        eligible_image_count=1,
        contributing_image_ids=(f"img-{day}",),
        device_weights={},
        regressed=regressed,
        had_evidence=had_evidence,
    )


class TestMonotonicityViolations:
    def test_a_rising_series_has_none(self) -> None:
        series = [_window(1, 10, 10), _window(2, 15, 15), _window(3, 20, 20)]
        assert monotonicity_violations(series) == 0

    def test_a_sanctioned_ratchet_release_is_not_a_violation(self) -> None:
        series = [_window(1, 30, 30), _window(2, 20, 20, regressed=True)]
        assert monotonicity_violations(series) == 0

    def test_a_drop_without_the_regressed_flag_is_a_violation(self) -> None:
        """This is what would fail if the aggregator's own guarantee ever broke."""
        series = [_window(1, 30, 30), _window(2, 20, 20, regressed=False)]
        assert monotonicity_violations(series) == 1

    def test_a_flat_series_has_none(self) -> None:
        series = [_window(1, 30, 30), _window(2, 30, 30)]
        assert monotonicity_violations(series) == 0


class TestJitterReduction:
    def test_a_perfectly_smooth_displayed_series_shows_full_reduction(self) -> None:
        series = [
            _window(1, 10, 20, ema_pct=10),
            _window(2, 30, 20, ema_pct=30),  # raw swings, displayed held flat
            _window(3, 5, 20, ema_pct=5),
        ]
        raw_std, displayed_std, reduction = jitter_reduction(series)
        assert displayed_std == 0.0
        assert raw_std > 0.0
        assert reduction == 100.0

    def test_identical_raw_and_displayed_series_show_no_reduction(self) -> None:
        series = [_window(1, 10, 10), _window(2, 20, 20), _window(3, 15, 15)]
        raw_std, displayed_std, reduction = jitter_reduction(series)
        assert raw_std == displayed_std
        assert reduction == 0.0

    def test_fewer_than_two_windows_is_defined_as_zero(self) -> None:
        assert jitter_reduction([_window(1, 10, 10)]) == (0.0, 0.0, 0.0)
        assert jitter_reduction([]) == (0.0, 0.0, 0.0)


class TestStageTransitionLag:
    def test_zero_lag_when_the_system_confirms_on_the_true_day(self) -> None:
        series = [_window(1, 25, 25, stage=MacroStage.FRAMING)]
        lag = stage_transition_lag(series, {MacroStage.FRAMING: series[0].window_start.date()})
        assert lag == 0.0

    def test_positive_lag_when_the_system_confirms_late(self) -> None:
        series = [
            _window(1, 15, 15, stage=MacroStage.FOUNDATION),
            _window(5, 25, 25, stage=MacroStage.FRAMING),
        ]
        # Framing genuinely started on day 2, system confirms on day 5.
        lag = stage_transition_lag(
            series, {MacroStage.FRAMING: datetime(2026, 1, 2, tzinfo=UTC).date()}
        )
        assert lag == 3.0

    def test_a_stage_never_reached_is_excluded_not_an_error(self) -> None:
        series = [_window(1, 15, 15, stage=MacroStage.FOUNDATION)]
        lag = stage_transition_lag(series, {MacroStage.APPROVAL: series[0].window_start.date()})
        assert lag is None


class TestEvaluateAgainstGroundTruth:
    def test_mae_of_a_perfect_match_is_zero(self) -> None:
        series = [_window(1, 20, 20), _window(2, 30, 30)]
        ground_truth = [
            GroundTruthPoint(day=series[0].window_start.date(), true_pct=20),
            GroundTruthPoint(day=series[1].window_start.date(), true_pct=30),
        ]
        evaluation = evaluate_against_ground_truth(series, ground_truth)
        assert evaluation.mae_pp == 0.0
        assert evaluation.n_points == 2

    def test_mae_reflects_a_known_gap(self) -> None:
        series = [_window(1, 20, 20)]
        ground_truth = [GroundTruthPoint(day=series[0].window_start.date(), true_pct=25)]
        evaluation = evaluate_against_ground_truth(series, ground_truth)
        assert evaluation.mae_pp == 5.0
        assert evaluation.max_error_pp == 5.0

    def test_a_ground_truth_day_with_no_matching_window_is_skipped(self) -> None:
        series = [_window(1, 20, 20)]
        ground_truth = [GroundTruthPoint(day=datetime(2099, 1, 1, tzinfo=UTC).date(), true_pct=99)]
        evaluation = evaluate_against_ground_truth(series, ground_truth)
        assert evaluation.n_points == 0
        assert evaluation.mae_pp == 0.0

    def test_bundles_monotonicity_and_jitter_alongside_mae(self) -> None:
        series = [_window(1, 10, 10), _window(2, 20, 20)]
        evaluation = evaluate_against_ground_truth(series, [])
        assert evaluation.monotonicity_violations == 0
        assert evaluation.raw_std >= 0.0
