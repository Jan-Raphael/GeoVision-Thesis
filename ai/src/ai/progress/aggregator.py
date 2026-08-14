"""Temporal aggregation — the core algorithm and the thesis contribution.

**Pure functions. No I/O, no ORM, no torch, ever.** That constraint is not
stylistic: this is the module that must be walked through line by line during
the defense, and every rule in it must be demonstrable from a table of numbers
rather than from a running system.

Why not simply report the model's latest output? Because a single frame is
noisy. A truck parked in front of the façade, a rainy afternoon, a low sun
angle, or scaffolding can each flip a class. A headline number that follows raw
predictions jitters and can move *backwards*, which destroys the one thing the
number needs: trust.

So progress is computed in four stages (``Progress-Calculation.md``):

1. **Per image** — nominal % for the predicted class (:mod:`ai.progress.estimator`).
2. **Per device, per window** — the **median** of that device's eligible images.
   Median, not mean: one bad frame cannot drag a camera's reading.
3. **Per project, per window** — a **weighted mean** across cameras. A
   ``front_diagonal`` camera sees two façades and is weighted 1.5 against a
   single-face view's 1.0.
4. **Across windows** — EMA smoothing, a stage-advance guard, and a monotonic
   ratchet that releases only on sustained evidence.

The ratchet is the interesting one. Construction genuinely can go backwards —
rework, typhoon damage — so a hard monotonic constraint would be a lie. But a
one-window dip is almost always occlusion or weather. So the displayed number
holds through a dip and releases after ``REGRESS_CONFIRMATIONS`` consecutive
lower windows, writing a remark when it does.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime

from ai.progress.constants import (
    ADVANCE_CONFIRMATIONS,
    ALGORITHM_VERSION,
    ALPHA,
    MACHINE_CEILING_PCT,
    REGRESS_CONFIRMATIONS,
)
from ai.progress.estimator import ImageProgress
from ai.progress.mapping import MacroStage, load_reference

__all__ = [
    "DeviceReading",
    "WindowInput",
    "WindowResult",
    "aggregate_window",
    "compute_series",
    "device_value",
    "macro_stage_for",
    "raw_project_value",
    "stage_percentages",
]


@dataclass(frozen=True, slots=True)
class DeviceReading:
    """One camera's value for one window."""

    device_id: str
    value_pct: float
    weight: float
    image_count: int


@dataclass(frozen=True, slots=True)
class WindowInput:
    """Everything one window contributes, before smoothing."""

    window_start: datetime
    window_end: datetime
    images: tuple[ImageProgress, ...] = ()
    #: Per-device aggregation weight. A device absent here is weighted 1.0.
    device_weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WindowResult:
    """The aggregated, smoothed, ratcheted result for one window.

    Maps one-to-one onto a ``project_progress_snapshots`` row.
    """

    window_start: datetime
    window_end: datetime
    raw_pct: float
    ema_pct: float
    displayed_pct: float
    macro_stage: MacroStage
    stage_pcts: dict[MacroStage, float]
    eligible_image_count: int
    contributing_image_ids: tuple[str, ...]
    device_weights: dict[str, float]
    #: True when the ratchet released and the number actually moved down. The
    #: caller writes a system remark; nothing else in here does I/O.
    regressed: bool = False
    #: True when this window is the first to reach the machine ceiling.
    reached_ceiling: bool = False
    #: False when no eligible image existed. The snapshot still exists (the
    #: timeline must show a gap, not a hole), but it carries forward rather than
    #: claiming new evidence.
    had_evidence: bool = True
    algorithm_version: str = ALGORITHM_VERSION


# ---------------------------------------------------------------------------
# Stage 2 — per device
# ---------------------------------------------------------------------------


def device_value(images: tuple[ImageProgress, ...]) -> float | None:
    """Median nominal progress across one device's eligible images.

    Returns ``None`` when the device produced no eligible image in the window.
    **Not zero.** A camera that saw nothing has no opinion; treating that as 0 %
    would drag the project average toward zero every time a lens fogged up, which
    is the opposite of what the evidence says.

    Median rather than mean so that one misclassified frame in five cannot move
    the reading — with an even count, ``statistics.median`` averages the middle
    two, which is the standard definition and keeps the result stable.
    """
    eligible = [image.raw_progress_pct for image in images if image.is_eligible]
    return statistics.median(eligible) if eligible else None


# ---------------------------------------------------------------------------
# Stage 3 — per project
# ---------------------------------------------------------------------------


def raw_project_value(readings: tuple[DeviceReading, ...]) -> float | None:
    """Weighted mean across the cameras that reported.

    ``sum(weight * value) / sum(weight)``. With equal weights this reduces to exactly
    the ``(Cam1 + Cam2) / 2`` in the original spec; the weights generalise it so a
    diagonal camera seeing two façades can count for more than a single-face view.

    Returns ``None`` when no camera reported.
    """
    contributing = [reading for reading in readings if reading.weight > 0]
    if not contributing:
        return None

    total_weight = sum(reading.weight for reading in contributing)
    if total_weight <= 0:
        return None
    return sum(r.weight * r.value_pct for r in contributing) / total_weight


