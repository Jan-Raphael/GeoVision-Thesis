"""Unit tests for `ai.evaluation.metrics` — hand-verifiable synthetic fixtures only."""

from __future__ import annotations

import numpy as np
import pytest

from ai.evaluation.metrics import (
    LabeledPrediction,
    calibration_report,
    confusion_matrix,
    mean_absolute_ordinal_error,
    per_class_metrics,
    summarize_classification,
    top1_accuracy,
    topk_accuracy,
)

CLASS_NAMES = ("A", "B", "C")


def _pred(true_index: int, pred_index: int, confidence: float = 0.9) -> LabeledPrediction:
    probs = [0.0, 0.0, 0.0]
    probs[pred_index] = confidence
    remainder = (1 - confidence) / 2
    for i in range(3):
        if i != pred_index:
            probs[i] = remainder
    return LabeledPrediction(true_index, pred_index, confidence, tuple(probs))


class TestConfusionMatrix:
    def test_all_correct_is_diagonal(self) -> None:
        predictions = [_pred(0, 0), _pred(1, 1), _pred(2, 2)]
        matrix = confusion_matrix(predictions, num_classes=3)
        assert np.array_equal(matrix, np.eye(3, dtype=np.int64))

    def test_counts_land_in_true_row_predicted_column(self) -> None:
        predictions = [_pred(0, 1), _pred(0, 1)]
        matrix = confusion_matrix(predictions, num_classes=3)
        assert matrix[0, 1] == 2
        assert matrix.sum() == 2


class TestPerClassMetrics:
    def test_perfect_predictions_score_1_0(self) -> None:
        predictions = [_pred(0, 0), _pred(1, 1), _pred(2, 2)]
        matrix = confusion_matrix(predictions, num_classes=3)
        results = per_class_metrics(matrix, CLASS_NAMES)
        assert all(
            item.precision == 1.0 and item.recall == 1.0 and item.f1 == 1.0 for item in results
        )

    def test_a_class_never_predicted_scores_zero_not_nan(self) -> None:
        """0/0 must read as 0.0, not NaN — a NaN silently poisons any mean it enters."""
        predictions = [_pred(0, 1), _pred(1, 1)]  # class 0 has support but is never the argmax
        matrix = confusion_matrix(predictions, num_classes=3)
        results = per_class_metrics(matrix, CLASS_NAMES)
        assert results[0].recall == 0.0
        assert results[2].precision == 0.0  # class 2: never predicted, no support either


class TestAccuracy:
    def test_top1_accuracy_counts_exact_matches(self) -> None:
        predictions = [_pred(0, 0), _pred(1, 0), _pred(2, 2)]
        assert top1_accuracy(predictions) == pytest.approx(2 / 3, abs=1e-4)

    def test_top1_accuracy_of_empty_input_is_zero_not_an_error(self) -> None:
        assert top1_accuracy([]) == 0.0

    def test_topk_accuracy_catches_the_runner_up(self) -> None:
        # true=1, argmax=0, but class 1 is the second-highest probability
        prediction = LabeledPrediction(
            true_index=1, pred_index=0, confidence=0.5, probabilities=(0.5, 0.4, 0.1)
        )
        assert topk_accuracy([prediction], k=2) == 1.0

    def test_topk_accuracy_is_none_without_probabilities(self) -> None:
        predictions = [LabeledPrediction(0, 0, 0.9, probabilities=())]
        assert topk_accuracy(predictions) is None


class TestOrdinalError:
    """Ordinal error only reads `true_index`/`pred_index`, so these build
    `LabeledPrediction` directly rather than through `_pred`, which is scoped
    to a 3-class fixture."""

    def test_adjacent_confusion_scores_one(self) -> None:
        prediction = LabeledPrediction(true_index=4, pred_index=5, confidence=0.9)
        assert mean_absolute_ordinal_error([prediction]) == 1.0

    def test_distant_confusion_scores_the_full_gap(self) -> None:
        prediction = LabeledPrediction(true_index=0, pred_index=9, confidence=0.9)
        assert mean_absolute_ordinal_error([prediction]) == 9.0

    def test_perfect_predictions_score_zero(self) -> None:
        predictions = [
            LabeledPrediction(true_index=3, pred_index=3, confidence=0.9),
            LabeledPrediction(true_index=7, pred_index=7, confidence=0.9),
        ]
        assert mean_absolute_ordinal_error(predictions) == 0.0


class TestCalibration:
    def test_empty_input_returns_none(self) -> None:
        assert calibration_report([]) is None

    def test_perfectly_calibrated_predictions_score_zero_ece(self) -> None:
        # Every prediction at confidence 1.0 and always correct: confidence
        # and accuracy agree exactly in the top bin.
        predictions = [_pred(i % 3, i % 3, confidence=1.0) for i in range(10)]
        report = calibration_report(predictions, n_bins=5)
        assert report is not None
        assert report.expected_calibration_error == 0.0

    def test_bin_weights_sum_to_one(self) -> None:
        predictions = [_pred(0, 0, confidence=c) for c in (0.1, 0.3, 0.5, 0.7, 0.9)]
        report = calibration_report(predictions, n_bins=5)
        assert report is not None
        assert sum(report.bin_weight) == pytest.approx(1.0)


class TestSummarizeClassification:
    def test_bundles_every_metric_consistently(self) -> None:
        predictions = [_pred(0, 0), _pred(1, 1), _pred(2, 0)]
        report = summarize_classification(predictions, CLASS_NAMES)
        assert report.n == 3
        assert report.top1_accuracy == pytest.approx(2 / 3, abs=1e-4)
        assert report.confusion.sum() == 3
        assert report.confusion_normalized.shape == (3, 3)
        assert report.class_names == CLASS_NAMES
        assert report.calibration is not None
