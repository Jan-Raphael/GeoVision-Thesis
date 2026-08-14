"""The individual transform steps.

Each is tested for the property it exists to provide, and — where the obvious
implementation would have been wrong — for the specific mistake it avoids. CLAHE
applied per-RGB-channel and a stretched resize both *work*; they just quietly
ruin the data.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import cv2
import numpy as np
import pytest

from ai.preprocessing.calibration import (
    homography_from_corners,
    homography_from_json,
    homography_to_json,
    order_corners,
)
from ai.preprocessing.denoise import bilateral_denoise
from ai.preprocessing.errors import ConfigError
from ai.preprocessing.normalize import apply_clahe, gray_world_white_balance
from ai.preprocessing.perspective import rectify
from ai.preprocessing.resize import PAD_VALUE, letterbox
from ai.preprocessing.types import Image


class TestClahe:
    """Vault testing procedure #7."""

    @staticmethod
    def _low_contrast(size: int = 240) -> Image:
        """A washed-out frame: the 16:00 haze case."""
        base = np.full((size, size, 3), 128, dtype=np.uint8)
        cv2.rectangle(base, (40, 40), (200, 200), (138, 138, 138), -1)
        cv2.rectangle(base, (80, 80), (160, 160), (120, 120, 120), -1)
        return base

    def test_contrast_increases(self) -> None:
        """The point of the step: recover detail from a flat frame."""
        image = self._low_contrast()
        before = float(cv2.cvtColor(image, cv2.COLOR_BGR2LAB)[:, :, 0].std())
        after = float(cv2.cvtColor(apply_clahe(image), cv2.COLOR_BGR2LAB)[:, :, 0].std())

        assert after > before

    def test_it_does_not_blow_out_the_highlights(self, site_photo: Image) -> None:
        """Contrast-*limited* is the whole distinction from plain equalisation.

        Plain histogram equalisation on a site photograph drives the sky to pure
        white and the shadowed façade to pure black, destroying exactly the
        detail this step is supposed to recover.
        """
        result = apply_clahe(site_photo)
        saturated = float(np.count_nonzero(result >= 254) / result.size)

        assert saturated < 0.02

    def test_hue_is_preserved(self) -> None:
        """L channel only.

        Running CLAHE per BGR channel equalises each colour independently, which
        changes their ratios and therefore the hue — concrete comes out green.
        This is the test that would fail if somebody "simplified" the LAB
        round-trip away.
        """
        image = np.zeros((120, 120, 3), dtype=np.uint8)
        image[:, :60] = (60, 90, 170)  # a warm brick tone
        image[:, 60:] = (150, 120, 80)  # a cool shadow tone

        before = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 0].astype(np.int16)
        after = cv2.cvtColor(apply_clahe(image), cv2.COLOR_BGR2HSV)[:, :, 0].astype(np.int16)

        assert np.median(np.abs(after - before)) <= 3

    def test_it_is_deterministic(self, site_photo: Image) -> None:
        assert np.array_equal(apply_clahe(site_photo), apply_clahe(site_photo))

    def test_output_stays_uint8(self, site_photo: Image) -> None:
        assert apply_clahe(site_photo).dtype == np.uint8


class TestWhiteBalance:
    """Correcting the 07:00 warm cast and the open-shade blue one."""

    def test_a_colour_cast_is_reduced(self, site_photo: Image) -> None:
        warm = np.clip(
            site_photo.astype(np.float32) * np.array([0.75, 1.0, 1.30], dtype=np.float32),
            0,
            255,
        ).astype(np.uint8)

        def spread(image: Image) -> float:
            return float(np.ptp([float(np.mean(image[:, :, c])) for c in range(3)]))

        assert spread(gray_world_white_balance(warm)) < spread(warm)

    def test_a_neutral_frame_is_left_alone(self) -> None:
        """It must not invent a correction where there is no cast."""
        neutral = np.full((80, 80, 3), 140, dtype=np.uint8)
        result = gray_world_white_balance(neutral)

        assert np.allclose(result, neutral, atol=2)

    def test_a_black_frame_does_not_explode(self) -> None:
        """Unbounded gain on a near-zero mean produces saturated garbage."""
        black = np.zeros((60, 60, 3), dtype=np.uint8)

        assert np.array_equal(gray_world_white_balance(black), black)

    def test_gain_is_clipped(self) -> None:
        """A nearly monochrome frame must not be amplified into noise."""
        mostly_blue = np.zeros((60, 60, 3), dtype=np.uint8)
        mostly_blue[:, :, 0] = 200
        mostly_blue[:, :, 1] = 2
        mostly_blue[:, :, 2] = 2

        result = gray_world_white_balance(mostly_blue)
        assert result.max() <= 255
        assert float(np.mean(result[:, :, 1])) <= 2 * 2 + 1


