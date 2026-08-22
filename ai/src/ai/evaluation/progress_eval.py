"""Evaluating the progress algorithm itself, not a model.

``ai/progress/aggregator.py`` is the thesis's core contribution
(``Progress-Calculation.md``), and it earns its own evaluation chapter
separate from the classifier's (``Evaluation-Plan.md`` §5): does the smoothed,
ratcheted number the system displays actually track reality, and — the whole
point of the EMA and the ratchet — is it materially less jittery than the raw
per-window value it is built from?

Every function here operates on :class:`~ai.progress.aggregator.WindowResult`,
which :func:`~ai.progress.aggregator.compute_series` produces with **no
model, no database, and no I/O involved.** That means this whole module is
exercisable today against a hand-built or synthetic sequence of windows, and
tomorrow against a real project's stored snapshots — the aggregator does not
change, only where the ``WindowResult`` sequence comes from.
"""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from ai.progress.aggregator import WindowResult
from ai.progress.mapping import MacroStage

__all__ = [
    "GroundTruthPoint",
    "ProgressEvaluation",
    "evaluate_against_ground_truth",
    "jitter_reduction",
    "monotonicity_violations",
    "stage_transition_lag",
]


@dataclass(frozen=True, slots=True)
class GroundTruthPoint:
    """One manually-verified progress reading for a real site.

    Produced by a human — a site visit, a set of dated photographs reviewed by
    the thesis author, or (once P1-5 is resolved) a civil engineer's estimate —
    never by the system itself. Comparing the system against its own output
    would not be an evaluation.
    """

    day: date
    true_pct: float


@dataclass(frozen=True, slots=True)
class ProgressEvaluation:
    """Everything :func:`evaluate_against_ground_truth` reports."""

    n_points: int
    mae_pp: float
    max_error_pp: float
    #: `None` until at least one true stage transition date is supplied.
    mean_stage_transition_lag_days: float | None
    monotonicity_violations: int
    raw_std: float
    displayed_std: float
    jitter_reduction_pct: float


def monotonicity_violations(results: Sequence[WindowResult]) -> int:
    """Count of backward moves the ratchet did **not** sanction.

    By construction, ``displayed_pct`` may only fall on a window where
    ``regressed=True`` — the ratchet's whole job is to forbid any other kind
    of drop (``Progress-Calculation.md`` §4). Target is exactly **0**; a
    non-zero result here is not a modelling limitation to report in the
    thesis, it is a bug in the aggregator, because the algorithm's own
    contract guarantees this never happens. Kept as a callable check (rather
    than trusted as an invariant) so real data — which will exercise code
    paths a hand-written unit test might not think to — verifies it too.
    """
    violations = 0
    for previous, current in itertools.pairwise(results):
        if current.displayed_pct < previous.displayed_pct and not current.regressed:
            violations += 1
    return violations


def jitter_reduction(results: Sequence[WindowResult]) -> tuple[float, float, float]:
    """Standard deviation of the raw series vs. the displayed series.

    Returns ``(raw_std, displayed_std, reduction_pct)``. This is the direct
    empirical case for the EMA + ratchet: if smoothing is doing its job,
    ``displayed_std`` should be visibly smaller than ``raw_std`` over the same
    window-to-window deltas — the reduction is computed on the **first
    difference** of each series (window-over-window change), because the
    series themselves trend upward over a project's life and comparing their
    raw standard deviations would mostly measure that trend, not noise.
    """
    if len(results) < 2:
        return (0.0, 0.0, 0.0)

    raw_deltas = [b.raw_pct - a.raw_pct for a, b in itertools.pairwise(results)]
    displayed_deltas = [b.displayed_pct - a.displayed_pct for a, b in itertools.pairwise(results)]

    raw_std = statistics.pstdev(raw_deltas)
    displayed_std = statistics.pstdev(displayed_deltas)
    reduction = (1 - displayed_std / raw_std) * 100 if raw_std > 0 else 0.0
    return (round(raw_std, 4), round(displayed_std, 4), round(reduction, 2))


def stage_transition_lag(
    results: Sequence[WindowResult], true_transitions: dict[MacroStage, date]
) -> float | None:
    """Mean days between a *true* stage change and the system's confirmed label.

    Args:
        results: The window series, oldest first.
        true_transitions: Ground truth date each macro stage was actually
            reached on site, from a human observation.

    Target is **≤ 3 days** (``Evaluation-Plan.md`` §5) — the stage-advance
    guard trades a small, bounded lag for immunity to a one-day fluke, and
    this is what turns "the guard adds a delay" from an assumption into a
    measured number.
    """
    lags: list[float] = []
    for stage, true_date in true_transitions.items():
        confirmed = next((window for window in results if window.macro_stage == stage), None)
        if confirmed is None:
            continue
        lags.append((confirmed.window_start.date() - true_date).days)

    return round(statistics.mean(lags), 2) if lags else None


def evaluate_against_ground_truth(
    results: Sequence[WindowResult],
    ground_truth: Sequence[GroundTruthPoint],
    *,
    true_transitions: dict[MacroStage, date] | None = None,
) -> ProgressEvaluation:
    """Run the full progress-algorithm evaluation in one call.

    Ground-truth points are matched to the window whose ``window_start`` falls
    on the same calendar day; a ground-truth day with no matching window is
    silently skipped rather than raising, since a manual walkthrough will
    rarely land on exactly the days the camera captured.
    """
    by_day = {window.window_start.date(): window for window in results}
    errors: list[float] = []
    for point in ground_truth:
        window = by_day.get(point.day)
        if window is not None:
            errors.append(abs(window.displayed_pct - point.true_pct))

    raw_std, displayed_std, reduction = jitter_reduction(results)

    return ProgressEvaluation(
        n_points=len(errors),
        mae_pp=round(statistics.mean(errors), 2) if errors else 0.0,
        max_error_pp=round(max(errors), 2) if errors else 0.0,
        mean_stage_transition_lag_days=(
            stage_transition_lag(results, true_transitions) if true_transitions else None
        ),
        monotonicity_violations=monotonicity_violations(results),
        raw_std=raw_std,
        displayed_std=displayed_std,
        jitter_reduction_pct=reduction,
    )
