"""Building the homography a device stores.

An operator opens one reference frame in the dashboard, clicks the four corners
of the façade, and this turns those clicks into the 3x3 matrix written to
``devices.homography``. Module 12 builds that UI; this is the maths behind it,
kept here so it is unit-testable without a browser.

The output is plain nested lists, not a numpy array, because it travels to the
database as JSON and back. Keeping the serialisation boundary explicit avoids the
usual accident where a numpy float32 reaches ``json.dumps`` and raises.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from ai.preprocessing.errors import ConfigError

__all__ = [
    "homography_from_corners",
    "homography_from_json",
    "homography_to_json",
    "order_corners",
]

#: Minimum separation, in pixels, between any two clicked corners. Four clicks
#: within a few pixels of each other produce a numerically unstable matrix that
#: warps the frame into noise, and the operator gets no feedback that they
#: mis-clicked.
MIN_CORNER_SEPARATION = 10.0


def order_corners(points: NDArray[np.float32]) -> NDArray[np.float32]:
    """Sort four arbitrary clicks into top-left, top-right, bottom-right, bottom-left.

    An operator clicks in whatever order feels natural. Feeding those raw to
    ``getPerspectiveTransform`` produces a matrix that mirrors or rotates the
    façade depending on click order — and it does so without error, which is the
    worst kind of bug: the calibration "works", and every subsequent capture from
    that camera is flipped.

    Ordered by coordinate sums and differences: top-left has the smallest ``x+y``,
    bottom-right the largest; top-right has the smallest ``y-x``, bottom-left the
    largest.
    """
    ordered = np.zeros((4, 2), dtype=np.float32)
    coordinate_sum = points.sum(axis=1)
    coordinate_diff = np.diff(points, axis=1).ravel()

    ordered[0] = points[np.argmin(coordinate_sum)]  # top-left
    ordered[2] = points[np.argmax(coordinate_sum)]  # bottom-right
    ordered[1] = points[np.argmin(coordinate_diff)]  # top-right
    ordered[3] = points[np.argmax(coordinate_diff)]  # bottom-left
    return ordered


def homography_from_corners(
    corners: list[tuple[float, float]] | NDArray[np.float32],
    *,
    output_size: tuple[int, int] | None = None,
) -> NDArray[np.float64]:
    """Build the transform mapping four clicked corners onto a rectangle.

    Args:
        corners: The four façade corners in the reference frame, any order.
        output_size: ``(width, height)`` of the canonical rectangle. Defaults to
            the bounding box of the clicked quadrilateral, which preserves the
            façade's real aspect ratio instead of imposing an arbitrary one.

    Returns:
        A 3x3 float64 homography.

    Raises:
        ConfigError: If there are not exactly four corners, or they are too close
            together to define a stable transform.
    """
    points = np.asarray(corners, dtype=np.float32)
    if points.shape != (4, 2):
        msg = f"expected exactly 4 (x, y) corners, got shape {points.shape}"
        raise ConfigError(msg)

    ordered = order_corners(points)
    _reject_degenerate(ordered)

    if output_size is None:
        # Use the longer of each opposing pair, so the rectangle is at least as
        # large as the façade in both axes and nothing is lost to downscaling.
        width = max(_distance(ordered[0], ordered[1]), _distance(ordered[3], ordered[2]))
        height = max(_distance(ordered[0], ordered[3]), _distance(ordered[1], ordered[2]))
        output_size = (max(1, round(width)), max(1, round(height)))

    target_width, target_height = output_size
    destination = np.array(
        [
            [0, 0],
            [target_width - 1, 0],
            [target_width - 1, target_height - 1],
            [0, target_height - 1],
        ],
        dtype=np.float32,
    )

    matrix = cv2.getPerspectiveTransform(ordered, destination)
    return np.asarray(matrix, dtype=np.float64)


def homography_to_json(matrix: NDArray[np.float64]) -> dict[str, Any]:
    """Serialise a homography for ``devices.homography``.

    Versioned so that a future change to the representation can be detected
    rather than silently misread as the current one.
    """
    return {"version": 1, "matrix": np.asarray(matrix, dtype=np.float64).tolist()}


def homography_from_json(document: dict[str, Any] | None) -> NDArray[np.float64] | None:
    """Read a homography back out of the database.

    Returns ``None`` for a missing or unusable value rather than raising: an
    uncalibrated or badly-calibrated camera should degrade to "no rectification",
    not stop its captures being processed.
    """
    if not document:
        return None
    raw = document.get("matrix")
    if raw is None:
        return None
    try:
        matrix = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    return matrix if matrix.shape == (3, 3) else None


def _distance(first: NDArray[np.float32], second: NDArray[np.float32]) -> float:
    """Euclidean distance between two points."""
    return float(np.linalg.norm(first - second))


def _reject_degenerate(ordered: NDArray[np.float32]) -> None:
    """Raise if any two corners are too close to define a stable transform.

    Raises:
        ConfigError: If two corners are within :data:`MIN_CORNER_SEPARATION`.
    """
    for index in range(4):
        for other in range(index + 1, 4):
            if _distance(ordered[index], ordered[other]) < MIN_CORNER_SEPARATION:
                msg = (
                    "calibration corners are too close together to define a "
                    "stable transform - click the four corners of the façade"
                )
                raise ConfigError(msg)