def readings_for(window: WindowInput) -> tuple[DeviceReading, ...]:
    """Collapse a window's images into one reading per device."""
    by_device: dict[str, list[ImageProgress]] = {}
    for image in window.images:
        by_device.setdefault(image.device_id, []).append(image)

    readings: list[DeviceReading] = []
    for device_id, images in sorted(by_device.items()):
        value = device_value(tuple(images))
        if value is None:
            continue
        readings.append(
            DeviceReading(
                device_id=device_id,
                value_pct=value,
                weight=window.device_weights.get(device_id, 1.0),
                image_count=sum(1 for image in images if image.is_eligible),
            )
        )
    return tuple(readings)


# ---------------------------------------------------------------------------
# Stage 4 — across windows
# ---------------------------------------------------------------------------


def macro_stage_for(displayed_pct: float) -> MacroStage:
    """Which of the five bars a percentage falls in.

    Uses the bands from ``classes.yaml`` rather than hard-coded numbers, and
    treats each band as ``floor <= x < ceiling`` with the top band closed, so
    exactly 20.0 reads as Framing rather than Foundation — the boundary belongs
    to the stage being entered.
    """
    bands = _stage_bands()
    for stage in (
        MacroStage.APPROVAL,
        MacroStage.FINISHING,
        MacroStage.ROOFING,
        MacroStage.FRAMING,
    ):
        if displayed_pct >= bands[stage][0]:
            return stage
    return MacroStage.FOUNDATION


def stage_percentages(displayed_pct: float) -> dict[MacroStage, float]:
    """Per-stage completion for the five bars.

    ``clamp((displayed - floor) / (ceiling - floor) * 100, 0, 100)`` — so a
    project at 47 % shows Foundation 100, Framing 100, Roofing 35, Finishing 0,
    Approval 0.
    """
    result: dict[MacroStage, float] = {}
    for stage, (floor, ceiling) in _stage_bands().items():
        span = ceiling - floor
        fraction = 0.0 if span <= 0 else (displayed_pct - floor) / span * 100.0
        result[stage] = round(min(max(fraction, 0.0), 100.0), 2)
    return result


def aggregate_window(
    window: WindowInput,
    previous: WindowResult | None = None,
    *,
    history: tuple[WindowResult, ...] = (),
    alpha: float = ALPHA,
    advance_confirmations: int = ADVANCE_CONFIRMATIONS,
    regress_confirmations: int = REGRESS_CONFIRMATIONS,
    ceiling_pct: float = MACHINE_CEILING_PCT,
) -> WindowResult:
    """Aggregate one window, smoothing against what came before.

    Args:
        window: This window's images and device weights.
        previous: The immediately preceding result, or ``None`` for the first
            window (the EMA seeds itself from the raw value).
        history: Earlier results, oldest first, used only to count consecutive
            regressions. ``previous`` need not be repeated here.
        alpha: EMA weight on the newest window.
        advance_confirmations: Consecutive windows before the macro stage may
            advance.
        regress_confirmations: Consecutive lower windows before the ratchet
            releases.
        ceiling_pct: The machine ceiling (ADR-007).

    Returns:
        The window's snapshot values.
    """
    readings = readings_for(window)
    raw = raw_project_value(readings)

    eligible = tuple(image for image in window.images if image.is_eligible)
    had_evidence = raw is not None

    if raw is None:
        # An empty window still produces a snapshot: the timeline must show a
        # flat stretch where captures stopped, not a missing point that a chart
        # would interpolate straight through and imply data nobody collected.
        if previous is None:
            return _empty_first_window(window, ceiling_pct)
        raw = previous.raw_pct
        ema = previous.ema_pct
    else:
        ema = raw if previous is None else alpha * raw + (1 - alpha) * previous.ema_pct

    ema = min(ema, ceiling_pct)

    displayed, regressed = _apply_ratchet(
        ema=ema,
        previous=previous,
        history=history,
        regress_confirmations=regress_confirmations,
        had_evidence=had_evidence,
    )
    displayed = min(displayed, ceiling_pct)

    stage = _guarded_stage(
        displayed=displayed,
        previous=previous,
        history=history,
        advance_confirmations=advance_confirmations,
    )

    return WindowResult(
        window_start=window.window_start,
        window_end=window.window_end,
        raw_pct=round(raw, 4),
        ema_pct=round(ema, 4),
        displayed_pct=round(displayed, 4),
        macro_stage=stage,
        stage_pcts=stage_percentages(displayed),
        eligible_image_count=len(eligible),
        contributing_image_ids=tuple(image.image_id for image in eligible),
        device_weights={r.device_id: r.weight for r in readings},
        regressed=regressed,
        reached_ceiling=(
            displayed >= ceiling_pct and (previous is None or previous.displayed_pct < ceiling_pct)
        ),
        had_evidence=had_evidence,
    )


