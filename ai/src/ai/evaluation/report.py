"""Writes evaluation results to ``outputs/evaluation/<run_id>/`` as tables and figures.

**No number reaches this module by hand.** Every table is CSV/JSON, every
figure is a PNG rendered by this code from the same values in the table next
to it — never a chart pasted into the manuscript and then forgotten about.
That is the whole reason ``ai/evaluation/`` exists rather than a spreadsheet
(``Evaluation-Plan.md`` §8): the classifier *will* be retrained the week
before submission, and only a script-generated figure survives that.

Every run directory carries a manifest (git commit, seed, package versions,
timestamp) so a number in the thesis can always be traced back to the run
that produced it — "reproducible" here means literally re-runnable, not just
plausible.
"""

from __future__ import annotations

import csv
import json
import logging
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless: this runs on a server / CI runner, never a desktop
import matplotlib.pyplot as plt

from ai.evaluation.benchmark import BenchmarkResult, HardwareInfo
from ai.evaluation.detector_eval import AgreementReport, MAPReport
from ai.evaluation.metrics import ClassificationReport
from ai.evaluation.progress_eval import ProgressEvaluation
from ai.progress.aggregator import WindowResult

__all__ = [
    "BackboneComparisonRow",
    "RunManifest",
    "new_run_id",
    "run_output_dir",
    "write_agreement_report",
    "write_backbone_comparison",
    "write_classification_report",
    "write_manifest",
    "write_map_report",
    "write_progress_evaluation",
]

logger = logging.getLogger(__name__)

#: Where every evaluation run lands, matching `Repository-Structure.md`.
OUTPUTS_ROOT = Path("outputs") / "evaluation"


def new_run_id() -> str:
    """A sortable, collision-resistant run identifier: ``20260815T070000Z``."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_output_dir(run_id: str, *, root: Path = OUTPUTS_ROOT) -> Path:
    """Create (if needed) and return ``outputs/evaluation/<run_id>/``."""
    directory = root / run_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@dataclass(frozen=True, slots=True)
class RunManifest:
    """What produced this run, so it can be reproduced or at least explained."""

    run_id: str
    created_at: str
    git_commit: str | None
    seed: int | None
    hardware: HardwareInfo
    package_versions: dict[str, str] = field(default_factory=dict)
    notes: str = ""


def _git_commit() -> str | None:
    """Best-effort short commit hash. `None` outside a git checkout (e.g. a built image)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _package_versions(
    names: tuple[str, ...] = ("torch", "torchvision", "numpy", "scikit-learn"),
) -> dict[str, str]:
    """Versions of the libraries that most affect whether a number reproduces."""
    versions: dict[str, str] = {"python": platform.python_version()}
    for name in names:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def write_manifest(
    directory: Path,
    *,
    hardware: HardwareInfo,
    seed: int | None = None,
    notes: str = "",
) -> RunManifest:
    """Write ``manifest.json`` — the first file every run produces."""
    manifest = RunManifest(
        run_id=directory.name,
        created_at=datetime.now(UTC).isoformat(),
        git_commit=_git_commit(),
        seed=seed,
        hardware=hardware,
        package_versions=_package_versions(),
        notes=notes,
    )
    _write_json(directory / "manifest.json", asdict(manifest))
    return manifest


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Classifier report: table + confusion matrix + calibration diagram
# ---------------------------------------------------------------------------


def write_classification_report(directory: Path, report: ClassificationReport) -> Path:
    """Per-class table, confusion matrix heatmap, and reliability diagram.

    Returns the subdirectory everything was written into, so ``run_all.py``
    can log one path per section rather than a dozen.
    """
    out = directory / "classifier"
    out.mkdir(exist_ok=True)

    _write_json(
        out / "summary.json",
        {
            "n": report.n,
            "top1_accuracy": report.top1_accuracy,
            "top2_accuracy": report.top2_accuracy,
            "macro_f1": report.macro_f1,
            "mean_absolute_ordinal_error": report.mean_absolute_ordinal_error,
        },
    )
    _write_csv(
        out / "per_class_metrics.csv",
        [asdict(item) for item in report.per_class],
    )

    _plot_confusion_matrix(report, out / "confusion_matrix.png")
    if report.calibration is not None:
        _plot_reliability_diagram(report.calibration, out / "reliability_diagram.png")
        _write_json(out / "calibration.json", asdict(report.calibration))

    return out


