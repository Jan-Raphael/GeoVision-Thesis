"""Shared fixtures for the preprocessing tests.

Images are generated, never committed. A binary fixture in git is one whose
provenance nobody can inspect, and every property these tests assert — sharpness,
brightness, texture, geometry — is far easier to control by construction than to
find in a photograph.

Exposed as *factory* fixtures rather than module-level helpers so tests never
import each other; ``tests/`` is not a package, and making it one just to share
two drawing functions would be the wrong trade.
"""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np
import pytest

from ai.preprocessing.types import CalibrationContext, Image

SitePhotoFactory = Callable[..., Image]


def _draw_site_photo(width: int = 640, height: int = 480, *, seed: int = 3) -> Image:
    """Draw a sharp, mid-brightness scene with plenty of structural edges."""
    rng = np.random.default_rng(seed)
    image = np.full((height, width, 3), 150, dtype=np.uint8)

    cv2.rectangle(
        image,
        (int(width * 0.1), int(height * 0.35)),
        (int(width * 0.9), int(height * 0.95)),
        (120, 118, 115),
        -1,
    )
    for index in range(1, 10):
        x = int(width * 0.1) + index * int(width * 0.08)
        cv2.line(image, (x, int(height * 0.35)), (x, int(height * 0.95)), (85, 83, 80), 2)
    for index in range(1, 6):
        y = int(height * 0.35) + index * int(height * 0.12)
        cv2.line(image, (int(width * 0.1), y), (int(width * 0.9), y), (92, 90, 88), 2)

    noisy = image.astype(np.float32) + rng.normal(0, 4.0, image.shape)
    return np.asarray(np.clip(noisy, 0, 255), dtype=np.uint8)


@pytest.fixture
def make_site_photo() -> SitePhotoFactory:
    """Build a site photo at any size."""
    return _draw_site_photo


@pytest.fixture
def site_photo() -> Image:
    """A 640x480 frame that passes every quality check."""
    return _draw_site_photo()


@pytest.fixture
def facade_roi() -> CalibrationContext:
    """An ROI polygon covering the façade in the standard 640x480 photo."""
    width, height = 640, 480
    polygon = np.array(
        [
            [int(width * 0.1), int(height * 0.35)],
            [int(width * 0.9), int(height * 0.35)],
            [int(width * 0.9), int(height * 0.95)],
            [int(width * 0.1), int(height * 0.95)],
        ],
        dtype=np.int32,
    )
    return CalibrationContext(roi_polygon=polygon)


@pytest.fixture
def encode_jpeg() -> Callable[..., bytes]:
    """Encode an image the way a camera would."""

    def _encode(image: Image, quality: int = 92) -> bytes:
        ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        assert ok, "failed to encode test JPEG"
        return bytes(buffer)

    return _encode
