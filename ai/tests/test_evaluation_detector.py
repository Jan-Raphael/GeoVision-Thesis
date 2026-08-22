"""Unit tests for `ai.evaluation.detector_eval` — mAP and the agreement rule."""

from __future__ import annotations

import pytest

from ai.evaluation.detector_eval import (
    DetectionEvalSample,
    agreement_report,
    average_precision,
    iou,
    mean_average_precision,
    stage_from_object_counts,
)
from ai.models.base import BoundingBox, DetectedObject
from ai.progress.mapping import MacroStage


def _box(x: float, y: float, w: float, h: float) -> BoundingBox:
    return BoundingBox(x=x, y=y, width=w, height=h)


class TestIoU:
    def test_identical_boxes_score_one(self) -> None:
        box = _box(0.1, 0.1, 0.2, 0.2)
        assert iou(box, box) == pytest.approx(1.0)

    def test_disjoint_boxes_score_zero(self) -> None:
        assert iou(_box(0.0, 0.0, 0.1, 0.1), _box(0.5, 0.5, 0.1, 0.1)) == 0.0

    def test_a_known_half_overlap(self) -> None:
        # Two 0.2x0.2 boxes overlapping in a 0.1x0.2 strip: intersection 0.02,
        # union 0.2*0.2 + 0.2*0.2 - 0.02 = 0.06 -> IoU = 0.02/0.06 = 1/3.
        a = _box(0.0, 0.0, 0.2, 0.2)
        b = _box(0.1, 0.0, 0.2, 0.2)
        assert iou(a, b) == pytest.approx(1 / 3)


class TestAveragePrecision:
    def test_a_perfect_detector_scores_one(self) -> None:
        gt = DetectedObject("column", 1.0, _box(0.1, 0.1, 0.2, 0.2))
        pred = DetectedObject("column", 0.95, _box(0.1, 0.1, 0.2, 0.2))
        samples = [DetectionEvalSample("img1", (gt,), (pred,))]
        result = average_precision(samples, "column", iou_threshold=0.5)
        assert result.average_precision == pytest.approx(1.0)
        assert result.n_ground_truth == 1

    def test_a_false_positive_with_no_ground_truth_scores_zero(self) -> None:
        pred = DetectedObject("column", 0.9, _box(0.1, 0.1, 0.2, 0.2))
        samples = [DetectionEvalSample("img1", (), (pred,))]
        result = average_precision(samples, "column")
        assert result.average_precision == 0.0
        assert result.n_ground_truth == 0

    def test_no_ground_truth_and_no_predictions_scores_zero_not_an_error(self) -> None:
        samples = [DetectionEvalSample("img1", (), ())]
        result = average_precision(samples, "column")
        assert result.average_precision == 0.0

    def test_a_missed_detection_scores_below_one(self) -> None:
        gt = DetectedObject("column", 1.0, _box(0.1, 0.1, 0.2, 0.2))
        samples = [DetectionEvalSample("img1", (gt,), ())]
        result = average_precision(samples, "column")
        assert result.average_precision == 0.0
        assert result.n_ground_truth == 1

    def test_a_second_box_on_the_same_target_does_not_inflate_ap(self) -> None:
        """One ground-truth box can only be matched once.

        With a single ground-truth box, recall reaches 1.0 at the first
        (highest-confidence) match — under the standard all-point
        interpolation (COCO/Pascal VOC 2010+), a same-target false positive
        *after* recall has already reached 1.0 does not reduce AP, because
        the precision envelope at recall=1.0 is already pinned by the first,
        correct detection. This is standard behaviour, not a gap: precision
        collapsing after full recall is exactly what `n_ground_truth` and
        the raw precision/recall curve (not exercised by this single number)
        are for.
        """
        gt = DetectedObject("column", 1.0, _box(0.1, 0.1, 0.2, 0.2))
        pred_high = DetectedObject("column", 0.9, _box(0.1, 0.1, 0.2, 0.2))
        pred_low = DetectedObject("column", 0.8, _box(0.1, 0.1, 0.2, 0.2))
        samples = [DetectionEvalSample("img1", (gt,), (pred_high, pred_low))]
        result = average_precision(samples, "column")
        assert result.average_precision == pytest.approx(1.0)

    def test_a_false_positive_on_a_different_image_caps_ap_below_one(self) -> None:
        """Hand-verified: 2 ground-truth boxes, 1 TP + 1 FP-elsewhere -> AP = 0.5.

        Recall can only reach 0.5 (one of the two ground-truth boxes is never
        matched), so the standard formula's zero-precision padding beyond the
        achieved recall drags the interpolated area down to exactly 0.5 —
        this is the case that demonstrates a detector actually being
        penalised for missed and spurious detections.
        """
        gt1 = DetectedObject("column", 1.0, _box(0.1, 0.1, 0.2, 0.2))
        gt2 = DetectedObject("column", 1.0, _box(0.6, 0.6, 0.2, 0.2))
        true_positive = DetectedObject("column", 0.9, _box(0.1, 0.1, 0.2, 0.2))
        false_positive = DetectedObject("column", 0.8, _box(0.6, 0.1, 0.1, 0.1))  # nowhere near gt2
        samples = [DetectionEvalSample("img1", (gt1, gt2), (true_positive, false_positive))]
        result = average_precision(samples, "column")
        assert result.average_precision == pytest.approx(0.5)
        assert result.n_ground_truth == 2


