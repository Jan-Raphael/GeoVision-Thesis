"""ResNet18 stage classifier — the primary model (`Module-07-Classifier-Training.md`).

`build_resnet18` is shared by training (`ai/training/train_classifier.py`) and inference
(`ResNet18Classifier` below) so the architecture can never drift between the two — a training
script that builds a differently-shaped head than the one inference loads would fail opaquely,
deep inside `load_state_dict`, far from the config line that actually caused it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import torch
from torch import nn
from torchvision.models import ResNet18_Weights, resnet18

from ai.data.transforms import eval_transforms, to_rgb
from ai.models.base import Classification, Image, ModelInfo
from ai.progress.mapping import class_names

__all__ = ["CHECKPOINT_KEYS", "ResNet18Classifier", "build_resnet18", "freeze_backbone", "unfreeze_all"]

#: Keys every checkpoint this project writes or reads must have (Module 07's note: "a `.pt`
#: file that doesn't know its own class order is a landmine").
CHECKPOINT_KEYS = ("model_state", "class_names", "input_size", "preprocessing_fingerprint")


def build_resnet18(num_classes: int, *, pretrained: bool = True, dropout: float = 0.3) -> nn.Module:
    """A torchvision ResNet18 with its head replaced for `num_classes`.

    Args:
        num_classes: Size of the final linear layer — 4, per `classes.yaml` (ADR-036/ADR-038).
        pretrained: Load ImageNet weights. `False` only for fast structural tests that never
            need real features (downloading ImageNet weights in a unit test would be absurd).
        dropout: Applied between the pooled features and the final linear layer, per the
            training recipe.
    """
    weights = ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
    model = resnet18(weights=weights)
    in_features: int = model.fc.in_features
    model.fc = nn.Sequential(nn.Dropout(dropout), nn.Linear(in_features, num_classes))
    # torchvision's own stubs type `resnet18(...)` loosely enough that mypy loses track of
    # the return type after `model.fc` is reassigned above; it is a `ResNet` (an `nn.Module`)
    # both before and after, verified by the training smoke test actually running it.
    return model  # type: ignore[no-any-return]


def freeze_backbone(model: nn.Module) -> None:
    """Freeze everything except the final head — the recipe's "3 epochs frozen" phase."""
    for name, param in model.named_parameters():
        param.requires_grad = name.startswith("fc.")


def unfreeze_all(model: nn.Module) -> None:
    """Release every parameter for fine-tuning, after the frozen warm-up phase."""
    for param in model.parameters():
        param.requires_grad = True


@dataclass(slots=True)
class ResNet18Classifier:
    """The trained model, satisfying `ai.models.base.StageClassifier`.

    Args:
        weights_path: A checkpoint written by `ai/training/train_classifier.py`, carrying
            `CHECKPOINT_KEYS`.
        device: `"cuda"`, `"cpu"`, or `"auto"` (resolves to CUDA when available).
    """

    weights_path: str
    device: str = "auto"
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

        checkpoint = torch.load(self.weights_path, map_location=self._resolved_device)
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
        self._model = build_resnet18(len(self._classes), pretrained=False)
        self._model.load_state_dict(checkpoint["model_state"])
        self._model.to(self._resolved_device)
        self._model.eval()

    @property
    def info(self) -> ModelInfo:
        """Provenance for `GET /model/status` and the preprocessing-skew check."""
        return ModelInfo(
            name="resnet18-classifier",
            architecture="resnet18",
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
