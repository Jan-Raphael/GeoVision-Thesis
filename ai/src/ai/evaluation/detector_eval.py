"""YOLOv8 evaluation: mAP, and the classifier/detector agreement experiment.

Two unrelated jobs share this file because the vault treats them as one
chapter (``Evaluation-Plan.md`` §3). The first is standard detection scoring.
The second is what turns "we also trained a detector" into a real corroboration
result: a **rule-based stage inferred purely from object counts** — a
``roof`` box means at least Roofing, ``scaffolding`` with no ``roof`` means at
most Framing — compared against the classifier's stage on the same images.
Agreement between two independently-trained models that never see each other's
output is a much stronger claim than either model's accuracy alone.

Both halves operate on :class:`~ai.models.base.DetectionResult` /
:class:`~ai.models.base.BoundingBox`, so they run against
:class:`~ai.models.stub.StubDetector` today and a trained YOLOv8n tomorrow.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ai.models.base import BoundingBox, DetectedObject
from ai.progress.mapping import MacroStage

__all__ = [
    "AgreementReport",
    "DetectionAP",
    "DetectionEvalSample",
    "MAPReport",
    "agreement_report",
    "average_precision",
    "iou",
    "mean_average_precision",
    "stage_from_object_counts",
]


def iou(a: BoundingBox, b: BoundingBox) -> float:
    """Intersection-over-union of two normalised boxes.

    Boxes are ``(x, y, width, height)`` fractions of the frame, matching how
    they are stored (``Domain-Model.md`` — ``detections`` table): comparing
    fractions rather than pixels means this function is correct regardless of
    what resolution either box was drawn at.
    """
    ax2, ay2 = a.x + a.width, a.y + a.height
    bx2, by2 = b.x + b.width, b.y + b.height

    inter_x = max(0.0, min(ax2, bx2) - max(a.x, b.x))
    inter_y = max(0.0, min(ay2, by2) - max(a.y, b.y))
    intersection = inter_x * inter_y
    if intersection <= 0:
        return 0.0

    union = a.width * a.height + b.width * b.height - intersection
    return intersection / union if union > 0 else 0.0


@dataclass(frozen=True, slots=True)
class DetectionEvalSample:
    """One test image's ground-truth boxes and the detector's predictions."""

    image_id: str
    ground_truth: tuple[DetectedObject, ...]
    predictions: tuple[DetectedObject, ...]


@dataclass(frozen=True, slots=True)
class DetectionAP:
    """Average precision for one class at one IoU threshold."""

    class_name: str
    iou_threshold: float
    average_precision: float
    n_ground_truth: int


def average_precision(
    samples: Sequence[DetectionEvalSample], class_name: str, iou_threshold: float = 0.5
) -> DetectionAP:
    """AP for one class at one IoU threshold, by all-point interpolation.

    Standard greedy matching: predictions are sorted by confidence
    (highest first), and each is matched to the highest-IoU unclaimed
    ground-truth box of the same class that clears the threshold — a
    ground-truth box may be matched at most once, so a detector that draws
    five boxes on one column gets four false positives, not five true
    positives. All-point interpolation (the exact area under the raw
    precision/recall curve, not the older 11-point approximation) is what
    COCO and Pascal VOC 2010+ both use, so a number reported here is directly
    comparable to numbers in the detection literature.
    """
    ground_truth_count = sum(
        1 for sample in samples for box in sample.ground_truth if box.class_name == class_name
    )
    if ground_truth_count == 0:
        return DetectionAP(class_name, iou_threshold, 0.0, 0)

    scored: list[tuple[float, str, int]] = []  # (confidence, image_id, prediction_index)
    for sample in samples:
        for index, box in enumerate(sample.predictions):
            if box.class_name == class_name:
                scored.append((box.confidence, sample.image_id, index))
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return DetectionAP(class_name, iou_threshold, 0.0, ground_truth_count)

    by_image = {sample.image_id: sample for sample in samples}
    claimed: dict[str, set[int]] = {sample.image_id: set() for sample in samples}

    tp = np.zeros(len(scored))
    fp = np.zeros(len(scored))

    for rank, (_, image_id, pred_index) in enumerate(scored):
        sample = by_image[image_id]
        prediction = sample.predictions[pred_index]

        best_iou = 0.0
        best_gt_index = -1
        for gt_index, gt_box in enumerate(sample.ground_truth):
            if gt_box.class_name != class_name or gt_index in claimed[image_id]:
                continue
            score = iou(prediction.bbox, gt_box.bbox)
            if score > best_iou:
                best_iou = score
                best_gt_index = gt_index

        if best_iou >= iou_threshold and best_gt_index >= 0:
            tp[rank] = 1
            claimed[image_id].add(best_gt_index)
        else:
            fp[rank] = 1

    tp_cumsum = np.cumsum(tp)
    fp_cumsum = np.cumsum(fp)
    recall = tp_cumsum / ground_truth_count
    precision = tp_cumsum / np.maximum(tp_cumsum + fp_cumsum, 1e-9)

    # All-point interpolation: precision envelope made monotonically
    # non-increasing from the right, then integrated against the change in
    # recall. This is the part that differs from a naive "area under the raw
    # points" trapezoid and is what makes the number match COCO/VOC tooling.
    precision_envelope = np.concatenate(([0.0], precision, [0.0]))
    recall_envelope = np.concatenate(([0.0], recall, [1.0]))
    for index in range(len(precision_envelope) - 2, -1, -1):
        precision_envelope[index] = max(precision_envelope[index], precision_envelope[index + 1])

    changes = np.where(recall_envelope[1:] != recall_envelope[:-1])[0]
    ap = float(
        np.sum(
            (recall_envelope[changes + 1] - recall_envelope[changes])
            * precision_envelope[changes + 1]
        )
    )
    return DetectionAP(class_name, iou_threshold, round(ap, 4), ground_truth_count)


@dataclass(frozen=True, slots=True)
class MAPReport:
    """mAP@0.5 and the coarse mAP@0.5:0.95 sweep, per class and overall."""

    per_class_ap50: tuple[DetectionAP, ...]
    map50: float
    #: Mean AP averaged over IoU thresholds 0.50, 0.55, ..., 0.95 — the COCO
    #: primary metric. Stored as one number per class isn't kept (ten
    #: thresholds x N classes gets unwieldy fast); only the class-averaged
    #: curve is.
    map50_95: float


def mean_average_precision(
    samples: Sequence[DetectionEvalSample], class_names: Sequence[str]
) -> MAPReport:
    """mAP@0.5 (reported per class) and mAP@0.5:0.95 (summary only)."""
    per_class_50 = tuple(average_precision(samples, name, 0.5) for name in class_names)
    map50 = (
        round(sum(item.average_precision for item in per_class_50) / len(per_class_50), 4)
        if per_class_50
        else 0.0
    )

    thresholds = np.arange(0.50, 1.00, 0.05)
    sweep_means = []
    for threshold in thresholds:
        aps = [average_precision(samples, name, float(threshold)) for name in class_names]
        if aps:
            sweep_means.append(sum(item.average_precision for item in aps) / len(aps))
    map50_95 = round(float(np.mean(sweep_means)), 4) if sweep_means else 0.0

    return MAPReport(per_class_ap50=per_class_50, map50=map50, map50_95=map50_95)


# ---------------------------------------------------------------------------
# Classifier / detector agreement
# ---------------------------------------------------------------------------

#: Rule-based stage inference from object counts alone — a deliberately simple,
#: human-auditable ruleset, not a second learned model. Order matters: checked
#: from the most-advanced signal down, so a site with both scaffolding and a
#: finished roof (plausible during finishing work) reads as the more advanced
#: stage rather than the more common object.
_RULES: tuple[tuple[str, MacroStage], ...] = (
    ("roof", MacroStage.ROOFING),
    ("wall", MacroStage.FRAMING),
    ("beam", MacroStage.FRAMING),
    ("column", MacroStage.FRAMING),
    ("scaffolding", MacroStage.FRAMING),
)


def stage_from_object_counts(counts: dict[str, int]) -> MacroStage | None:
    """The corroboration rule: object counts alone, no classifier involved.

    Returns ``None`` when nothing recognisable was detected — "no opinion" is
    the honest answer, and forcing a guess (e.g. defaulting to Foundation)
    would make an empty detection look like agreement or disagreement by
    accident rather than by evidence.
    """
    for class_name, stage in _RULES:
        if counts.get(class_name, 0) > 0:
            return stage
    return None


@dataclass(frozen=True, slots=True)
class AgreementReport:
    """How often the rule-based (detector) stage matches the classifier's."""

    n_comparable: int
    n_total: int
    agreement_rate: float
    #: classifier stage -> rule-based stage -> count. A dict rather than a
    #: numpy matrix because the key set is the five-value ``MacroStage`` enum,
    #: not a dense index range, and the report layer wants the names anyway.
    confusion: dict[MacroStage, dict[MacroStage, int]]


