"""Per-image progress: turning one classification into one number.

Stage 1 of four (``Progress-Calculation.md`` §1). A class only says *which*
20-point band an image falls in (ADR-036); where within that band is resolved
by fusing two independent signals (ADR-038, closing Open-Questions Q18):

* ``classifier_fraction`` — the softmax confidence of the predicted class,
  used as a proxy for how far into the stage's typical appearance the photo
  sits.
* ``detector_fraction`` — how many of that stage's expected YOLO elements
  (``classes.yaml``'s ``detection_checklists``) were found in the frame.

The two are averaged, then mapped onto the class's floor-to-ceiling band. This
keeps the classifier and the detector as two votes on the same question rather
than letting either one decide alone — a photograph the classifier is unsure
about but where the detector already sees the next stage's elements, and one
the classifier is confident about but the detector sees nothing new in, land at
similar answers instead of at the extremes either signal alone would produce.

The eligibility decision is separate and unchanged: a low-confidence prediction
is **stored and shown**, badged as uncertain, but excluded from aggregation.
Discarding it entirely would hide from the owner that the camera saw something;
counting it would let a coin-flip move a number people act on.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ai.progress.constants import MIN_CONFIDENCE
from ai.progress.mapping import MacroStage, StageReference, detection_checklist_for, reference_for

__all__ = ["ImageProgress", "estimate", "fused_raw_pct"]


@dataclass(frozen=True, slots=True)
class ImageProgress:
    """What one classified image contributes."""

    image_id: str
    device_id: str
    fine_class_index: int
    fine_class: str
    macro_stage: MacroStage
    confidence: float
    raw_progress_pct: float
    is_eligible: bool

    @property
    def low_confidence(self) -> bool:
        """Whether the UI should badge this as uncertain."""
        return not self.is_eligible


def fused_raw_pct(
    *,
    class_index: int,
    confidence: float,
    detected_classes: Iterable[str] = (),
    reference: StageReference | None = None,
) -> float:
    """Where within a class's 20-point band one image falls (ADR-038).

    ``sub_stage_fraction = (classifier_fraction + detector_fraction) / 2``,
    then mapped onto ``[stage_floor_pct, stage_ceiling_pct]``. A class with no
    checklist configured falls back to the classifier's confidence alone.

    Args:
        class_index: The classifier's argmax, as a frozen class index.
        confidence: Softmax probability of that class, 0-1. Used directly as
            ``classifier_fraction``.
        detected_classes: Distinct YOLO class names found in the same frame
            (e.g. ``DetectionResult.counts`` iterates its keys). Duplicates and
            order do not matter — only which checklist elements are present.
        reference: Pre-resolved class reference, to avoid a repeated lookup in a
            tight loop. Resolved from ``class_index`` when omitted.

    Returns:
        The fused raw percentage, in the predicted class's own band.
    """
    stage = reference or reference_for(class_index)
    checklist = detection_checklist_for(stage.token)

    if checklist:
        found = set(detected_classes)
        detector_fraction = sum(1 for item in checklist if item in found) / len(checklist)
    else:
        detector_fraction = confidence

    sub_stage_fraction = (confidence + detector_fraction) / 2
    span = stage.stage_ceiling_pct - stage.stage_floor_pct
    return stage.stage_floor_pct + sub_stage_fraction * span


def estimate(
    *,
    image_id: str,
    device_id: str,
    class_index: int,
    confidence: float,
    detected_classes: Iterable[str] = (),
    min_confidence: float = MIN_CONFIDENCE,
    reference: StageReference | None = None,
) -> ImageProgress:
    """Score one classified image.

    Args:
        image_id: The image this prediction belongs to.
        device_id: Which camera took it. Carried through because aggregation is
            per-device before it is per-project.
        class_index: The classifier's argmax, as a frozen class index.
        confidence: Softmax probability of that class, 0-1.
        detected_classes: Distinct YOLO class names found in the same frame —
            see :func:`fused_raw_pct`.
        min_confidence: The eligibility gate.
        reference: Pre-resolved class reference, to avoid a repeated lookup in a
            tight loop. Resolved from ``class_index`` when omitted.

    Returns:
        The image's fused progress and whether it may influence the project.

    Raises:
        KeyError: If ``class_index`` is not in the frozen class list.
        ValueError: If ``confidence`` is outside 0-1 — that means the caller
            passed a logit rather than a probability, which would sail through
            the eligibility gate and silently make every prediction count.
    """
    if not 0.0 <= confidence <= 1.0:
        msg = f"confidence must be a probability in [0, 1], got {confidence}"
        raise ValueError(msg)

    stage = reference or reference_for(class_index)
    raw_pct = fused_raw_pct(
        class_index=class_index,
        confidence=confidence,
        detected_classes=detected_classes,
        reference=stage,
    )
    return ImageProgress(
        image_id=image_id,
        device_id=device_id,
        fine_class_index=stage.index,
        fine_class=stage.name,
        macro_stage=stage.macro_stage,
        confidence=confidence,
        raw_progress_pct=raw_pct,
        is_eligible=confidence >= min_confidence,
    )
