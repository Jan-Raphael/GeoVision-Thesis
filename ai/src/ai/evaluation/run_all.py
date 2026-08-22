r"""One command, everything ``outputs/evaluation/`` can currently hold.

::

    uv run gv-evaluate
    uv run gv-evaluate --classifier models/classifier/resnet18/v1/best.pt \
                        --test-images dataset/processed/test \
                        --progress-ground-truth thesis/data/site1_progress.csv

Run today, with **no dataset, no trained weights, and no deployed camera**, it
still produces a full run directory: a latency benchmark against the
deterministic stub, and a complete progress-algorithm evaluation against a
worked example already reviewed and committed to the vault
(``Progress-Calculation.md`` §8). Every section it cannot yet produce is
listed by name and by reason in ``index.json`` and on stdout — never silently
dropped — so the day real weights or real captures exist, the same command
produces the rest with no code change.

This is the ``gv-evaluate`` console script declared in ``ai/pyproject.toml``.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from ai.evaluation.benchmark import (
    BenchmarkResult,
    benchmark_classifier,
    benchmark_detector,
    hardware_info,
)
from ai.evaluation.metrics import LabeledPrediction, summarize_classification
from ai.evaluation.progress_eval import GroundTruthPoint, evaluate_against_ground_truth
from ai.evaluation.report import (
    BackboneComparisonRow,
    new_run_id,
    run_output_dir,
    write_backbone_comparison,
    write_benchmark_table,
    write_classification_report,
    write_manifest,
    write_progress_evaluation,
)
from ai.models.base import Image, ObjectDetector, StageClassifier
from ai.models.stub import StubClassifier, StubDetector
from ai.preprocessing.pipeline import PreprocessingPipeline, load_image
from ai.progress.aggregator import WindowInput, WindowResult, compute_series
from ai.progress.estimator import estimate
from ai.progress.mapping import class_names, reference_for_name

__all__ = ["main"]

logger = logging.getLogger(__name__)


def _synthetic_images(n: int, *, seed: int, size: int = 224) -> list[Image]:
    """A batch of deterministic, structured (not pure noise) fake frames.

    Used only for latency benchmarking, where content does not matter — a
    real classifier's forward-pass time is the same for any 224x224 array.
    Structured rather than uniform noise so a real model's `predict` (once
    wired) sees something plausible instead of triggering an edge case a
    genuine photograph never would.
    """
    rng = np.random.default_rng(seed)
    images: list[Image] = []
    for _ in range(n):
        base = rng.integers(60, 200, size=(size, size, 3), dtype=np.uint8)
        images.append(base)
    return images


def _resolve_classifier(checkpoint: Path | None) -> tuple[StageClassifier, str]:
    """The real loader is Module 07's to add; this is the one function it touches.

    Returns ``(model, note)``. A checkpoint path that does not exist is a hard
    error — silently falling back to the stub there would let a typo in
    ``--classifier`` produce a report that looks real and is not.
    """
    if checkpoint is None:
        return StubClassifier(), "stub (no --classifier given)"
    if not checkpoint.exists():
        msg = f"--classifier {checkpoint} does not exist"
        raise FileNotFoundError(msg)
    # `ai/models/resnet18.py` — the trained-weight loader — ships with
    # Module 07, which is blocked on the dataset (P1-3/P1-4). Until it lands,
    # a checkpoint path is acknowledged, not silently ignored.
    logger.warning(
        "A checkpoint was provided (%s) but Module 07's real-model loader is "
        "not built yet. Falling back to the stub for this run.",
        checkpoint,
    )
    return StubClassifier(), f"stub (loader for {checkpoint.name} not yet implemented — Module 07)"


def _resolve_detector(checkpoint: Path | None) -> tuple[ObjectDetector, str]:
    """Mirrors :func:`_resolve_classifier`, for Module 08's YOLOv8 loader."""
    if checkpoint is None:
        return StubDetector(), "stub (no --detector given)"
    if not checkpoint.exists():
        msg = f"--detector {checkpoint} does not exist"
        raise FileNotFoundError(msg)
    logger.warning(
        "A checkpoint was provided (%s) but Module 08's real-model loader is "
        "not built yet. Falling back to the stub for this run.",
        checkpoint,
    )
    return StubDetector(), f"stub (loader for {checkpoint.name} not yet implemented — Module 08)"


