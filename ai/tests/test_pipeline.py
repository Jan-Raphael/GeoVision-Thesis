"""The pipeline: shape, determinism, config, and the fingerprint.

The determinism and fingerprint tests are the ones that matter. Train/serve skew
is this module's whole reason for existing, and it never announces itself — the
test set stays excellent while production accuracy quietly collapses. These tests
are the only thing standing between a config edit and that outcome.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai.preprocessing.errors import ConfigError, DecodeError
from ai.preprocessing.pipeline import (
    DEFAULT_CONFIG_PATH,
    PreprocessingPipeline,
    decode,
    load_image,
)
from ai.preprocessing.quality import QualityGate
from ai.preprocessing.resize import LetterboxResize
from ai.preprocessing.types import CalibrationContext, Image

DETECTOR_CONFIG = DEFAULT_CONFIG_PATH.parent / "preprocessing_detector.yaml"


@pytest.fixture
def pipeline() -> PreprocessingPipeline:
    """The packaged classifier pipeline."""
    return PreprocessingPipeline.from_config()


class TestOutputShape:
    """Vault testing procedure #1."""

    @pytest.mark.parametrize(
        ("width", "height"),
        [(640, 480), (480, 640), (512, 512), (1600, 1200), (100, 700)],
    )
    def test_output_is_always_224_square_uint8(
        self,
        width: int,
        height: int,
        pipeline: PreprocessingPipeline,
        make_site_photo: Callable[..., Image],
    ) -> None:
        result = pipeline.run(make_site_photo(width, height))

        assert result.image.shape == (224, 224, 3)
        assert result.image.dtype == np.uint8

    def test_the_detector_config_produces_640(self, make_site_photo: Callable[..., Image]) -> None:
        detector = PreprocessingPipeline.from_config(DETECTOR_CONFIG)
        assert detector.run(make_site_photo()).image.shape == (640, 640, 3)

    def test_aspect_ratio_is_preserved_by_padding(
        self, pipeline: PreprocessingPipeline, make_site_photo: Callable[..., Image]
    ) -> None:
        """Letterbox, never stretch.

        A 2:1 input squashed into a square would make the building twice as tall
        relative to its width, and the model would learn that shape. Padding
        leaves matching bars top and bottom, which is what this checks.
        """
        result = pipeline.run(make_site_photo(640, 320))
        image = result.image

        top_band = image[:20].mean(axis=(0, 1))
        bottom_band = image[-20:].mean(axis=(0, 1))
        assert np.allclose(top_band, bottom_band, atol=12)


class TestDeterminism:
    """Vault testing procedure #2 — the single most important property here."""

    def test_two_runs_are_byte_identical(
        self, pipeline: PreprocessingPipeline, site_photo: Image
    ) -> None:
        first = pipeline.run(site_photo)
        second = pipeline.run(site_photo)

        assert np.array_equal(first.image, second.image)

    def test_a_freshly_built_pipeline_agrees(self, site_photo: Image) -> None:
        """Determinism must survive process restarts, not just repeat calls.

        Training and serving are different processes. A pipeline that agreed with
        itself in one process but not across two would be exactly the skew this
        module exists to prevent.
        """
        first = PreprocessingPipeline.from_config().run(site_photo)
        second = PreprocessingPipeline.from_config().run(site_photo)

        assert np.array_equal(first.image, second.image)

    def test_the_input_array_is_not_mutated(
        self, pipeline: PreprocessingPipeline, site_photo: Image
    ) -> None:
        """The caller may still need the original — to store it, or to hash it."""
        original = site_photo.copy()
        pipeline.run(site_photo)

        assert np.array_equal(site_photo, original)


