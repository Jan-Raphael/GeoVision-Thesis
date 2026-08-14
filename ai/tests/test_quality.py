"""The quality gate.

These matter more than they look. Everything the gate lets through gets a
confident prediction attached to it, and that prediction flows into a progress
percentage a homeowner may act on. A gate that is too permissive is worse than no
gate, because it launders a bad frame into a number that carries no visible
uncertainty.
"""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np
import pytest

from ai.preprocessing.quality import (
    QualityFlag,
    QualityGate,
    assess,
    blur_score,
    brightness,
    occlusion_ratio,
)
from ai.preprocessing.types import CalibrationContext, Image
from ai.progress.constants import (
    BLUR_THRESHOLD,
    DARKNESS_THRESHOLD,
    OCCLUSION_MAX_RATIO,
)


class TestBlur:
    """Vault testing procedure #3."""

    def test_a_sharp_frame_passes(self, site_photo: Image) -> None:
        assert assess(site_photo).passed

    def test_a_gaussian_blurred_frame_is_rejected(self, site_photo: Image) -> None:
        """The defocus case: a camera whose lens has drifted out of focus."""
        blurred = cv2.GaussianBlur(site_photo, (31, 31), 0)
        report = assess(blurred)

        assert not report.passed
        assert QualityFlag.BLURRY in report.flags
        assert report.blur_score < BLUR_THRESHOLD

    def test_a_motion_blurred_frame_is_rejected(self, site_photo: Image) -> None:
        """The wind case: a pole-mounted camera shaken during exposure."""
        kernel = np.zeros((25, 25), dtype=np.float32)
        kernel[12, :] = 1.0 / 25.0
        smeared = cv2.filter2D(site_photo, -1, kernel)

        assert QualityFlag.BLURRY in assess(smeared).flags

    def test_blur_score_orders_correctly(self, site_photo: Image) -> None:
        """Blurring more must always score lower, or the metric is not usable."""
        scores = [blur_score(cv2.GaussianBlur(site_photo, (size, size), 0)) for size in (3, 11, 31)]
        assert scores == sorted(scores, reverse=True)


class TestDarkness:
    """Vault testing procedure #4."""

    def test_a_dark_frame_is_rejected(self, site_photo: Image) -> None:
        """The 18:00 capture that fired after sunset."""
        dark = (site_photo.astype(np.float32) * 0.10).astype(np.uint8)
        report = assess(dark)

        assert not report.passed
        assert QualityFlag.TOO_DARK in report.flags
        assert report.brightness < DARKNESS_THRESHOLD

    def test_a_normally_exposed_frame_is_not_flagged(self, site_photo: Image) -> None:
        assert QualityFlag.TOO_DARK not in assess(site_photo).flags

    def test_brightness_uses_perceptual_lightness(self) -> None:
        """L, not a mean over BGR.

        A saturated blue fills one channel and leaves two near zero, so a naive
        BGR mean reads it as dark. It is not dark, and rejecting a photograph for
        having a blue sky in it would be absurd.
        """
        blue = np.zeros((64, 64, 3), dtype=np.uint8)
        blue[:, :, 0] = 255

        assert float(np.mean(blue)) < DARKNESS_THRESHOLD * 4
        assert brightness(blue) > DARKNESS_THRESHOLD


