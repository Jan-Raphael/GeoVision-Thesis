"""Edge-preserving noise reduction.

The OV2640 on an ESP32-CAM is a small, cheap sensor. In anything but bright
daylight it produces visible chroma noise, and CLAHE has just amplified it — which
is why denoising runs *after* normalisation rather than before. Denoise first and
the contrast pass simply re-amplifies whatever noise the filter left behind.

A bilateral filter rather than a Gaussian blur, because what the classifier reads
on a construction site is *edges*: the line where formwork meets poured concrete,
the grid of scaffolding, the silhouette of a roof truss. A Gaussian smooths noise
and edges alike. A bilateral filter weights neighbours by intensity similarity as
well as distance, so it averages within flat regions and stops at boundaries.

It is also the slowest step in the pipeline by a wide margin, which is why
:mod:`ai.preprocessing.pipeline` places it after the resize by default — see the
note there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from ai.preprocessing.types import CalibrationContext, Image

__all__ = ["BilateralDenoise", "bilateral_denoise"]


def bilateral_denoise(
    image: Image,
    *,
    diameter: int = 9,
    sigma_color: float = 75.0,
    sigma_space: float = 75.0,
) -> Image:
    """Smooth flat regions while keeping edges sharp.

    Args:
        image: BGR uint8.
        diameter: Neighbourhood diameter in pixels. 9 is the documented default;
            larger is dramatically slower for little visible gain.
        sigma_color: How different in intensity a neighbour may be and still be
            averaged in. Larger values smooth across weaker edges.
        sigma_space: How far away a neighbour may be. Larger values smooth more
            broadly.

    Returns:
        A new BGR uint8 image.
    """
    filtered = cv2.bilateralFilter(
        image, d=diameter, sigmaColor=sigma_color, sigmaSpace=sigma_space
    )
    return np.asarray(filtered, dtype=np.uint8)


@dataclass(slots=True)
class BilateralDenoise:
    """Bilateral filtering as a pipeline step."""

    diameter: int = 9
    sigma_color: float = 75.0
    sigma_space: float = 75.0
    name: str = "denoise"

    def apply(self, image: Image, ctx: CalibrationContext) -> Image:
        """Denoise while preserving structural edges."""
        _ = ctx
        return bilateral_denoise(
            image,
            diameter=self.diameter,
            sigma_color=self.sigma_color,
            sigma_space=self.sigma_space,
        )

    def describe(self) -> dict[str, Any]:
        """Every parameter that changes the output."""
        return {
            "diameter": self.diameter,
            "sigma_color": self.sigma_color,
            "sigma_space": self.sigma_space,
        }