class TestFingerprint:
    """Skew detection: Module 07 records this, Module 09 verifies it."""

    def test_it_is_stable_across_instances(self) -> None:
        assert (
            PreprocessingPipeline.from_config().fingerprint
            == PreprocessingPipeline.from_config().fingerprint
        )

    def test_it_changes_when_a_parameter_changes(self, tmp_path: Path) -> None:
        """A clip_limit edit after training must not go unnoticed."""
        baseline = PreprocessingPipeline.from_config().fingerprint
        altered = _config_variant(tmp_path, "normalize", {"clip_limit": 3.5})

        assert PreprocessingPipeline.from_config(altered).fingerprint != baseline

    def test_it_changes_when_a_step_is_disabled(self, tmp_path: Path) -> None:
        """Disabling denoise is a different pipeline, and must say so."""
        baseline = PreprocessingPipeline.from_config().fingerprint
        without = _disable_step(tmp_path, "denoise")

        assert PreprocessingPipeline.from_config(without).fingerprint != baseline

    def test_it_changes_when_the_order_changes(self, tmp_path: Path) -> None:
        """Denoise-then-resize and resize-then-denoise are not the same pipeline.

        The whole ADR-024 argument rests on being able to tell them apart.
        """
        baseline = PreprocessingPipeline.from_config().fingerprint
        document = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        steps = document["steps"]
        resize_at = next(i for i, s in enumerate(steps) if s["name"] == "resize")
        denoise_at = next(i for i, s in enumerate(steps) if s["name"] == "denoise")
        steps[resize_at], steps[denoise_at] = steps[denoise_at], steps[resize_at]

        swapped = tmp_path / "swapped.yaml"
        swapped.write_text(yaml.safe_dump(document), encoding="utf-8")

        assert PreprocessingPipeline.from_config(swapped).fingerprint != baseline

    def test_classifier_and_detector_differ(self) -> None:
        """Different targets, different pipelines, different fingerprints."""
        assert (
            PreprocessingPipeline.from_config().fingerprint
            != PreprocessingPipeline.from_config(DETECTOR_CONFIG).fingerprint
        )

    def test_yaml_and_python_construction_agree(self) -> None:
        """A list from YAML and a tuple in Python must not fingerprint apart.

        Without the coercion in ``_coerce_tuples`` they would, and the same
        pipeline built two ways would appear to be two pipelines.
        """
        from_yaml = PreprocessingPipeline.from_config()
        rebuilt = PreprocessingPipeline(steps=from_yaml.steps)

        assert rebuilt.fingerprint == from_yaml.fingerprint

    def test_it_is_short_enough_to_read_in_a_log(self) -> None:
        assert len(PreprocessingPipeline.from_config().fingerprint) == 16

    def test_the_result_carries_it(
        self, pipeline: PreprocessingPipeline, site_photo: Image
    ) -> None:
        assert pipeline.run(site_photo).fingerprint == pipeline.fingerprint


class TestConfig:
    """A typo must fail at construction, not silently skip a step."""

    def test_an_unknown_step_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "bad.yaml"
        config.write_text("steps:\n  - name: sharpen\n", encoding="utf-8")

        with pytest.raises(ConfigError, match="unknown step 'sharpen'"):
            PreprocessingPipeline.from_config(config)

    def test_a_bad_parameter_is_refused(self, tmp_path: Path) -> None:
        """Better than an hour of training through a misconfigured pipeline."""
        config = tmp_path / "bad.yaml"
        config.write_text("steps:\n  - name: resize\n    widht: 224\n", encoding="utf-8")

        with pytest.raises(ConfigError, match="bad parameters"):
            PreprocessingPipeline.from_config(config)

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="no preprocessing config"):
            PreprocessingPipeline.from_config(tmp_path / "nope.yaml")

    def test_malformed_yaml_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "bad.yaml"
        config.write_text("steps: [\n  broken", encoding="utf-8")

        with pytest.raises(ConfigError, match="not valid YAML"):
            PreprocessingPipeline.from_config(config)

    def test_a_config_with_no_steps_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "empty.yaml"
        config.write_text("steps:\n  - name: resize\n    enabled: false\n", encoding="utf-8")

        with pytest.raises(ConfigError, match="nothing to do"):
            PreprocessingPipeline.from_config(config)

    def test_disabling_a_step_removes_it(self, tmp_path: Path) -> None:
        """The ablation study is a config change, never a code change."""
        without = PreprocessingPipeline.from_config(_disable_step(tmp_path, "denoise"))

        assert "denoise" not in [step.name for step in without.steps]

    def test_the_packaged_config_matches_the_documented_order(
        self, pipeline: PreprocessingPipeline
    ) -> None:
        """Pinned deliberately: reordering these is ADR-024 territory."""
        assert [step.name for step in pipeline.steps] == [
            "quality_gate",
            "perspective_rectify",
            "normalize",
            "resize",
            "denoise",
        ]

    def test_thresholds_are_not_restated_in_yaml(self) -> None:
        """They default to ai/progress/constants.py — their definition site.

        Setting them in the config would create a second one, which is how the
        thesis and the code end up disagreeing.
        """
        document = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        gate = next(s for s in document["steps"] if s["name"] == "quality_gate")

        assert set(gate) <= {"name", "enabled"}


class TestDecoding:
    """Vault testing procedure #8."""

    def test_a_real_jpeg_decodes(
        self, site_photo: Image, encode_jpeg: Callable[..., bytes]
    ) -> None:
        assert decode(encode_jpeg(site_photo)).shape == site_photo.shape

    def test_truncated_bytes_raise_rather_than_segfault(
        self, site_photo: Image, encode_jpeg: Callable[..., bytes]
    ) -> None:
        """OpenCV returns None here; that surfaces later as an AttributeError
        pointing at the wrong module."""
        with pytest.raises(DecodeError):
            decode(encode_jpeg(site_photo)[:64])

    def test_empty_bytes_raise(self) -> None:
        with pytest.raises(DecodeError, match="empty"):
            decode(b"")

    def test_non_image_bytes_raise(self) -> None:
        with pytest.raises(DecodeError):
            decode(b"this is not an image, it is a sentence" * 40)

    def test_a_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DecodeError, match="no such image"):
            load_image(tmp_path / "absent.jpg")

    def test_run_bytes_goes_end_to_end(
        self,
        pipeline: PreprocessingPipeline,
        site_photo: Image,
        encode_jpeg: Callable[..., bytes],
    ) -> None:
        result = pipeline.run_bytes(encode_jpeg(site_photo))

        assert result.image.shape == (224, 224, 3)
        assert result.quality.passed