class TestOcclusion:
    """Vault testing procedure #5."""

    def test_a_clear_facade_is_not_flagged(
        self, site_photo: Image, facade_roi: CalibrationContext
    ) -> None:
        report = assess(site_photo, facade_roi)

        assert QualityFlag.OCCLUDED not in report.flags
        assert report.occlusion_ratio <= OCCLUSION_MAX_RATIO

    def test_a_large_flat_obstruction_is_rejected(
        self, site_photo: Image, facade_roi: CalibrationContext
    ) -> None:
        """A truck parked in front of the camera, covering ~60 % of the façade.

        Flat and untextured because it is close enough to be out of the depth of
        field, and much darker than the wall behind it — the two properties the
        heuristic requires together.
        """
        occluded = site_photo.copy()
        cv2.rectangle(occluded, (64, 280), (576, 456), (40, 40, 45), -1)
        report = assess(occluded, facade_roi)

        assert not report.passed
        assert QualityFlag.OCCLUDED in report.flags
        assert report.occlusion_ratio > OCCLUSION_MAX_RATIO

    def test_a_totally_blocked_lens_is_still_rejected(
        self, site_photo: Image, facade_roi: CalibrationContext
    ) -> None:
        """The occlusion test alone cannot catch this, and does not have to.

        With the whole ROI covered there is no unobstructed remainder to compare
        against, so the intensity condition finds nothing anomalous. In reality a
        surface pressed against the lens is never in focus, so the blur gate
        takes it — which is why the frame must still be rejected overall.
        """
        blocked = site_photo.copy()
        cv2.rectangle(blocked, (0, 0), (640, 480), (45, 45, 50), -1)
        blocked = cv2.GaussianBlur(blocked, (31, 31), 0)
        report = assess(blocked, facade_roi)

        assert not report.passed
        assert QualityFlag.BLURRY in report.flags

    def test_a_small_obstruction_is_tolerated(
        self, site_photo: Image, facade_roi: CalibrationContext
    ) -> None:
        """One worker in frame must not throw away the whole capture."""
        partial = site_photo.copy()
        cv2.rectangle(partial, (60, 380), (170, 460), (40, 40, 45), -1)

        assert QualityFlag.OCCLUDED not in assess(partial, facade_roi).flags

    def test_no_roi_means_no_occlusion_check(self, site_photo: Image) -> None:
        """An uncalibrated camera must not have every frame rejected."""
        blocked = site_photo.copy()
        blocked[:, :] = (40, 40, 45)

        assert occlusion_ratio(blocked, CalibrationContext()) == 0.0

    def test_a_degenerate_polygon_does_not_divide_by_zero(self, site_photo: Image) -> None:
        """A bad calibration must not reject every subsequent capture."""
        collinear = CalibrationContext(
            roi_polygon=np.array([[0, 0], [10, 0], [20, 0]], dtype=np.int32)
        )
        assert occlusion_ratio(site_photo, collinear) == 0.0


class TestReport:
    """What the gate hands back."""

    def test_scores_are_kept_even_when_the_frame_passes(self, site_photo: Image) -> None:
        """The dataset audit needs the distribution, not just the count."""
        report = assess(site_photo)

        assert report.passed
        assert report.blur_score > 0
        assert report.brightness > 0

    def test_multiple_failures_are_all_reported(self, site_photo: Image) -> None:
        """Fixing only the first problem would leave the frame still rejected."""
        bad = cv2.GaussianBlur((site_photo.astype(np.float32) * 0.08).astype(np.uint8), (31, 31), 0)
        report = assess(bad)

        assert QualityFlag.BLURRY in report.flags
        assert QualityFlag.TOO_DARK in report.flags

    def test_reason_is_none_when_passing(self, site_photo: Image) -> None:
        assert assess(site_photo).reason is None

    def test_as_dict_is_json_safe(self, site_photo: Image) -> None:
        """It is stored on the image row as JSON."""
        import json

        payload = assess(site_photo).as_dict()
        assert json.loads(json.dumps(payload))["passed"] is True

    def test_thresholds_come_from_the_shared_constants(self) -> None:
        """Re-typing a threshold here is how the thesis and the code diverge."""
        gate = QualityGate()

        assert gate.blur_threshold == BLUR_THRESHOLD
        assert gate.darkness_threshold == DARKNESS_THRESHOLD
        assert gate.occlusion_max_ratio == OCCLUSION_MAX_RATIO

    def test_the_gate_does_not_modify_the_image(self, site_photo: Image) -> None:
        """It measures; it does not transform."""
        gate = QualityGate()
        result = gate.apply(site_photo, CalibrationContext())

        assert np.array_equal(result, site_photo)

    @pytest.mark.parametrize("scale", [0.5, 1.0, 2.0])
    def test_the_same_scene_scores_consistently_across_sizes(
        self, scale: float, make_site_photo: Callable[..., Image]
    ) -> None:
        """Not identical - blur variance is scale-dependent by nature - but the
        verdict must not flip, or the gate would depend on camera resolution."""
        photo = make_site_photo(int(640 * scale), int(480 * scale))
        assert assess(photo).passed
