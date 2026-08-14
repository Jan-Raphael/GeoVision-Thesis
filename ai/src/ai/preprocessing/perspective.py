"""Perspective rectification.

A camera bolted to a pole sees the façade at an angle, so the building is a
trapezoid in the frame. Two cameras on the same site see *different* trapezoids.
Rectifying both onto a canonical rectangle means the classifier learns what a
stage looks like rather than what a particular mounting angle looks like — and
it means the ROI and progress fractions from two cameras are comparable.

Geometry before photometry: this runs before CLAHE and denoising, because
warping resamples pixels and would smear any contrast enhancement applied first.

A device with no ``homography`` is passed through untouched. Most cameras will
run uncalibrated for their first days on site, and refusing to process their
captures until somebody has clicked four corners would mean losing exactly the
early-stage images the project needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from ai.preprocessing.errors import ConfigError
from ai.preprocessing.types import CalibrationContext, Image

__all__ = ["PerspectiveRectify", "rectify"]


def rectify(
    image: Image,
    homography: NDArray[np.float64] | None,
    *,
    output_size: tuple[int, int] | None = None,
) -> Image:
    """Warp *image* onto its canonical rectangle.

    Args:
        image: Source frame, BGR uint8.
        homography: 3x3 transform. ``None`` returns the image unchanged.
        output_size: ``(width, height)`` of the result. Defaults to the input
            size, which keeps the step resolution-neutral so that changing the
            target resize does not silently change the rectification.

    Returns:
        The rectified image, or the original when there is no homography.

    Raises:
        ConfigError: If the homography is not a 3x3 matrix.
    """
    if homography is None:
        return image

    matrix = np.asarray(homography, dtype=np.float64)
    if matrix.shape != (3, 3):
        msg = f"homography must be 3x3, got {matrix.shape}"
        raise ConfigError(msg)

    height, width = image.shape[:2]
    size = output_size or (width, height)

    # INTER_LINEAR, not INTER_CUBIC: cubic overshoots at strong edges, producing
    # halos along exactly the structural lines (formwork, scaffolding) the
    # classifier depends on. BORDER_REPLICATE rather than a black fill so the
    # edges of a warped frame do not introduce artificial high-contrast borders
    # that the blur metric and the classifier would both read as structure.
    warped = cv2.warpPerspective(
        image,
        matrix,
        size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return np.asarray(warped, dtype=np.uint8)


@dataclass(slots=True)
class PerspectiveRectify:
    """Rectification as a pipeline step."""

    enabled: bool = True
    name: str = "perspective_rectify"

    def apply(self, image: Image, ctx: CalibrationContext) -> Image:
        """Rectify using the device's homography, if it has one."""
        if not self.enabled or not ctx.has_homography:
            return image
        return rectify(image, ctx.homography)

    def describe(self) -> dict[str, Any]:
        """Parameters affecting the output.

        The homography itself is *not* included: it is per-device, so folding it
        into the pipeline fingerprint would give every camera a different
        fingerprint and make the train/serve comparison meaningless. What matters
        for skew is whether rectification is applied at all.
        """
        return {"enabled": self.enabled}