def _plot_confusion_matrix(report: ClassificationReport, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, matrix, title, fmt in (
        (axes[0], report.confusion, "Confusion matrix (counts)", "d"),
        (axes[1], report.confusion_normalized, "Confusion matrix (row-normalized)", ".2f"),
    ):
        im = ax.imshow(matrix, cmap="Blues")
        ax.set_xticks(range(len(report.class_names)))
        ax.set_yticks(range(len(report.class_names)))
        ax.set_xticklabels(report.class_names, rotation=45, ha="right", fontsize=8)
        ax.set_yticklabels(report.class_names, fontsize=8)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("True")
        ax.set_title(title, fontsize=10)
        threshold = matrix.max() / 2 if matrix.size else 0
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                value = matrix[i, j]
                ax.text(
                    j,
                    i,
                    format(value, fmt),
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="white" if value > threshold else "black",
                )
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_reliability_diagram(calibration: Any, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ax.plot([0, 1], [0, 1], linestyle="--", color="#94a3b8", label="Perfect calibration")

    centers = [
        (lo + hi) / 2
        for lo, hi in zip(calibration.bin_edges[:-1], calibration.bin_edges[1:], strict=True)
    ]
    accuracy = [value if value == value else 0.0 for value in calibration.bin_accuracy]  # nan -> 0
    ax.bar(
        centers,
        accuracy,
        width=1.0 / calibration.n_bins,
        edgecolor="#1f5799",
        color="#87b6e2",
        alpha=0.85,
        label="Accuracy",
    )
    ax.set_xlabel("Confidence")
    ax.set_ylabel("Accuracy")
    ax.set_title(
        f"Reliability diagram (ECE={calibration.expected_calibration_error:.3f})", fontsize=10
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Backbone comparison: table + accuracy-vs-latency scatter
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BackboneComparisonRow:
    """One row of the backbone comparison table (`Evaluation-Plan.md` §2)."""

    model: str
    top1_accuracy: float | None
    macro_f1: float | None
    params: int | None
    size_mb: float | None
    cpu_ms: float | None
    gpu_ms: float | None
    epochs_to_best: int | None = None


def write_backbone_comparison(directory: Path, rows: list[BackboneComparisonRow]) -> Path:
    """The comparison table plus an accuracy-vs-CPU-latency scatter plot.

    The scatter is the figure that argues the deployment choice quantitatively
    rather than by assertion — it is drawn even with a single point (today,
    just the stub) so the plotting code is exercised long before there are
    four real rows to put on it.
    """
    out = directory / "backbone_comparison"
    out.mkdir(exist_ok=True)
    _write_csv(out / "comparison.csv", [asdict(row) for row in rows])

    plottable: list[tuple[str, float, float]] = [
        (row.model, row.cpu_ms, row.top1_accuracy)
        for row in rows
        if row.top1_accuracy is not None and row.cpu_ms is not None
    ]
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    if plottable:
        ax.scatter(
            [cpu_ms for _, cpu_ms, _ in plottable],
            [accuracy for _, _, accuracy in plottable],
            s=80,
            color="#1f5799",
        )
        for model, cpu_ms, accuracy in plottable:
            ax.annotate(
                model, (cpu_ms, accuracy), fontsize=8, xytext=(4, 4), textcoords="offset points"
            )
    else:
        ax.text(
            0.5,
            0.5,
            "No accuracy+latency pairs yet",
            ha="center",
            va="center",
            transform=ax.transAxes,
            color="#64748b",
        )
    ax.set_xlabel("CPU latency (ms/image)")
    ax.set_ylabel("Top-1 accuracy")
    ax.set_title("Accuracy vs. latency", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "accuracy_vs_latency.png", dpi=150)
    plt.close(fig)

    return out


def write_benchmark_table(directory: Path, results: list[BenchmarkResult]) -> Path:
    """Raw latency benchmark rows, independent of the comparison table above."""
    out = directory / "benchmarks"
    out.mkdir(exist_ok=True)
    _write_csv(out / "latency.csv", [asdict(item) for item in results])
    return out


# ---------------------------------------------------------------------------
# Detector: mAP + agreement
# ---------------------------------------------------------------------------


def write_map_report(directory: Path, report: MAPReport) -> Path:
    """mAP@0.5 / mAP@0.5:0.95 summary plus the per-class AP@0.5 table."""
    out = directory / "detector"
    out.mkdir(exist_ok=True)
    _write_json(out / "summary.json", {"map50": report.map50, "map50_95": report.map50_95})
    _write_csv(out / "per_class_ap50.csv", [asdict(item) for item in report.per_class_ap50])
    return out


def write_agreement_report(directory: Path, report: AgreementReport) -> Path:
    """Classifier-vs-detector agreement table (`Evaluation-Plan.md` §3)."""
    out = directory / "detector"
    out.mkdir(exist_ok=True)
    _write_json(
        out / "agreement.json",
        {
            "n_comparable": report.n_comparable,
            "n_total": report.n_total,
            "agreement_rate": report.agreement_rate,
        },
    )
    rows = [
        {"classifier_stage": classifier.value, "rule_stage": rule.value, "count": count}
        for classifier, by_rule in report.confusion.items()
        for rule, count in by_rule.items()
    ]
    _write_csv(out / "agreement_confusion.csv", rows)
    return out


# ---------------------------------------------------------------------------
# Progress algorithm: MAE + raw-vs-smoothed plot
# ---------------------------------------------------------------------------


def write_progress_evaluation(
    directory: Path, evaluation: ProgressEvaluation, results: list[WindowResult]
) -> Path:
    """The progress-algorithm results and the raw-vs-smoothed series figure.

    The figure is the empirical case for the EMA + ratchet
    (`Progress-Calculation.md` §8): plotting `raw_pct` and `displayed_pct` on
    the same axes over the same windows makes the smoothing visible in a way
    the MAE number alone does not.
    """
    out = directory / "progress"
    out.mkdir(exist_ok=True)
    _write_json(out / "summary.json", asdict(evaluation))

    _write_csv(
        out / "series.csv",
        [
            {
                "window_start": window.window_start.isoformat(),
                "raw_pct": window.raw_pct,
                "ema_pct": window.ema_pct,
                "displayed_pct": window.displayed_pct,
                "macro_stage": window.macro_stage.value,
                "regressed": window.regressed,
                "had_evidence": window.had_evidence,
            }
            for window in results
        ],
    )

    if results:
        fig, ax = plt.subplots(figsize=(7, 4))
        x = list(range(len(results)))
        ax.plot(
            x,
            [w.raw_pct for w in results],
            label="Raw",
            color="#94a3b8",
            linestyle="--",
            marker="o",
            markersize=3,
        )
        ax.plot(
            x,
            [w.displayed_pct for w in results],
            label="Displayed (smoothed)",
            color="#1f5799",
            linewidth=2,
        )
        ax.axhline(80.0, color="#b45309", linestyle=":", label="Machine ceiling")
        ax.set_xlabel("Window")
        ax.set_ylabel("Progress (%)")
        ax.set_title("Raw vs. smoothed progress", fontsize=10)
        ax.legend(fontsize=8)
        ax.set_ylim(0, 105)
        fig.tight_layout()
        fig.savefig(out / "raw_vs_smoothed.png", dpi=150)
        plt.close(fig)

    return out