def agreement_report(
    classifier_stages: Sequence[MacroStage], detection_counts: Sequence[dict[str, int]]
) -> AgreementReport:
    """Compare the classifier's stage against the detector's on the same images.

    Args:
        classifier_stages: One macro stage per test image, from the classifier.
        detection_counts: That image's detected-object counts, same order.

    Images where the rule has no opinion (empty or unrecognised detections)
    are excluded from ``agreement_rate`` but counted in ``n_total``, so a
    detector that rarely fires is visible in the gap between the two counts
    rather than silently dragging the rate down as if it had disagreed.
    """
    confusion: dict[MacroStage, dict[MacroStage, int]] = {
        stage: dict.fromkeys(MacroStage, 0) for stage in MacroStage
    }
    comparable = 0
    agreeing = 0

    for classifier_stage, counts in zip(classifier_stages, detection_counts, strict=True):
        rule_stage = stage_from_object_counts(counts)
        if rule_stage is None:
            continue
        comparable += 1
        confusion[classifier_stage][rule_stage] += 1
        if rule_stage == classifier_stage:
            agreeing += 1

    rate = round(agreeing / comparable, 4) if comparable else 0.0
    return AgreementReport(
        n_comparable=comparable,
        n_total=len(classifier_stages),
        agreement_rate=rate,
        confusion=confusion,
    )
