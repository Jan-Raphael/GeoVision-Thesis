"""Classifier metrics: accuracy, per-class P/R/F1, ordinal error, calibration.

Every function here takes plain arrays of integer class indices and floats —
never a torch tensor, never a model. That is deliberate: it is what lets this
whole module be written, tested, and trusted **before a single epoch of
training has happened**, against the deterministic :class:`~ai.models.stub.
StubClassifier` today and against a real ResNet18's output tomorrow, with zero
code changes on either side of the boundary (``Evaluation-Plan.md`` §1).

The classes are an **ordered construction sequence**
(``Construction-Stages.md``), which is why ``mean_absolute_ordinal_error`` and
top-2 accuracy sit next to plain accuracy: confusing *Columns* with *Slab* is a
materially smaller mistake than confusing *Excavation* with *Roof*, and a
metric that cannot tell those apart is hiding the shape of the model's errors.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "CalibrationReport",
    "ClassMetrics",
    "ClassificationReport",
    "LabeledPrediction",
    "calibration_report",
    "confusion_matrix",
    "mean_absolute_ordinal_error",
    "per_class_metrics",
    "summarize_classification",
    "top1_accuracy",
    "topk_accuracy",
]


@dataclass(frozen=True, slots=True)
class LabeledPrediction:
    """One test-set image's ground truth against what the model said.

    The unit :func:`summarize_classification` and every metric in this module
    consumes — a real evaluation run builds a list of these from the labelled
    test split; a unit test builds a handful by hand.
    """

    true_index: int
    pred_index: int
    confidence: float
    #: Full softmax distribution in class-index order, for top-k and
    #: calibration. Optional: a caller that only has the argmax can omit it and
    #: still get everything except :func:`topk_accuracy`.
    probabilities: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    """Precision / recall / F1 / support for one class."""

    class_index: int
    class_name: str
    precision: float
    recall: float
    f1: float
    support: int


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Reliability-diagram data and the single-number summary (ECE).

    Bins predictions by confidence into ``n_bins`` equal-width buckets and
    compares each bucket's mean confidence against its actual accuracy — a
    well-calibrated model's points sit on the diagonal. This is the empirical
    justification for ``MIN_CONFIDENCE = 0.60`` (``Progress-Calculation.md``
    §9): it shows where the gate actually separates trustworthy predictions
    from coin flips, rather than asserting the threshold by feel.
    """

    n_bins: int
    #: Bin edges, length ``n_bins + 1``.
    bin_edges: tuple[float, ...]
    #: Mean confidence per bin. ``nan`` for an empty bin.
    bin_confidence: tuple[float, ...]
    #: Actual accuracy per bin. ``nan`` for an empty bin.
    bin_accuracy: tuple[float, ...]
    #: Fraction of all predictions falling in each bin.
    bin_weight: tuple[float, ...]
    #: Expected Calibration Error: the weighted mean gap between confidence and
    #: accuracy across bins. 0 is perfect; the stub, which is not a real model,
    #: is expected to score poorly here — that is a sanity check, not a result.
    expected_calibration_error: float


@dataclass(frozen=True, slots=True)
class ClassificationReport:
    """Bundle of everything :func:`summarize_classification` produces.

    What :mod:`ai.evaluation.report` writes out as a table.
    """

    n: int
    top1_accuracy: float
    top2_accuracy: float | None
    macro_f1: float
    mean_absolute_ordinal_error: float
    per_class: tuple[ClassMetrics, ...]
    confusion: NDArray[np.int64]
    confusion_normalized: NDArray[np.float64]
    calibration: CalibrationReport | None
    class_names: tuple[str, ...] = field(default_factory=tuple)


def confusion_matrix(
    predictions: Sequence[LabeledPrediction], num_classes: int
) -> NDArray[np.int64]:
    """Row = true class, column = predicted class — the standard orientation.

    Deliberately hand-rolled rather than pulled from scikit-learn's
    ``confusion_matrix``: this project already depends on scikit-learn for the
    dataset split (``StratifiedGroupKFold``), but a 10x10 count matrix is eight
    lines of numpy, and keeping the metrics module's only dependency as numpy
    means it never needs to change when the split strategy does.
    """
    matrix = np.zeros((num_classes, num_classes), dtype=np.int64)
    for item in predictions:
        matrix[item.true_index, item.pred_index] += 1
    return matrix


def per_class_metrics(
    matrix: NDArray[np.int64], class_names: Sequence[str]
) -> tuple[ClassMetrics, ...]:
    """Precision, recall, F1, and support, read directly off the confusion matrix.

    ``precision = TP / predicted_positive``, ``recall = TP / actual_positive``,
    both defined as 0 (not NaN) when their denominator is 0 — a class the model
    never predicts has 0 % precision by convention, not an undefined one, so it
    still sorts and averages sensibly.
    """
    results: list[ClassMetrics] = []
    for index, name in enumerate(class_names):
        tp = int(matrix[index, index])
        predicted_positive = int(matrix[:, index].sum())
        actual_positive = int(matrix[index, :].sum())

        precision = tp / predicted_positive if predicted_positive else 0.0
        recall = tp / actual_positive if actual_positive else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        results.append(
            ClassMetrics(
                class_index=index,
                class_name=name,
                precision=round(precision, 4),
                recall=round(recall, 4),
                f1=round(f1, 4),
                support=actual_positive,
            )
        )
    return tuple(results)


