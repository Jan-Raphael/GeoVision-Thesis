"""Failures the preprocessing pipeline can raise.

Every one of these means "this image cannot be processed", never "this image is
bad". A blurry photograph is a *result* (:class:`~ai.preprocessing.quality.QualityReport`
with ``passed=False``), not an exception — the difference matters, because at
training time you want to count rejections and at inference time you want to
record them, and neither is served by a traceback.
"""

from __future__ import annotations

__all__ = ["ConfigError", "DecodeError", "PreprocessingError"]


class PreprocessingError(Exception):
    """Base class for anything that prevents an image being processed."""


class DecodeError(PreprocessingError):
    """The bytes are not a decodable image.

    Raised for truncated uploads and files that carry a JPEG magic number but
    nothing usable behind it. OpenCV's own behaviour here is to return ``None``
    silently, which then fails several steps later as an unhelpful
    ``AttributeError`` on a shape that does not exist.
    """


class ConfigError(PreprocessingError):
    """``preprocessing.yaml`` is malformed or names an unknown step.

    Raised at construction time rather than on first use. A typo in a step name
    should stop the training run before it spends an hour producing a model
    trained through a pipeline nobody intended.
    """