class TestMeanAveragePrecision:
    def test_averages_across_classes(self) -> None:
        gt_a = DetectedObject("column", 1.0, _box(0.0, 0.0, 0.2, 0.2))
        pred_a = DetectedObject("column", 0.9, _box(0.0, 0.0, 0.2, 0.2))
        samples = [DetectionEvalSample("img1", (gt_a,), (pred_a,))]
        report = mean_average_precision(samples, ["column", "wall"])
        assert report.map50 == pytest.approx(0.5)  # column=1.0, wall=0.0 (no data)
        assert 0.0 <= report.map50_95 <= report.map50


class TestStageFromObjectCounts:
    def test_roof_present_means_roofing_regardless_of_other_objects(self) -> None:
        assert stage_from_object_counts({"roof": 1, "scaffolding": 3}) == MacroStage.ROOFING

    def test_scaffolding_with_no_roof_means_framing(self) -> None:
        assert stage_from_object_counts({"scaffolding": 2}) == MacroStage.FRAMING

    def test_no_recognisable_objects_means_no_opinion(self) -> None:
        assert stage_from_object_counts({}) is None
        assert stage_from_object_counts({"worker": 4}) is None


class TestAgreementReport:
    def test_perfect_agreement_scores_one(self) -> None:
        stages = [MacroStage.ROOFING, MacroStage.FRAMING]
        counts = [{"roof": 1}, {"scaffolding": 1}]
        report = agreement_report(stages, counts)
        assert report.agreement_rate == 1.0
        assert report.n_comparable == 2
        assert report.n_total == 2

    def test_images_with_no_rule_opinion_are_excluded_from_the_rate(self) -> None:
        stages = [MacroStage.FOUNDATION]
        counts = [{}]  # no recognisable objects
        report = agreement_report(stages, counts)
        assert report.n_comparable == 0
        assert report.n_total == 1
        assert report.agreement_rate == 0.0  # not NaN, not a crash

    def test_disagreement_is_tallied_in_the_confusion_dict(self) -> None:
        stages = [MacroStage.FOUNDATION]
        counts = [{"roof": 1}]  # classifier says Foundation, detector implies Roofing
        report = agreement_report(stages, counts)
        assert report.confusion[MacroStage.FOUNDATION][MacroStage.ROOFING] == 1
        assert report.agreement_rate == 0.0
