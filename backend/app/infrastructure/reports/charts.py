"""Matplotlib figures for the PDF, rendered to PNG bytes.

``matplotlib.use("Agg")`` is set **before** pyplot is imported anywhere in this
module's import chain. Without it matplotlib picks an interactive backend, which
on a headless worker either raises or — worse on a developer machine — tries to
open a window from inside a Celery task.

Every figure is closed explicitly. A long-running worker that leaks figures
climbs in memory until it is killed, and the symptom (a worker restarting every
few hours) looks nothing like its cause.
"""

from __future__ import annotations

import io
from datetime import date
from typing import TYPE_CHECKING, Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

if TYPE_CHECKING:
    from app.domain.reporting import ReportData

__all__ = ["capture_histogram", "progress_curve", "stage_bars"]

#: Muted, print-safe, and distinguishable in greyscale — a report gets printed.
_ACTUAL = "#1f4e79"
_EXPECTED = "#b0b7bf"
_BAR = "#2e7d32"
_ACCENT = "#8d6e63"

_STAGE_LABELS = ("Foundation", "Framing", "Roofing", "Finishing", "Approval")


def _axis(days: list[date]) -> Any:
    """Hand a date sequence to matplotlib.

    matplotlib plots dates on an axis natively and has done for years; its
    bundled stubs simply do not model it, so every call site would otherwise
    need its own ``type: ignore``. Widening once, here, keeps that stub gap
    documented in one place instead of four.
    """
    return days


def _render(figure: Figure) -> bytes:
    """Serialise a figure to PNG bytes and close it."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(figure)
    return buffer.getvalue()


def progress_curve(data: ReportData) -> bytes:
    """Displayed progress against the linear schedule, over the period.

    Gaps are plotted as gaps. Windows with no captures are simply absent from
    the snapshot series, and joining across them would draw a confident straight
    line through a fortnight in which nothing was measured.
    """
    figure, axes = plt.subplots(figsize=(7.2, 3.2))

    if data.snapshots:
        days = [snapshot.window_start.date() for snapshot in data.snapshots]
        actual = [snapshot.displayed_pct.as_float() for snapshot in data.snapshots]
        axes.plot(
            _axis(days),
            actual,
            marker="o",
            markersize=3.5,
            linewidth=1.8,
            color=_ACTUAL,
            label="AI estimate",
        )
        axes.plot(
            _axis([data.period.start, data.period.end]),
            [0.0, data.expected_pct],
            linestyle="--",
            linewidth=1.4,
            color=_EXPECTED,
            label="Expected (linear)",
        )
        axes.legend(frameon=False, fontsize=8, loc="upper left")
    else:
        axes.text(
            0.5,
            0.5,
            "No captures in this period",
            ha="center",
            va="center",
            fontsize=11,
            color="#777777",
            transform=axes.transAxes,
        )
        axes.set_xticks([])

    # The AI stops at 80 %; the last fifth is a human inspection (ADR-007).
    axes.axhline(80.0, color=_ACCENT, linewidth=1.0, linestyle=":")
    axes.text(
        0.995,
        81.0,
        "AI ceiling — inspection required above",
        transform=axes.get_yaxis_transform(),
        ha="right",
        fontsize=7,
        color=_ACCENT,
    )

    axes.set_ylim(0, 105)
    axes.set_ylabel("Progress (%)", fontsize=9)
    axes.grid(axis="y", alpha=0.25, linewidth=0.6)
    axes.spines[["top", "right"]].set_visible(False)
    axes.tick_params(labelsize=8)
    figure.autofmt_xdate(rotation=30)
    return _render(figure)


def stage_bars(data: ReportData) -> bytes:
    """The five stage bars at the end of the period."""
    figure, axes = plt.subplots(figsize=(7.2, 2.4))
    latest = data.snapshots[-1] if data.snapshots else None
    values = (
        [
            latest.foundation_pct,
            latest.framing_pct,
            latest.roofing_pct,
            latest.finishing_pct,
            latest.approval_pct,
        ]
        if latest
        else [0.0] * 5
    )

    # The fifth bar is visually distinct because it is not the same kind of
    # thing: four are measured by a model, the last is awarded by a person.
    colours = [_BAR] * 4 + [_ACCENT]
    bars = axes.barh(list(_STAGE_LABELS), values, color=colours, height=0.6)
    for bar, value in zip(bars, values, strict=True):
        axes.text(
            min(value + 1.5, 101),
            bar.get_y() + bar.get_height() / 2,
            f"{value:.0f}%",
            va="center",
            fontsize=8,
        )

    axes.set_xlim(0, 108)
    axes.invert_yaxis()
    axes.set_xlabel("Stage completion (%)", fontsize=9)
    axes.grid(axis="x", alpha=0.25, linewidth=0.6)
    axes.spines[["top", "right"]].set_visible(False)
    axes.tick_params(labelsize=8)
    return _render(figure)


def capture_histogram(data: ReportData) -> bytes:
    """Captures per day, split into accepted and gate-rejected.

    The rejected series is not decoration. A camera that suddenly produces
    nothing but rejects has been knocked, fogged, or obstructed, and the
    histogram is where that becomes visible before the progress curve goes flat.
    """
    figure, axes = plt.subplots(figsize=(7.2, 2.4))

    accepted: dict[date, int] = {}
    rejected: dict[date, int] = {}
    for row in data.captures:
        day = row.image.captured_at.date()
        bucket = rejected if row.was_rejected else accepted
        bucket[day] = bucket.get(day, 0) + 1

    days = sorted(set(accepted) | set(rejected))
    if days:
        axes.bar(
            _axis(days),
            [accepted.get(day, 0) for day in days],
            color=_ACTUAL,
            label="Accepted",
            width=0.7,
        )
        axes.bar(
            _axis(days),
            [rejected.get(day, 0) for day in days],
            bottom=[accepted.get(day, 0) for day in days],
            color=_EXPECTED,
            label="Rejected by quality gate",
            width=0.7,
        )
        axes.legend(frameon=False, fontsize=8)
    else:
        axes.text(
            0.5,
            0.5,
            "No captures in this period",
            ha="center",
            va="center",
            fontsize=11,
            color="#777777",
            transform=axes.transAxes,
        )
        axes.set_xticks([])

    axes.set_ylabel("Captures", fontsize=9)
    axes.grid(axis="y", alpha=0.25, linewidth=0.6)
    axes.spines[["top", "right"]].set_visible(False)
    axes.tick_params(labelsize=8)
    figure.autofmt_xdate(rotation=30)
    return _render(figure)
