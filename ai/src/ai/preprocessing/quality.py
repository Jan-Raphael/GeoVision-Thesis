"""The quality gate: what never reaches the classifier.

Three cheap measurements on the decoded original, before anything expensive
happens. Rejecting here saves the rectification, the CLAHE pass, the bilateral
filter, and a forward pass through ResNet18 — but that is the smaller reason.
The real reason is that a classifier handed a blurry, dark, or truck-obscured
frame does not decline to answer. It answers confidently and wrongly, and that
wrong answer flows into a progress percentage somebody may act on.

Thresholds come from :mod:`ai.progress.constants` — never re-typed here.

Two design choices worth stating:

**Measured on the original, not the processed frame.** Blur variance and mean
brightness both depend on resolution and on the CLAHE pass, so measuring after
processing would make a photograph's score depend on pipeline settings. The same
photograph must always score the same, or the dataset audit ("how many of my own
captures would have been rejected?") means nothing.

**A failure is a result, not an exception.** At inference the image is stored
with ``status='rejected'``; at training the gate is used to audit the dataset.
Neither is served by raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import cv2
import numpy as np

from ai.preprocessing.types import CalibrationContext, Image
from ai.progress.constants import (
    BLUR_THRESHOLD,
    DARKNESS_THRESHOLD,
    OCCLUSION_MAX_RATIO,
)

__all__ = ["QualityFlag", "QualityGate", "QualityReport", "assess"]


class QualityFlag(StrEnum):
    """Why a frame was rejected. Multiple flags can apply at once."""

    BLURRY = "blurry"
    TOO_DARK = "too_dark"
    OCCLUDED = "occluded"


@dataclass(frozen=True, slots=True)
class QualityReport:
    """The gate's verdict, with the numbers behind it.

    The scores are kept even when the frame passes. They are what makes the
    thesis able to say *how* marginal the accepted images were, rather than only
    how many were thrown away.
    """

    passed: bool
    flags: tuple[QualityFlag, ...]
    blur_score: float
    brightness: float
    occlusion_ratio: float

    @property
    def reason(self) -> str | None:
        """A short human-readable summary, or ``None`` when the frame passed."""
        if self.passed:
            return None
        return ", ".join(flag.value for flag in self.flags)

    def as_dict(self) -> dict[str, Any]:
        """Serialise for storage on the image row and for the dataset audit."""
        return {
            "passed": self.passed,
            "flags": [flag.value for flag in self.flags],
            "blur_score": round(self.blur_score, 3),
            "brightness": round(self.brightness, 3),
            "occlusion_ratio": round(self.occlusion_ratio, 4),
        }


def blur_score(image: Image) -> float:
    """Variance of the Laplacian — higher is sharper.

    The Laplacian responds to second-order intensity change, so a sharp edge
    produces a large positive and a large negative response side by side, and the
    *variance* over the whole frame summarises how much such structure exists. A
    defocused or motion-blurred frame has smooth gradients and little of it.

    Scale-dependent by nature, which is why this is measured on the original at
    native resolution and never after a resize.
    """
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def brightness(image: Image) -> float:
    """Mean of the LAB L channel, 0-255.

    L is perceptual lightness, unlike a mean over BGR which weights a saturated
    blue sky the same as the grey concrete underneath it. A construction site
    photographed at dusk is dark in a way L measures and RGB averages hide.
    """
    lightness = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)[:, :, 0]
    return float(np.mean(lightness))


#: Local standard deviation below which a region carries no structure the
#: classifier could read. JPEG noise on a flat surface sits around 3-6; façade
#: detail — formwork lines, window reveals, scaffolding — comfortably exceeds 12.
TEXTURE_FLOOR = 8.0

#: How far a region's intensity must sit from the façade's own median before it
#: is treated as a different object rather than part of the building. See the
#: false-positive discussion in :func:`occlusion_ratio`.
INTENSITY_DELTA = 25.0

#: A polygon smaller than this is not a calibration, it is a mis-click.
MIN_ROI_AREA_PX = 256

#: Absolute floor on a candidate blob, for very small ROIs where 1 % is a
#: handful of pixels.
MIN_BLOB_AREA_PX = 64


def occlusion_ratio(image: Image, ctx: CalibrationContext) -> float:
    """Fraction of the façade ROI covered by a near-field obstruction.

    Returns ``0.0`` when the device has no usable ROI polygon. That is
    deliberate: an uncalibrated camera should not have every frame rejected for
    an occlusion nobody has defined the boundaries of.

    The heuristic is worth recording for the thesis, including its limits. What
    obscures a fixed site camera is almost always *close* to the lens — a truck
    parked in front of it, a tarpaulin, a worker's jacket. Two properties follow,
    and the test requires **both**:

    1. **Low local texture.** Close objects fall outside the depth of field, so
       they arrive as large regions of near-uniform intensity, whereas a façade
       at distance is full of edges.

    2. **Intensity unlike the rest of the ROI.** Each flat region is compared
       against the ROI *excluding that region* — deliberately not against the
       ROI's overall median, which fails exactly when it matters most: an
       occluder covering most of the façade becomes the median, declares itself
       normal, and passes.

    The second condition is not decoration. It is what stops the gate rejecting a
    *legitimately smooth* wall — freshly poured concrete, a rendered finish, a
    tarpaulin stretched flat as weatherproofing are all low-texture and all
    perfectly valid subjects. Texture alone flags every one of them, and a gate
    that silently discards good captures of a smooth building is worse than no
    gate: the images vanish, the progress curve thins, and nothing reports an
    error.

    The cost of requiring both is a miss when an occluder matches the façade's
    brightness — a grey truck against grey concrete. That trade is the right way
    round. A missed occlusion contributes one bad frame to a window whose value
    is a *median* over many frames, so it is absorbed; a false rejection removes
    a good frame permanently. A fully blocked lens, where this test has no
    unobstructed remainder to compare against, is caught by the blur gate
    instead — a surface pressed against the lens is never in focus.
    """
    if not ctx.has_roi:
        return 0.0

    height, width = image.shape[:2]
    roi_mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(roi_mask, [np.asarray(ctx.roi_polygon, dtype=np.int32)], color=255)

    roi_area = int(np.count_nonzero(roi_mask))
    if roi_area < MIN_ROI_AREA_PX:
        # Degenerate: collinear points, a mis-click, or a polygon entirely
        # outside the frame. Reporting 0 rather than dividing by a near-zero
        # area, because a bad calibration must not reject every capture that
        # follows it — that failure would look like a broken camera.
        return 0.0

    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    grey_f = grey.astype(np.float32)

    # Local texture energy: standard deviation inside a sliding window, computed
    # as sqrt(E[x²] - E[x]²) via two box filters. Exactly equivalent to a
    # per-pixel windowed std and dramatically faster.
    kernel = (15, 15)
    mean = cv2.blur(grey_f, kernel)
    mean_square = cv2.blur(grey_f * grey_f, kernel)
    texture = np.sqrt(np.maximum(mean_square - mean * mean, 0.0))

    flat = ((texture < TEXTURE_FLOOR).astype(np.uint8) * 255) & roi_mask

    # Opening removes speckle, so scattered pixels never accumulate into a false
    # occlusion. Only contiguous regions survive — which is what an obstruction
    # actually looks like.
    opened = cv2.morphologyEx(flat, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    if count <= 1:
        return 0.0

    inside_roi = roi_mask > 0
    roi_total = float(grey_f[inside_roi].sum())
    occluded_pixels = 0

    for label in range(1, count):
        blob_area = int(stats[label, cv2.CC_STAT_AREA])
        # Below 1 % of the ROI a region cannot reach the rejection threshold on
        # its own, and comparing tiny blobs adds noise for no decision value.
        if blob_area < max(MIN_BLOB_AREA_PX, roi_area // 100):
            continue

        blob = labels == label
        blob_mean = float(grey_f[blob].mean())

        # The reference is the ROI *without* this blob. When a truck covers 90 %
        # of the façade, the remaining 10 % is still the building, and that is
        # what the truck must be compared against.
        remainder_area = roi_area - blob_area
        if remainder_area <= 0:
            continue
        remainder_mean = (roi_total - float(grey_f[blob].sum())) / remainder_area

        if abs(blob_mean - remainder_mean) > INTENSITY_DELTA:
            occluded_pixels += blob_area

    return float(occluded_pixels / roi_area)


def assess(
    image: Image,
    ctx: CalibrationContext | None = None,
    *,
    blur_threshold: float = BLUR_THRESHOLD,
    darkness_threshold: float = DARKNESS_THRESHOLD,
    occlusion_max_ratio: float = OCCLUSION_MAX_RATIO,
) -> QualityReport:
    """Measure a frame and decide whether it is worth classifying.

    Args:
        image: The decoded original, BGR uint8.
        ctx: Device calibration. Without an ROI polygon, occlusion is not tested.
        blur_threshold: Minimum Laplacian variance.
        darkness_threshold: Minimum mean L.
        occlusion_max_ratio: Maximum obscured fraction of the ROI.

    Returns:
        A report carrying every score, whether or not the frame passed.
    """
    context = ctx or CalibrationContext()

    sharpness = blur_score(image)
    lightness = brightness(image)
    occluded = occlusion_ratio(image, context)

    flags: list[QualityFlag] = []
    if sharpness < blur_threshold:
        flags.append(QualityFlag.BLURRY)
    if lightness < darkness_threshold:
        flags.append(QualityFlag.TOO_DARK)
    if occluded > occlusion_max_ratio:
        flags.append(QualityFlag.OCCLUDED)

    return QualityReport(
        passed=not flags,
        flags=tuple(flags),
        blur_score=sharpness,
        brightness=lightness,
        occlusion_ratio=occluded,
    )


@dataclass(slots=True)
class QualityGate:
    """The quality gate as a pipeline step.

    Passes the image through untouched — it measures, it does not transform. The
    pipeline reads the report off :attr:`last_report`.
    """

    blur_threshold: float = BLUR_THRESHOLD
    darkness_threshold: float = DARKNESS_THRESHOLD
    occlusion_max_ratio: float = OCCLUSION_MAX_RATIO
    name: str = "quality_gate"
    last_report: QualityReport | None = None

    def apply(self, image: Image, ctx: CalibrationContext) -> Image:
        """Measure quality, storing the report; return the image unchanged."""
        self.last_report = assess(
            image,
            ctx,
            blur_threshold=self.blur_threshold,
            darkness_threshold=self.darkness_threshold,
            occlusion_max_ratio=self.occlusion_max_ratio,
        )
        return image

    def describe(self) -> dict[str, Any]:
        """Parameters that affect the verdict, for the config fingerprint."""
        return {
            "blur_threshold": self.blur_threshold,
            "darkness_threshold": self.darkness_threshold,
            "occlusion_max_ratio": self.occlusion_max_ratio,
        }
