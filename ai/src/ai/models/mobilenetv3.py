"""MobileNetV3 stage classifier — the comparison model (`Module-07-Classifier-Training.md`:
"MobileNetV3 (comparison) — same interface, different backbone").

Structurally a mirror of `ai/models/resnet18.py`; the only real differences are which
torchvision constructor gets called and where the classification head lives
(`model.classifier[3]` here vs `model.fc` for ResNet18) — see `ai/models/common.py` for why
that's a parameter rather than two copies of the freeze/unfreeze logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import torch
from torch import nn
from torchvision.models import (
    MobileNet_V3_Large_Weights,
    MobileNet_V3_Small_Weights,
    mobilenet_v3_large,
    mobilenet_v3_small,
)

from ai.data.transforms import eval_transforms, to_rgb
from ai.models.base import Classification, Image, ModelInfo
from ai.progress.mapping import class_names

__all__ = ["CHECKPOINT_KEYS", "HEAD_PREFIX", "MobileNetV3Classifier", "build_mobilenetv3"]

CHECKPOINT_KEYS = ("model_state", "class_names", "input_size", "preprocessing_fingerprint")

#: `classifier.3` is the final Linear layer in both the `_large` and `_small` head
#: (`Linear -> Hardswish -> Dropout -> Linear`); the prefix is identical for both variants.
HEAD_PREFIX = "classifier.3."


def build_mobilenetv3(
    num_classes: int, *, pretrained: bool = True, dropout: float = 0.3, variant: str = "large"
) -> nn.Module:
    """A torchvision MobileNetV3 with its head replaced for `num_classes`.

    Args:
        num_classes: Size of the final linear layer — 4, per `classes.yaml` (ADR-036/ADR-038).
        pretrained: Load ImageNet weights. `False` only for fast structural tests.
        dropout: Applied between the pooled features and the final linear layer, matching the
            existing dropout slot already in torchvision's classifier head (index 2).
        variant: `"large"` or `"small"` — the comparison this module exists for is against
            ResNet18's accuracy, so `"large"` is the default; `"small"` trades some accuracy
            for a model that would actually fit an edge device, which is its own interesting
            comparison point for the thesis discussion.

    Raises:
        ValueError: If `variant` is neither `"large"` nor `"small"`.
    """
    if variant == "large":
        weights = MobileNet_V3_Large_Weights.IMAGENET1K_V1 if pretrained else None
        model = mobilenet_v3_large(weights=weights)
    elif variant == "small":
        weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None
        model = mobilenet_v3_small(weights=weights)
    else:
        msg = f"variant must be 'large' or 'small', got {variant!r}"
        raise ValueError(msg)

    in_features: int = model.classifier[3].in_features
    model.classifier[2] = nn.Dropout(dropout)
    model.classifier[3] = nn.Linear(in_features, num_classes)
    return model  # type: ignore[no-any-return]  # see the matching note in resnet18.py


@dataclass(slots=True)
class MobileNetV3Classifier:
    """The trained model, satisfying `ai.models.base.StageClassifier`.

    Args:
        weights_path: A checkpoint written by `ai/training/train_classifier.py --arch mobilenetv3`.
        device: `"cuda"`, `"cpu"`, or `"auto"` (resolves to CUDA when available).
        variant: Must match whatever the checkpoint was actually trained as — `build_mobilenetv3`
            has no way to recover this from `state_dict` alone (large/small share layer names).
    """

    weights_path: str
    device: str = "auto"
    variant: str = "large"
    _model: nn.Module = field(init=False, repr=False)
    _classes: tuple[str, ...] = field(init=False, repr=False)
    _resolved_device: str = field(init=False)
    _fingerprint: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        """Resolve the device, load the checkpoint, and validate it against `classes.yaml`."""
        self._resolved_device = (
            "cuda" if (self.device == "auto" and torch.cuda.is_available()) else self.device
        )
        if self._resolved_device == "auto":
            self._resolved_device = "cpu"

        # weights_only=False: see the matching note in ai/models/resnet18.py.
        checkpoint = torch.load(
            self.weights_path, map_location=self._resolved_device, weights_only=False
        )
        missing = [key for key in CHECKPOINT_KEYS if key not in checkpoint]
        if missing:
            msg = f"{self.weights_path}: checkpoint missing {missing} — not written by train_classifier.py"
            raise ValueError(msg)

        checkpoint_classes = tuple(checkpoint["class_names"])
        current_classes = class_names()
        if checkpoint_classes != current_classes:
            msg = (
                f"{self.weights_path} was trained against classes {checkpoint_classes}, but "
                f"classes.yaml now defines {current_classes} — the checkpoint does not match "
                "the current class table and would silently mislabel every prediction"
            )
            raise ValueError(msg)

        self._classes = current_classes
        self._fingerprint = checkpoint["preprocessing_fingerprint"]
        self._model = build_mobilenetv3(len(self._classes), pretrained=False, variant=self.variant)
        self._model.load_state_dict(checkpoint["model_state"])
        self._model.to(self._resolved_device)
        self._model.eval()

    @property
    def info(self) -> ModelInfo:
        """Provenance for `GET /model/status` and the preprocessing-skew check."""
        return ModelInfo(
            name=f"mobilenetv3-{self.variant}-classifier",
            architecture=f"mobilenet_v3_{self.variant}",
            version=Path(self.weights_path).parent.name or "unknown",
            class_names=self._classes,
            input_size=224,
            device=self._resolved_device,
            is_stub=False,
            preprocessing_fingerprint=self._fingerprint,
            weights_path=self.weights_path,
        )

    def predict(self, image: Image) -> Classification:
        """Classify one preprocessed frame."""
        started = time.perf_counter()
        rgb = to_rgb(image)
        tensor = eval_transforms()(image=rgb)["image"].unsqueeze(0).to(self._resolved_device)

        with torch.no_grad():
            logits = self._model(tensor)
            probabilities = torch.softmax(logits, dim=1)[0]

        class_index = int(torch.argmax(probabilities).item())
        return Classification(
            class_index=class_index,
            class_name=self._classes[class_index],
            confidence=float(probabilities[class_index]),
            probabilities={
                name: float(probabilities[i]) for i, name in enumerate(self._classes)
            },
            inference_ms=int((time.perf_counter() - started) * 1000),
        )

    def warm_up(self) -> None:
        """One throwaway inference, so the first real upload after a deploy isn't the slow one."""
        import numpy as np

        self.predict(np.zeros((224, 224, 3), dtype=np.uint8))
