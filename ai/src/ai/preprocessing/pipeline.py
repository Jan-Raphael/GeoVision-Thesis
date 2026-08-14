"""The preprocessing pipeline: one ordered, configured, fingerprinted sequence.

This module exists to prevent one specific failure. If training preprocesses
images one way and serving preprocesses them another, the model's accuracy on the
test set stays excellent and its accuracy in production quietly collapses — and
nothing anywhere reports an error. Train/serve skew does not raise. It just makes
the system wrong.

Three mechanisms guard against it:

1. **One definition of the order**, in ``ai/configs/preprocessing.yaml``. Training
   and serving both build the pipeline from that file. There is no second place
   the order is written down.

2. **A fingerprint.** :attr:`PreprocessingPipeline.fingerprint` hashes every
   step's name, position, and parameters. Module 07 records it in the checkpoint;
   Module 09 compares it at load time and refuses a mismatch. Skew becomes a
   startup error instead of a silent accuracy loss.

3. **Determinism.** No step in this pipeline may be random. Augmentation is
   training-only and lives in ``ai/data/transforms.py`` (Module 07), downstream of
   everything here.

Usage::

    pipeline = PreprocessingPipeline.from_config("ai/configs/preprocessing.yaml")
    result = pipeline.run(image, ctx)
    if result.quality.passed:
        tensor = to_tensor(result.image)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from ai.preprocessing.denoise import BilateralDenoise
from ai.preprocessing.errors import ConfigError, DecodeError
from ai.preprocessing.normalize import ClaheNormalize
from ai.preprocessing.perspective import PerspectiveRectify
from ai.preprocessing.quality import QualityGate, QualityReport
from ai.preprocessing.resize import LetterboxResize
from ai.preprocessing.types import (
    CalibrationContext,
    Image,
    PipelineDebug,
    PreprocessingStep,
    StepTiming,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "STEP_REGISTRY",
    "PreprocessingPipeline",
    "PreprocessingResult",
    "decode",
    "load_image",
]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "preprocessing.yaml"

#: Maps a config key to its step class. A step absent here cannot be named in
#: the YAML, which is what turns a typo into a startup error rather than a
#: silently skipped stage.
STEP_REGISTRY: dict[str, type] = {
    "quality_gate": QualityGate,
    "perspective_rectify": PerspectiveRectify,
    "normalize": ClaheNormalize,
    "denoise": BilateralDenoise,
    "resize": LetterboxResize,
}


@dataclass(slots=True)
class PreprocessingResult:
    """Everything one pass produced."""

    image: Image
    quality: QualityReport
    timings: tuple[StepTiming, ...] = ()
    fingerprint: str = ""
    #: Per-step frames, populated only when the pipeline was run with `debug=True`.
    debug_frames: tuple[tuple[str, Image], ...] = ()

    @property
    def total_ms(self) -> float:
        """Wall-clock milliseconds across every step."""
        return sum(timing.milliseconds for timing in self.timings)


def decode(data: bytes) -> Image:
    """Decode encoded image bytes into a BGR array.

    Raises:
        DecodeError: If the bytes are not a decodable image.

    OpenCV returns ``None`` for undecodable input rather than raising, which
    surfaces several steps later as an ``AttributeError`` on a ``NoneType``
    shape. Converting it to an explicit error here is the difference between "the
    upload was truncated" and a traceback pointing at the wrong module.
    """
    buffer = np.frombuffer(data, dtype=np.uint8)
    if buffer.size == 0:
        msg = "empty image payload"
        raise DecodeError(msg)

    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        msg = "could not decode image (truncated or not an image)"
        raise DecodeError(msg)
    return np.asarray(image, dtype=np.uint8)


def load_image(path: str | Path) -> Image:
    """Read an image from disk, EXIF-oriented.

    ``cv2.imread`` ignores the EXIF orientation tag, so a photograph taken in
    portrait arrives rotated. Reading the bytes and going through ``imdecode``
    with ``IMREAD_COLOR`` behaves the same way, so orientation is applied
    explicitly below. A fixed site camera never rotates, but the manual-upload
    path in Module 07 accepts phone photographs, which routinely do.

    Raises:
        DecodeError: If the file is missing or undecodable.
    """
    file_path = Path(path)
    if not file_path.is_file():
        msg = f"no such image: {file_path}"
        raise DecodeError(msg)
    return _apply_exif_orientation(decode(file_path.read_bytes()), file_path)


def _apply_exif_orientation(image: Image, path: Path) -> Image:
    """Rotate *image* according to its EXIF orientation tag, if any."""
    try:
        from PIL import Image as PILImage
        from PIL import ImageOps

        with PILImage.open(path) as handle:
            oriented = ImageOps.exif_transpose(handle)
            if oriented is None or oriented.size == handle.size:
                # No tag, or a tag that means "already upright".
                return image
            # PIL is RGB; this pipeline is BGR throughout.
            return np.asarray(
                cv2.cvtColor(np.asarray(oriented.convert("RGB")), cv2.COLOR_RGB2BGR),
                dtype=np.uint8,
            )
    except Exception:
        # A malformed EXIF block must not cost us the image. The pixels decoded
        # fine; only the rotation hint is unreadable.
        return image


@dataclass(slots=True)
class PreprocessingPipeline:
    """An ordered, configured sequence of deterministic steps."""

    steps: tuple[PreprocessingStep, ...]
    #: Where the config came from, for error messages and the demo figure.
    source: str = "(constructed)"
    _fingerprint: str = field(default="", repr=False)

    # -- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, path: str | Path | None = None) -> PreprocessingPipeline:
        """Build a pipeline from ``preprocessing.yaml``.

        Args:
            path: Config file. Defaults to the packaged
                ``ai/configs/preprocessing.yaml``.

        Returns:
            A configured pipeline.

        Raises:
            ConfigError: If the file is missing, malformed, or names an unknown
                step.
        """
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        if not config_path.is_file():
            msg = f"no preprocessing config at {config_path}"
            raise ConfigError(msg)

        try:
            document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            msg = f"{config_path} is not valid YAML: {exc}"
            raise ConfigError(msg) from exc

        if not isinstance(document, dict) or "steps" not in document:
            msg = f"{config_path} must be a mapping containing a 'steps' list"
            raise ConfigError(msg)

        return cls(steps=cls._build_steps(document["steps"], config_path), source=str(config_path))

    @staticmethod
    def _build_steps(raw_steps: Any, config_path: Path) -> tuple[PreprocessingStep, ...]:
        """Instantiate each configured step in order.

        Raises:
            ConfigError: On an unknown step name or a bad parameter.
        """
        if not isinstance(raw_steps, list):
            msg = f"{config_path}: 'steps' must be a list"
            raise ConfigError(msg)

        built: list[PreprocessingStep] = []
        for index, entry in enumerate(raw_steps):
            if not isinstance(entry, dict) or "name" not in entry:
                msg = f"{config_path}: step {index} must be a mapping with a 'name'"
                raise ConfigError(msg)

            name = entry["name"]
            # A disabled step is dropped entirely rather than kept as a no-op, so
            # it costs nothing at runtime AND changes the fingerprint - which is
            # correct: a pipeline without denoising is a different pipeline.
            if not entry.get("enabled", True):
                continue

            step_class = STEP_REGISTRY.get(name)
            if step_class is None:
                known = ", ".join(sorted(STEP_REGISTRY))
                msg = f"{config_path}: unknown step '{name}'. Known steps: {known}"
                raise ConfigError(msg)

            params = {key: value for key, value in entry.items() if key not in {"name", "enabled"}}
            params = _coerce_tuples(params)
            try:
                built.append(step_class(**params))
            except TypeError as exc:
                msg = f"{config_path}: bad parameters for step '{name}': {exc}"
                raise ConfigError(msg) from exc

        if not built:
            msg = f"{config_path}: every step is disabled; nothing to do"
            raise ConfigError(msg)
        return tuple(built)

    # -- the fingerprint ----------------------------------------------------

    @property
    def fingerprint(self) -> str:
        """A short hash of the exact pipeline, for train/serve skew detection.

        Covers each step's **position, name, and every parameter it declares**.
        Two pipelines sharing a fingerprint produce identical output for identical
        input; two that differ anywhere do not.

        Module 07 writes this into the checkpoint metadata. Module 09 compares it
        at model load and refuses to serve on a mismatch, turning the one bug this
        module exists to prevent into a loud startup failure.

        Truncated to 16 hex characters — 64 bits, far beyond what is needed to
        distinguish a handful of hand-written configs, and short enough to read in
        a log line.
        """
        if not self._fingerprint:
            spec = [
                {"position": index, "name": step.name, "params": step.describe()}
                for index, step in enumerate(self.steps)
            ]
            payload = json.dumps(spec, sort_keys=True, separators=(",", ":"))
            self._fingerprint = hashlib.sha256(payload.encode()).hexdigest()[:16]
        return self._fingerprint

    def describe(self) -> dict[str, Any]:
        """The full pipeline specification, for the thesis appendix and logs."""
        return {
            "fingerprint": self.fingerprint,
            "source": self.source,
            "steps": [{"name": step.name, "params": step.describe()} for step in self.steps],
        }

    # -- execution ----------------------------------------------------------

    def run(
        self, image: Image, ctx: CalibrationContext | None = None, *, debug: bool = False
    ) -> PreprocessingResult:
        """Run every step in order.

        Args:
            image: The decoded original, BGR uint8.
            ctx: Device calibration. Defaults to uncalibrated, in which case
                rectification and occlusion detection are no-ops.
            debug: Keep a copy of the frame after each step, for the demo figure.
                Off by default — it costs one full array per step.

        Returns:
            The processed image plus the quality verdict, per-step timings, and
            the pipeline fingerprint.

        Note:
            A frame that fails the quality gate is still processed to completion.
            The caller decides what to do with it: inference marks it
            ``rejected``; the dataset audit counts it. Short-circuiting here would
            return a half-processed array and make the two callers behave
            differently for no gain — the gate is early precisely so that a caller
            that *wants* to skip the remaining work can check
            :attr:`PreprocessingResult.quality` and stop.
        """
        context = ctx or CalibrationContext()
        current = image
        timings: list[StepTiming] = []
        quality: QualityReport | None = None
        capture = PipelineDebug(enabled=debug)

        for step in self.steps:
            started = time.perf_counter()
            current = step.apply(current, context)
            timings.append(StepTiming(step.name, (time.perf_counter() - started) * 1000.0))
            capture.record(step.name, current)

            if isinstance(step, QualityGate) and step.last_report is not None:
                quality = step.last_report

        return PreprocessingResult(
            image=current,
            # A pipeline configured without a quality gate reports a pass with
            # zeroed scores rather than None, so callers never branch on absence.
            quality=quality or _unmeasured(),
            timings=tuple(timings),
            fingerprint=self.fingerprint,
            debug_frames=tuple(capture.frames),
        )

    def run_bytes(
        self, data: bytes, ctx: CalibrationContext | None = None, *, debug: bool = False
    ) -> PreprocessingResult:
        """Decode *data* and run the pipeline over it.

        Raises:
            DecodeError: If the bytes are not a decodable image.
        """
        return self.run(decode(data), ctx, debug=debug)


def _unmeasured() -> QualityReport:
    """A passing report for a pipeline that has no quality gate configured."""
    return QualityReport(passed=True, flags=(), blur_score=0.0, brightness=0.0, occlusion_ratio=0.0)


def _coerce_tuples(params: dict[str, Any]) -> dict[str, Any]:
    """Convert YAML lists into tuples where a step expects one.

    YAML has no tuple type, so ``tile_grid_size: [8, 8]`` arrives as a list.
    Passing that straight through works — but it makes the step's
    :meth:`describe` output differ depending on whether the pipeline was built
    from YAML or in Python, which would give the same pipeline two different
    fingerprints. Normalising here keeps the fingerprint a property of the
    pipeline rather than of how it was constructed.
    """
    return {
        key: tuple(value) if key.endswith("_size") and isinstance(value, list) else value
        for key, value in params.items()
    }