class TestResult:
    """What one pass reports."""

    def test_quality_is_reported_not_raised(
        self, pipeline: PreprocessingPipeline, make_site_photo: Callable[..., Image]
    ) -> None:
        """A rejected frame is still processed to completion.

        Inference marks it rejected; the dataset audit counts it. Raising would
        force both callers into exception handling for a normal outcome.
        """
        import cv2

        dark = (make_site_photo().astype(np.float32) * 0.05).astype(np.uint8)
        result = pipeline.run(cv2.GaussianBlur(dark, (31, 31), 0))

        assert not result.quality.passed
        assert result.image.shape == (224, 224, 3)

    def test_timings_cover_every_step(
        self, pipeline: PreprocessingPipeline, site_photo: Image
    ) -> None:
        result = pipeline.run(site_photo)

        assert [t.name for t in result.timings] == [s.name for s in pipeline.steps]
        assert result.total_ms > 0

    def test_debug_frames_are_off_by_default(
        self, pipeline: PreprocessingPipeline, site_photo: Image
    ) -> None:
        """One full-resolution array per step is wasteful across a training run."""
        assert pipeline.run(site_photo).debug_frames == ()

    def test_debug_frames_capture_each_step(
        self, pipeline: PreprocessingPipeline, site_photo: Image
    ) -> None:
        result = pipeline.run(site_photo, debug=True)

        assert len(result.debug_frames) == len(pipeline.steps)

    def test_a_pipeline_without_a_gate_reports_a_pass(self, site_photo: Image) -> None:
        """So callers never have to branch on the report being absent."""
        pipeline = PreprocessingPipeline(steps=(LetterboxResize(),))

        assert pipeline.run(site_photo).quality.passed

    def test_quality_is_measured_on_the_original(
        self, pipeline: PreprocessingPipeline, site_photo: Image
    ) -> None:
        """Not on the 224x224 output.

        Blur variance is scale-dependent, so measuring after the resize would
        make a photograph's score depend on pipeline settings and render the
        dataset audit meaningless.
        """
        from ai.preprocessing.quality import blur_score

        result = pipeline.run(site_photo)

        assert result.quality.blur_score == pytest.approx(blur_score(site_photo))

    def test_describe_documents_the_whole_pipeline(self, pipeline: PreprocessingPipeline) -> None:
        """This goes in the thesis appendix and the checkpoint metadata."""
        described = pipeline.describe()

        assert described["fingerprint"] == pipeline.fingerprint
        assert len(described["steps"]) == len(pipeline.steps)
        assert all("params" in step for step in described["steps"])


class TestCalibrationIsOptional:
    """An uncalibrated camera must still work."""

    def test_no_calibration_still_processes(
        self, pipeline: PreprocessingPipeline, site_photo: Image
    ) -> None:
        assert pipeline.run(site_photo, CalibrationContext()).image.shape == (224, 224, 3)

    def test_omitting_the_context_entirely_works(
        self, pipeline: PreprocessingPipeline, site_photo: Image
    ) -> None:
        assert pipeline.run(site_photo).image.shape == (224, 224, 3)

    def test_the_gate_is_reused_safely_across_runs(
        self, pipeline: PreprocessingPipeline, make_site_photo: Callable[..., Image]
    ) -> None:
        """The gate holds its last report as mutable state.

        Two runs must not report each other's scores — which would silently
        attach one image's quality to another's row.
        """
        import cv2

        good = make_site_photo()
        bad = cv2.GaussianBlur(good, (31, 31), 0)

        assert pipeline.run(good).quality.passed
        assert not pipeline.run(bad).quality.passed
        assert pipeline.run(good).quality.passed

    def test_the_gate_step_is_present_in_the_packaged_pipeline(
        self, pipeline: PreprocessingPipeline
    ) -> None:
        assert any(isinstance(step, QualityGate) for step in pipeline.steps)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _config_variant(tmp_path: Path, step_name: str, overrides: dict) -> Path:
    """Copy the packaged config, overriding one step's parameters."""
    document = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    for step in document["steps"]:
        if step["name"] == step_name:
            step.update(overrides)
    path = tmp_path / f"{step_name}_variant.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def _disable_step(tmp_path: Path, step_name: str) -> Path:
    """Copy the packaged config with one step switched off."""
    return _config_variant(tmp_path, step_name, {"enabled": False})