class TestLetterbox:
    """Vault testing procedure #1, and the reason padding is not optional."""

    @pytest.mark.parametrize(("width", "height"), [(640, 480), (480, 640), (300, 300), (1920, 200)])
    def test_output_is_exactly_the_target(self, width: int, height: int) -> None:
        image = np.full((height, width, 3), 120, dtype=np.uint8)

        assert letterbox(image, (224, 224)).shape == (224, 224, 3)

    def test_a_square_input_needs_no_padding(self) -> None:
        image = np.full((300, 300, 3), 120, dtype=np.uint8)
        result = letterbox(image, (224, 224))

        assert not np.any(np.all(result == PAD_VALUE, axis=2))

    def test_a_wide_input_is_padded_top_and_bottom(self) -> None:
        image = np.full((200, 800, 3), 120, dtype=np.uint8)
        result = letterbox(image, (224, 224))

        assert np.all(result[0] == PAD_VALUE)
        assert np.all(result[-1] == PAD_VALUE)
        assert not np.all(result[112] == PAD_VALUE)

    def test_padding_is_centred(self) -> None:
        """An off-centre building is a systematic bias the model would learn."""
        image = np.full((200, 800, 3), 120, dtype=np.uint8)
        result = letterbox(image, (224, 224))

        top = int(np.argmax(~np.all(result == PAD_VALUE, axis=(1, 2))))
        flipped = result[::-1]
        bottom = int(np.argmax(~np.all(flipped == PAD_VALUE, axis=(1, 2))))

        assert abs(top - bottom) <= 1

    def test_aspect_ratio_is_not_distorted(self) -> None:
        """A circle must stay a circle.

        Stretching would make it an ellipse, and a model trained on stretched
        buildings mispredicts the moment a camera is mounted differently.
        """
        image = np.zeros((400, 800, 3), dtype=np.uint8)
        cv2.circle(image, (400, 200), 150, (255, 255, 255), -1)
        result = letterbox(image, (224, 224))

        white = np.argwhere(np.all(result > 200, axis=2))
        extent_y = int(np.ptp(white[:, 0]))
        extent_x = int(np.ptp(white[:, 1]))

        assert abs(extent_x - extent_y) <= 3

    def test_an_extreme_panorama_does_not_round_to_zero(self) -> None:
        """cv2.resize raises on a zero dimension; clamping avoids the crash."""
        image = np.full((10, 4000, 3), 120, dtype=np.uint8)

        assert letterbox(image, (224, 224)).shape == (224, 224, 3)

    def test_the_pad_value_is_neutral_grey(self) -> None:
        """Black becomes a strong negative after ImageNet normalisation, which a
        first conv layer reads as a real edge along the padding boundary."""
        assert PAD_VALUE == (114, 114, 114)

    def test_it_is_deterministic(self, site_photo: Image) -> None:
        assert np.array_equal(letterbox(site_photo), letterbox(site_photo))


class TestDenoise:
    """Smooth the noise, keep the edges."""

    def test_noise_is_reduced(self, make_site_photo: Callable[..., Image]) -> None:
        clean = np.full((200, 200, 3), 130, dtype=np.uint8)
        rng = np.random.default_rng(11)
        noisy = np.clip(clean.astype(np.float32) + rng.normal(0, 18, clean.shape), 0, 255).astype(
            np.uint8
        )

        before = float(np.abs(noisy.astype(np.float32) - 130).mean())
        after = float(np.abs(bilateral_denoise(noisy).astype(np.float32) - 130).mean())

        assert after < before

    def test_edges_survive(self) -> None:
        """The reason it is bilateral and not Gaussian.

        A Gaussian blur strong enough to remove sensor noise also softens the
        formwork and scaffolding lines the classifier depends on.
        """
        image = np.full((200, 200, 3), 60, dtype=np.uint8)
        image[:, 100:] = 200

        denoised = bilateral_denoise(image)
        gaussian = cv2.GaussianBlur(image, (9, 9), 0)

        def edge_strength(sample: Image) -> float:
            grey = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY).astype(np.float32)
            return float(np.abs(np.diff(grey[100])).max())

        assert edge_strength(denoised) > edge_strength(gaussian)

    def test_it_is_deterministic(self, site_photo: Image) -> None:
        assert np.array_equal(bilateral_denoise(site_photo), bilateral_denoise(site_photo))


