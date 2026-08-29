"""Augmentation and tensor conversion — deliberately downstream of the shared pipeline.

`ai/preprocessing/pipeline.py` (Module 06) is deterministic by contract: it is what training
*and* serving both build from, and its fingerprint is stamped into every checkpoint. Nothing
random can live there without breaking that guarantee. Augmentation — random flips, jitter,
rotation — only ever makes sense for training, so it lives here instead, strictly after the
shared pipeline has already produced the 224x224 BGR frame every code path agrees on.

Albumentations 2.x (ADR-014): transform signatures differ from 1.x tutorials copied off the
internet — verified against the installed version rather than assumed.
"""

from __future__ import annotations

import albumentations as A  # noqa: N812 - `as A` is albumentations' own universal convention
import numpy as np
from albumentations.pytorch import ToTensorV2
from numpy.typing import NDArray

__all__ = ["IMAGENET_MEAN", "IMAGENET_STD", "eval_transforms", "to_rgb", "train_transforms"]

#: Standard ImageNet statistics — what every torchvision pretrained backbone expects,
#: ResNet18 included. Computed on RGB, hence the BGR->RGB conversion before this ever applies.
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def to_rgb(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """BGR (what the preprocessing pipeline and OpenCV use) -> RGB (what torch expects)."""
    return image[:, :, ::-1]


def train_transforms() -> A.Compose:
    """Augmentation for training only — never applied to validation or test.

    Deliberately mild: the pipeline upstream already normalises lighting (CLAHE + white
    balance) and geometry (perspective rectification), so augmentation here only needs to cover
    what a *fixed* camera can still vary — a mildly different framing, minor residual exposure
    difference, sensor noise — not the wide viewpoint/lighting swings a dataset of unconstrained
    photos would need.
    """
    return A.Compose(
        [
            A.HorizontalFlip(p=0.5),
            A.Rotate(limit=7, border_mode=0, p=0.5),
            A.RandomBrightnessContrast(brightness_limit=0.15, contrast_limit=0.15, p=0.5),
            A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
            ToTensorV2(),
        ]
    )


def eval_transforms() -> A.Compose:
    """Validation/test: tensor conversion and normalisation only. No randomness, ever."""
    return A.Compose(
        [
            A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
            ToTensorV2(),
        ]
    )
