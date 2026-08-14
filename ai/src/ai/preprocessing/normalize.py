"""Photometric normalisation: CLAHE and white balance.

This is the step that earns its place on this particular project. The schedule
captures at 07:00 and 16:00 — low warm morning sun and harsh afternoon light,
plus the tropical swing between a clear day and an overcast one. The *same wall*
at the *same stage* can differ more between those two captures than two genuinely
different stages differ from each other. Without normalisation the classifier has
every incentive to learn the time of day.

Two operations, in order:

1. **CLAHE on the LAB L channel.** Contrast-limited adaptive histogram
   equalisation, applied tile by tile, which recovers detail in a shadowed
   façade without blowing out the sunlit half. The contrast limit is what stops
   it amplifying noise in flat regions the way plain histogram equalisation does.

2. **Gray-world white balance.** Assumes the average of a scene is neutral grey
   and scales each channel toward that. Corrects the orange cast of morning light
   and the blue cast of open shade.

Both are deterministic. Neither has any randomness, so training and serving see
identical output for identical input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from ai.preprocessing.types import CalibrationContext, Image

__all__ = ["ClaheNormalize", "apply_clahe", "gray_world_white_balance"]


def apply_clahe(
    image: Image, *, clip_limit: float = 2.0, tile_grid_size: tuple[int, int] = (8, 8)
) -> Image:
    """Equalise local contrast on the lightness channel only.

    **L channel only.** Running CLAHE per BGR channel equalises each colour
    independently, which changes their ratios and therefore the hue — concrete
    comes out green, brick comes out grey. Converting to LAB isolates lightness
    from colour so contrast can be fixed without touching either.

    Args:
        image: BGR uint8.
        clip_limit: Contrast ceiling per tile. 2.0 is the documented default;
            higher values start amplifying sensor noise in flat sky.
        tile_grid_size: Tiles across and down. 8x8 on a 640x480 frame gives
            80x60-pixel tiles — small enough to treat a shadowed corner
            separately, large enough to hold real structure.

    Returns:
        A new BGR uint8 image.
    """
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, a_channel, b_channel = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
    equalised = clahe.apply(lightness)

    merged = cv2.merge((equalised, a_channel, b_channel))
    return np.asarray(cv2.cvtColor(merged, cv2.COLOR_LAB2BGR), dtype=np.uint8)


def gray_world_white_balance(image: Image) -> Image:
    """Neutralise a colour cast by scaling channels toward a common mean.

    The gray-world assumption — that a sufficiently varied scene averages to
    neutral — holds reasonably for a construction site, which is mostly grey
    concrete, brown earth, and sky. It would fail badly on a scene dominated by
    one colour, which is worth knowing but is not the case here.

    Scaling is clipped at 2x. An unbounded gain turns a nearly monochrome frame —
    dense fog, or a lens fully covered — into saturated garbage, and those are
    exactly the frames the quality gate is about to reject anyway.
    """
    channels = cv2.split(image.astype(np.float32))
    means = [float(np.mean(channel)) for channel in channels]
    target = float(np.mean(means))

    if target <= 1e-6:
        # An essentially black frame. Any scaling here is noise amplification,
        # and the darkness gate has already flagged it.
        return image

    balanced = []
    for channel, mean in zip(channels, means, strict=True):
        gain = 1.0 if mean <= 1e-6 else min(target / mean, 2.0)
        balanced.append(np.clip(channel * gain, 0, 255))

    return np.asarray(cv2.merge(balanced), dtype=np.uint8)


@dataclass(slots=True)
class ClaheNormalize:
    """CLAHE plus optional white balance, as a pipeline step."""

    clip_limit: float = 2.0
    tile_grid_size: tuple[int, int] = (8, 8)
    white_balance: bool = True
    name: str = "normalize"

    def apply(self, image: Image, ctx: CalibrationContext) -> Image:
        """Equalise contrast, then neutralise the colour cast."""
        _ = ctx
        result = apply_clahe(image, clip_limit=self.clip_limit, tile_grid_size=self.tile_grid_size)
        if self.white_balance:
            result = gray_world_white_balance(result)
        return result

    def describe(self) -> dict[str, Any]:
        """Every parameter that changes the output."""
        return {
            "clip_limit": self.clip_limit,
            "tile_grid_size": list(self.tile_grid_size),
            "white_balance": self.white_balance,
        }