def compute_series(
    windows: tuple[WindowInput, ...],
    **options: float | int,
) -> tuple[WindowResult, ...]:
    """Aggregate a whole timeline from scratch, oldest window first.

    This is what makes recomputation **replayable**. Snapshots are always
    rebuilt from stored predictions rather than patched incrementally, so wiping
    the snapshot table and recomputing reproduces the timeline exactly — which is
    the only way an algorithm change can be applied to history honestly.
    """
    results: list[WindowResult] = []
    for window in sorted(windows, key=lambda item: item.window_start):
        results.append(
            aggregate_window(
                window,
                previous=results[-1] if results else None,
                history=tuple(results[:-1]),
                **options,  # type: ignore[arg-type]
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _apply_ratchet(
    *,
    ema: float,
    previous: WindowResult | None,
    history: tuple[WindowResult, ...],
    regress_confirmations: int,
    had_evidence: bool,
) -> tuple[float, bool]:
    """Hold the displayed number through a dip; release on sustained evidence.

    Returns ``(displayed_pct, regressed)``.

    While holding, this is exactly the spec's
    ``displayed(w) = max(displayed(w-1), ema(w))`` — the number still rises
    freely, it simply refuses to fall. Once the decline is confirmed the number
    tracks the EMA down and **keeps** tracking it: a regression that continues is
    one event, not a fresh one each window. Re-arming the ratchet after every
    release would make a genuine multi-week decline descend in visible stair
    steps and raise a remark on each one.
    """
    if previous is None:
        return ema, False

    run = _declining_run(ema=ema, previous=previous, history=history, had_evidence=had_evidence)

    if run >= regress_confirmations:
        # `regressed` marks only the window where the ratchet let go, so the
        # caller writes one system remark rather than one per window for as long
        # as the decline lasts.
        return ema, run == regress_confirmations

    return max(previous.displayed_pct, ema), False


def _declining_run(
    *,
    ema: float,
    previous: WindowResult,
    history: tuple[WindowResult, ...],
    had_evidence: bool,
) -> int:
    """How many consecutive windows the smoothed value has now fallen for.

    Measured on the **EMA**, not on the displayed value: the displayed value is
    what the ratchet is holding, so comparing against it would make the ratchet
    interrogate its own output and stop counting the moment it released.

    A window with no evidence interrupts the run rather than extending it. A
    camera going offline is not the building being demolished, and the
    conservative reading — harder to regress, never easier — is the right one for
    a number people act on.
    """
    if not had_evidence or ema >= previous.ema_pct:
        return 0

    run = 1
    chain = (*history, previous)
    for index in range(len(chain) - 1, 0, -1):
        later, earlier = chain[index], chain[index - 1]
        if later.had_evidence and later.ema_pct < earlier.ema_pct:
            run += 1
        else:
            break
    return run


def _guarded_stage(
    *,
    displayed: float,
    previous: WindowResult | None,
    history: tuple[WindowResult, ...],
    advance_confirmations: int,
) -> MacroStage:
    """Advance the macro stage only after repeated agreement.

    A single good day should not move a project from Framing to Roofing on the
    dashboard. The *number* may rise immediately — that is the EMA's job — but
    the stage label, which is what people read at a glance, waits for
    confirmation.
    """
    candidate = macro_stage_for(displayed)
    if previous is None:
        return candidate

    order = list(MacroStage)
    if order.index(candidate) <= order.index(previous.macro_stage):
        # Never guarded downward: the ratchet already governs falling, and
        # double-guarding would strand the label above a number that has
        # genuinely and repeatedly dropped.
        return candidate

    confirmations = 1
    for earlier in reversed((*history, previous)):
        if macro_stage_for(earlier.displayed_pct) == candidate:
            confirmations += 1
        else:
            break

    return candidate if confirmations >= advance_confirmations else previous.macro_stage


def _empty_first_window(window: WindowInput, ceiling_pct: float) -> WindowResult:
    """A first window with nothing eligible in it."""
    _ = ceiling_pct
    return WindowResult(
        window_start=window.window_start,
        window_end=window.window_end,
        raw_pct=0.0,
        ema_pct=0.0,
        displayed_pct=0.0,
        macro_stage=MacroStage.FOUNDATION,
        stage_pcts=stage_percentages(0.0),
        eligible_image_count=0,
        contributing_image_ids=(),
        device_weights={},
        had_evidence=False,
    )


def _stage_bands() -> dict[MacroStage, tuple[float, float]]:
    """Stage bands, derived from the canonical class table."""
    bands: dict[MacroStage, tuple[float, float]] = {}
    for reference in load_reference():
        bands[reference.macro_stage] = (
            reference.stage_floor_pct,
            reference.stage_ceiling_pct,
        )
    return bands