def top1_accuracy(predictions: Sequence[LabeledPrediction]) -> float:
    """Fraction of predictions whose argmax matches the true class."""
    if not predictions:
        return 0.0
    correct = sum(1 for item in predictions if item.pred_index == item.true_index)
    return round(correct / len(predictions), 4)


def topk_accuracy(predictions: Sequence[LabeledPrediction], k: int = 2) -> float | None:
    """Fraction where the true class is among the top ``k`` by probability.

    Top-2 in particular reports how often an *adjacent-stage* confusion — the
    likeliest kind, since the classes are ordinally close — would have been
    caught by a second-best guess. Returns ``None`` when no prediction carries
    a probability distribution, rather than silently scoring against argmax
    alone, which would make top-2 identical to top-1 and hide that the caller
    forgot to pass probabilities.
    """
    scored = [item for item in predictions if item.probabilities]
    if not scored:
        return None

    hits = 0
    for item in scored:
        ranked = sorted(
            range(len(item.probabilities)),
            key=lambda index: item.probabilities[index],
            reverse=True,
        )
        if item.true_index in ranked[:k]:
            hits += 1
    return round(hits / len(scored), 4)


def mean_absolute_ordinal_error(predictions: Sequence[LabeledPrediction]) -> float:
    """Mean ``|true_index - pred_index|`` — how many *stages* off, on average.

    The single metric that distinguishes "confused Columns for Slab" (error 1)
    from "confused Excavation for Roof" (error 7). Plain accuracy scores both
    as equally wrong; this is why it is reported alongside accuracy rather than
    instead of it (``Construction-Stages.md`` — Ordinality).
    """
    if not predictions:
        return 0.0
    total = sum(abs(item.true_index - item.pred_index) for item in predictions)
    return round(total / len(predictions), 4)


def calibration_report(
    predictions: Sequence[LabeledPrediction], *, n_bins: int = 10
) -> CalibrationReport | None:
    """Bin predictions by confidence and compare against realised accuracy.

    Returns ``None`` on an empty input rather than a report full of NaNs — an
    empty calibration report is not a data point, it is the absence of one.
    """
    if not predictions:
        return None

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    confidences = np.array([item.confidence for item in predictions])
    correct = np.array([1.0 if item.pred_index == item.true_index else 0.0 for item in predictions])

    bin_confidence: list[float] = []
    bin_accuracy: list[float] = []
    bin_weight: list[float] = []
    weighted_gap = 0.0

    for lo, hi in itertools.pairwise(edges):
        # The final bin is closed on both ends so a confidence of exactly 1.0
        # (the stub's ceiling case, and a torch softmax can round to it) lands
        # somewhere rather than being silently dropped.
        in_bin = (confidences >= lo) & (confidences < hi if hi < 1.0 else confidences <= hi)
        count = int(in_bin.sum())
        weight = count / len(predictions)
        bin_weight.append(round(weight, 4))

        if count == 0:
            bin_confidence.append(float("nan"))
            bin_accuracy.append(float("nan"))
            continue

        mean_conf = float(confidences[in_bin].mean())
        mean_acc = float(correct[in_bin].mean())
        bin_confidence.append(round(mean_conf, 4))
        bin_accuracy.append(round(mean_acc, 4))
        weighted_gap += weight * abs(mean_conf - mean_acc)

    return CalibrationReport(
        n_bins=n_bins,
        bin_edges=tuple(round(float(edge), 4) for edge in edges),
        bin_confidence=tuple(bin_confidence),
        bin_accuracy=tuple(bin_accuracy),
        bin_weight=tuple(bin_weight),
        expected_calibration_error=round(weighted_gap, 4),
    )


def summarize_classification(
    predictions: Sequence[LabeledPrediction],
    class_names: Sequence[str],
    *,
    n_calibration_bins: int = 10,
) -> ClassificationReport:
    """Run every metric in this module once and bundle the result.

    This is the function :mod:`ai.evaluation.run_all` calls; everything above
    it exists so each piece is independently unit-testable with a two-line
    fixture.
    """
    matrix = confusion_matrix(predictions, len(class_names))
    row_totals = matrix.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        normalized = np.divide(
            matrix.astype(np.float64),
            row_totals,
            out=np.zeros_like(matrix, dtype=np.float64),
            where=row_totals != 0,
        )

    per_class = per_class_metrics(matrix, class_names)
    macro_f1 = round(sum(item.f1 for item in per_class) / len(per_class), 4) if per_class else 0.0

    return ClassificationReport(
        n=len(predictions),
        top1_accuracy=top1_accuracy(predictions),
        top2_accuracy=topk_accuracy(predictions, k=2),
        macro_f1=macro_f1,
        mean_absolute_ordinal_error=mean_absolute_ordinal_error(predictions),
        per_class=per_class,
        confusion=matrix,
        confusion_normalized=normalized,
        calibration=calibration_report(predictions, n_bins=n_calibration_bins),
        class_names=tuple(class_names),
    )