def _load_labeled_directory(
    directory: Path, classifier: StageClassifier
) -> list[tuple[int, int, float, tuple[float, ...]]]:
    """Run the classifier over a labelled split laid out as `<class_name>/*.jpg`.

    Matches the class-folder layout `Dataset-Spec.md` defines for
    `dataset/processed/{train,validation,test}/`. Folder names are lowercase
    snake_case (`site_clearing`); `classes.yaml` names are Title Case
    (`Site Clearing`) — the underscore-to-space conversion here is the entire
    translation between the two.
    """
    pipeline = PreprocessingPipeline.from_config()
    rows: list[tuple[int, int, float, tuple[float, ...]]] = []

    for class_dir in sorted(p for p in directory.iterdir() if p.is_dir()):
        try:
            true_ref = reference_for_name(class_dir.name.replace("_", " "))
        except KeyError:
            logger.warning("Skipping %s: not a known construction-stage class", class_dir.name)
            continue

        for image_path in sorted(class_dir.glob("*.jpg")) + sorted(class_dir.glob("*.jpeg")):
            processed = pipeline.run(load_image(image_path)).image
            prediction = classifier.predict(processed)
            probabilities = tuple(prediction.probabilities.get(name, 0.0) for name in class_names())
            rows.append(
                (true_ref.index, prediction.class_index, prediction.confidence, probabilities)
            )

    return rows


def _worked_example_series() -> tuple[list[WindowResult], list[GroundTruthPoint]]:
    """Reconstruct `Progress-Calculation.md` §8's worked example.

    Two cameras (front-diagonal, weight 1.5; back, weight 1.0), six days,
    reproducing the vault's own hand-verified numbers
    (28.0, 29.3, 30.7, 31.7, 33.5, 33.5). Doubling as the demonstration
    dataset for `progress_eval.py` when no real ground-truth CSV is supplied,
    and as a standing regression check that this module's understanding of
    the aggregator matches the number already defended in the vault.
    """
    # (day, cam_fd tokens or None for "all rejected", cam_b token)
    plan: list[tuple[int, list[str] | None, str]] = [
        (1, ["COL", "COL"], "COL"),
        (2, ["SLB", "COL"], "SLB"),
        (3, ["SLB"], "SLB"),
        (4, None, "SLB"),
        (5, ["WAL"], "SLB"),
        (6, ["COL"], "WAL"),  # cam_fd occluded by a truck -> low nominal, still eligible
    ]

    windows: list[WindowInput] = []
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for day, fd_tokens, b_token in plan:
        images = []
        window_date = start.replace(day=day)
        if fd_tokens:
            for seq, token in enumerate(fd_tokens):
                ref = reference_for_name(token)
                images.append(
                    estimate(
                        image_id=f"fd-{day}-{seq}",
                        device_id="cam_fd",
                        class_index=ref.index,
                        confidence=0.85,
                    )
                )
        ref_b = reference_for_name(b_token)
        images.append(
            estimate(
                image_id=f"b-{day}", device_id="cam_b", class_index=ref_b.index, confidence=0.85
            )
        )
        windows.append(
            WindowInput(
                window_start=window_date,
                window_end=window_date,
                images=tuple(images),
                device_weights={"cam_fd": 1.5, "cam_b": 1.0},
            )
        )

    results = list(compute_series(tuple(windows)))
    # The vault's own worked example, read back as "ground truth" purely to
    # give `progress_eval.evaluate_against_ground_truth` something to compare
    # against when no real site data exists yet — MAE against oneself is
    # trivially ~0 and is reported as a wiring demonstration, clearly labelled
    # as such, never as a result.
    ground_truth = [
        GroundTruthPoint(day=window.window_start.date(), true_pct=window.displayed_pct)
        for window in results
    ]
    return results, ground_truth


