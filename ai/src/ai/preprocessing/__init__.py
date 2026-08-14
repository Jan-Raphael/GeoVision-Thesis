"""OpenCV preprocessing: the pipeline shared by training and serving.

Pure image-in, image-out. No database, no HTTP, no torch — which is what lets the
identical code run inside a training loop and inside the inference worker, and is
the only real defence against train/serve skew.

    from ai.preprocessing import PreprocessingPipeline

    pipeline = PreprocessingPipeline.from_config()
    result = pipeline.run(image, ctx)

Spec: ``GeoVision-Vault/03-Modules/Module-06-AI-Preprocessing.md``.
"""

from ai.preprocessing.calibration import (
    homography_from_corners,
    homography_from_json,
    homography_to_json,
)
from ai.preprocessing.denoise import BilateralDenoise, bilateral_denoise
from ai.preprocessing.errors import ConfigError, DecodeError, PreprocessingError
from ai.preprocessing.normalize import ClaheNormalize, apply_clahe, gray_world_white_balance
from ai.preprocessing.perspective import PerspectiveRectify, rectify
from ai.preprocessing.pipeline import (
    DEFAULT_CONFIG_PATH,
    PreprocessingPipeline,
    PreprocessingResult,
    decode,
    load_image,
)
from ai.preprocessing.quality import QualityFlag, QualityGate, QualityReport, assess
from ai.preprocessing.resize import LetterboxResize, letterbox
from ai.preprocessing.types import CalibrationContext, Image, PreprocessingStep

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "BilateralDenoise",
    "CalibrationContext",
    "ClaheNormalize",
    "ConfigError",
    "DecodeError",
    "Image",
    "LetterboxResize",
    "PerspectiveRectify",
    "PreprocessingError",
    "PreprocessingPipeline",
    "PreprocessingResult",
    "PreprocessingStep",
    "QualityFlag",
    "QualityGate",
    "QualityReport",
    "apply_clahe",
    "assess",
    "bilateral_denoise",
    "decode",
    "gray_world_white_balance",
    "homography_from_corners",
    "homography_from_json",
    "homography_to_json",
    "letterbox",
    "load_image",
    "rectify",
]