class TestPerspective:
    """Vault testing procedure #6."""

    @staticmethod
    def _checkerboard(size: int = 400, squares: int = 8) -> Image:
        """A square checkerboard, photographed head-on."""
        board = np.zeros((size, size, 3), dtype=np.uint8)
        step = size // squares
        for row in range(squares):
            for col in range(squares):
                if (row + col) % 2 == 0:
                    board[row * step : (row + 1) * step, col * step : (col + 1) * step] = 235
        return board

    def test_an_angled_board_rectifies_back_to_square(self) -> None:
        """Photograph a square at an angle, then undo it.

        The corners must land within a couple of pixels of where they started —
        this is the property every downstream progress comparison between two
        cameras depends on.
        """
        board = self._checkerboard()
        source = np.array([[0, 0], [399, 0], [399, 399], [0, 399]], dtype=np.float32)
        skewed_corners = np.array([[40, 15], [360, 60], [375, 350], [25, 385]], dtype=np.float32)

        forward = cv2.getPerspectiveTransform(source, skewed_corners)
        photographed = cv2.warpPerspective(board, forward, (400, 400))

        recovered = homography_from_corners(skewed_corners, output_size=(400, 400))
        rectified = rectify(photographed, recovered, output_size=(400, 400))

        assert rectified.shape == (400, 400, 3)

        # Sample the centre of every square on the 8x8 grid. If the geometry was
        # recovered, they alternate light/dark exactly as the original does.
        # (Column *means* would not show this - a checkerboard column contains
        # equal light and dark, so every column averages to the same grey.)
        grey = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
        step = 400 // 8
        for row in range(8):
            for col in range(8):
                centre = grey[row * step + step // 2, col * step + step // 2]
                if (row + col) % 2 == 0:
                    assert centre > 180, f"square ({row},{col}) should be light"
                else:
                    assert centre < 75, f"square ({row},{col}) should be dark"

    def test_no_homography_is_a_no_op(self, site_photo: Image) -> None:
        """Cameras run uncalibrated for their first days on site."""
        assert np.array_equal(rectify(site_photo, None), site_photo)

    def test_a_malformed_homography_is_refused(self, site_photo: Image) -> None:
        with pytest.raises(ConfigError, match="3x3"):
            rectify(site_photo, np.eye(4))

    def test_identity_leaves_the_image_essentially_unchanged(self, site_photo: Image) -> None:
        result = rectify(site_photo, np.eye(3))

        assert np.abs(result.astype(np.int16) - site_photo.astype(np.int16)).mean() < 1.0


class TestCalibration:
    """Turning four clicks into the matrix stored on the device."""

    CORNERS: ClassVar[list[tuple[float, float]]] = [
        (40.0, 15.0),
        (360.0, 60.0),
        (375.0, 350.0),
        (25.0, 385.0),
    ]

    def test_click_order_does_not_matter(self) -> None:
        """An operator clicks in whatever order feels natural.

        Feeding those raw to getPerspectiveTransform mirrors or rotates the
        façade depending on click order — silently. Every capture from that
        camera would then be flipped, with no error anywhere.
        """
        canonical = homography_from_corners(self.CORNERS)
        shuffled = homography_from_corners([self.CORNERS[i] for i in (2, 0, 3, 1)])

        assert np.allclose(canonical, shuffled, atol=1e-6)

    def test_corners_are_ordered_clockwise_from_top_left(self) -> None:
        points = np.array([[10, 10], [90, 12], [88, 95], [12, 92]], dtype=np.float32)
        ordered = order_corners(np.array([points[2], points[0], points[3], points[1]]))

        assert np.allclose(ordered, points)

    def test_too_few_corners_is_refused(self) -> None:
        with pytest.raises(ConfigError, match="exactly 4"):
            homography_from_corners([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)])

    def test_degenerate_clicks_are_refused(self) -> None:
        """Four clicks in the same place produce an unstable matrix that warps
        the frame into noise, with no feedback to the operator."""
        with pytest.raises(ConfigError, match="too close together"):
            homography_from_corners([(10.0, 10.0), (12.0, 11.0), (11.0, 12.0), (10.5, 10.5)])

    def test_json_round_trip(self) -> None:
        """It travels to the database as JSON and back."""
        import json

        matrix = homography_from_corners(self.CORNERS)
        document = homography_to_json(matrix)
        revived = homography_from_json(json.loads(json.dumps(document)))

        assert revived is not None
        assert np.allclose(revived, matrix)

    @pytest.mark.parametrize(
        "document",
        [None, {}, {"version": 1}, {"matrix": "nonsense"}, {"matrix": [[1, 2], [3, 4]]}],
    )
    def test_unusable_stored_values_degrade_to_none(self, document: object) -> None:
        """A bad calibration must mean "no rectification", not "no captures"."""
        assert homography_from_json(document) is None  # type: ignore[arg-type]
