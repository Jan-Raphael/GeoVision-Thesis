"""Aspect-preserving resize with letterbox padding.

**Letterbox, never stretch.** Squashing a 4:3 capture into a 224x224 square makes
the building 33 % wider than it is. A model trained on stretched images learns
those proportions, and the moment a camera is mounted in portrait — or the ESP32
is configured for a different frame size — every prediction shifts. Padding costs
a border of grey pixels and keeps the geometry honest.

Two targets, both driven by config: 224x224 for the ResNet18/MobileNetV3
classifier, 640x640 for YOLOv8.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from ai.preprocessing.types import CalibrationContext, Image

__all__ = ["LetterboxResize", "letterbox"]

#: Neutral mid-grey. Chosen over black because after ImageNet normalisation
#: black becomes a strong negative activation across all three channels, which a
#: convolutional first layer reads as a genuine edge running along the padding
#: boundary. Mid-grey lands near zero and stays quiet.
PAD_VALUE = (114, 114, 114)


def letterbox(
    image: Image,
    size: tuple[int, int] = (224, 224),
    *,
    pad_value: tuple[int, int, int] = PAD_VALUE,
) -> Image:
    """Resize to fit inside *size*, padding the remainder.

    Args:
        image: BGR uint8, any dimensions.
        size: Target ``(width, height)``.
        pad_value: BGR fill for the padding.

    Returns:
        A new image of exactly ``(height, width, 3)``, uint8.
    """
    target_width, target_height = size
    height, width = image.shape[:2]

    scale = min(target_width / width, target_height / height)
    # At least 1px in each dimension: a very wide panorama scaled to fit a square
    # can otherwise round its height to zero, and cv2.resize raises on that.
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))

    # INTER_AREA when shrinking, INTER_LINEAR when growing. INTER_AREA averages
    # over the source region, which is the only interpolation that avoids
    # aliasing on a large downscale - and every real capture is a downscale, from
    # 1600x1200 to 224x224. Using INTER_LINEAR there would sample sparsely and
    # turn scaffolding into moiré.
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (new_width, new_height), interpolation=interpolation)

    pad_width = target_width - new_width
    pad_height = target_height - new_height
    top = pad_height // 2
    left = pad_width // 2

    padded = cv2.copyMakeBorder(
        resized,
        top,
        pad_height - top,
        left,
        pad_width - left,
        cv2.BORDER_CONSTANT,
        value=pad_value,
    )
    return np.asarray(padded, dtype=np.uint8)


@dataclass(slots=True)
class LetterboxResize:
    """Letterbox resize as a pipeline step."""

    width: int = 224
    height: int = 224
    name: str = "resize"

    def apply(self, image: Image, ctx: CalibrationContext) -> Image:
        """Resize and pad to the configured target."""
        _ = ctx
        return letterbox(image, (self.width, self.height))

    def describe(self) -> dict[str, Any]:
        """Every parameter that changes the output."""
        return {"width": self.width, "height": self.height, "pad_value": list(PAD_VALUE)}