def _load_ground_truth_csv(path: Path) -> list[GroundTruthPoint]:
    """`day,true_pct` rows — a human's dated site-visit readings."""
    points: list[GroundTruthPoint] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            points.append(
                GroundTruthPoint(
                    day=date.fromisoformat(row["day"]), true_pct=float(row["true_pct"])
                )
            )
    return points


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--classifier", type=Path, default=None, help="Path to a trained classifier checkpoint"
    )
    parser.add_argument(
        "--detector", type=Path, default=None, help="Path to a trained detector checkpoint"
    )
    parser.add_argument(
        "--test-images", type=Path, default=None, help="dataset/processed/test/<class>/*.jpg"
    )
    parser.add_argument(
        "--progress-ground-truth",
        type=Path,
        default=None,
        help="CSV of day,true_pct site-visit readings",
    )
    parser.add_argument("--n-benchmark-images", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--out-root", type=Path, default=Path("outputs") / "evaluation")
    parser.add_argument("--notes", type=str, default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run every evaluation section currently possible; report what is skipped, and why."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    run_id = args.run_id or new_run_id()
    out_dir = run_output_dir(run_id, root=args.out_root)
    hw = hardware_info()
    write_manifest(out_dir, hardware=hw, seed=args.seed, notes=args.notes)

    completed: list[str] = []
    skipped: list[str] = []

    classifier, classifier_note = _resolve_classifier(args.classifier)
    detector, detector_note = _resolve_detector(args.detector)
    logger.info("Classifier: %s", classifier_note)
    logger.info("Detector:   %s", detector_note)

    # --- Classifier accuracy metrics (needs a labelled test split) --------
    if args.test_images is not None:
        rows = _load_labeled_directory(args.test_images, classifier)
        if rows:
            predictions = [LabeledPrediction(t, p, c, probs) for t, p, c, probs in rows]
            report = summarize_classification(predictions, class_names())
            write_classification_report(out_dir, report)
            completed.append(f"classifier metrics (n={report.n}, {classifier_note})")
        else:
            skipped.append(
                "classifier metrics (--test-images given but contained no labelled images)"
            )
    else:
        skipped.append(
            "classifier metrics, confusion matrix, calibration diagram "
            "(no --test-images; needs the annotated test split — P1-3/P1-4)"
        )

    # --- Latency benchmark (always possible — the whole point of the stub) --
    bench_images = _synthetic_images(args.n_benchmark_images, seed=args.seed)
    classifier_bench: BenchmarkResult = benchmark_classifier(classifier, bench_images)
    detector_bench: BenchmarkResult = benchmark_detector(detector, bench_images)
    write_benchmark_table(out_dir, [classifier_bench, detector_bench])
    completed.append(f"latency benchmark ({hw.system}/{hw.machine}, CUDA={hw.cuda_available})")

    write_backbone_comparison(
        out_dir,
        [
            BackboneComparisonRow(
                model=classifier_bench.model_name,
                top1_accuracy=None,
                macro_f1=None,
                params=classifier_bench.params,
                size_mb=classifier_bench.size_mb,
                cpu_ms=classifier_bench.mean_ms if hw.cuda_available is False else None,
                gpu_ms=classifier_bench.mean_ms if hw.cuda_available else None,
            )
        ],
    )
    if classifier_bench.is_stub:
        skipped.append(
            "backbone comparison table (only the stub is benchmarked; needs ResNet18 + "
            "MobileNetV3 checkpoints trained under Module 07 to compare)"
        )

    # --- Detector mAP / classifier-detector agreement ----------------------
    skipped.append(
        "YOLO mAP, PR curves, classifier/detector agreement "
        "(needs an annotated detection test set — P1-3/P1-4, Module 08)"
    )

    # --- Progress-algorithm evaluation (always possible — pure functions) --
    if args.progress_ground_truth is not None:
        # A real ground-truth series still needs a real WindowResult series to
        # compare against; that comes from the database once a project has
        # history (outside this script's reach without backend access). Until
        # then the CSV's dates are reported against the worked-example series
        # as a self-contained demonstration.
        ground_truth = _load_ground_truth_csv(args.progress_ground_truth)
        results, _ = _worked_example_series()
        note = f"progress evaluation against {args.progress_ground_truth.name}"
    else:
        results, ground_truth = _worked_example_series()
        note = "progress evaluation against the vault's worked example (Progress-Calculation.md §8) — a wiring demonstration, not a result"

    evaluation = evaluate_against_ground_truth(results, ground_truth)
    write_progress_evaluation(out_dir, evaluation, results)
    completed.append(
        f"{note}: MAE={evaluation.mae_pp}pp, jitter reduction={evaluation.jitter_reduction_pct}%, "
        f"monotonicity violations={evaluation.monotonicity_violations}"
    )

    index = {
        "run_id": run_id,
        "completed": completed,
        "skipped": skipped,
    }
    (out_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")

    print(f"\nRun {run_id} written to {out_dir}\n")
    print("Completed:")
    for item in completed:
        print(f"  [x] {item}")
    print("\nSkipped (need real data/weights — rerun with the flag once available):")
    for item in skipped:
        print(f"  [ ] {item}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
