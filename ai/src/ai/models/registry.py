"""Dispatch a checkpoint to the classifier wrapper that actually trained it.

Two backbones exist now (`resnet18`, the primary model; `mobilenetv3`, the comparison), and a
checkpoint has to self-describe which one it is — nothing else at load time can tell a ResNet18
`state_dict` from a MobileNetV3 one apart before attempting to load it into the wrong
architecture and failing confusingly deep inside `load_state_dict`.
"""

from __future__ import annotations

import torch

from ai.models.base import StageClassifier

__all__ = ["load_classifier"]


def load_classifier(weights_path: str, *, device: str = "auto") -> StageClassifier:
    """Load a trained checkpoint into whichever wrapper actually trained it.

    Args:
        weights_path: A checkpoint written by `ai/training/train_classifier.py`.
        device: `"cuda"`, `"cpu"`, or `"auto"`.

    Returns:
        A `ResNet18Classifier` or `MobileNetV3Classifier`, whichever the checkpoint's
        `architecture` key names.

    Raises:
        ValueError: If `architecture` names something this registry doesn't know.
    """
    # A first, cheap peek at just the architecture tag — the wrapper class re-loads and
    # validates the full checkpoint (class names, preprocessing fingerprint) itself right
    # after, so this isn't the place to duplicate that.
    # weights_only=False: see the note in ai/models/resnet18.py.
    peek = torch.load(weights_path, map_location="cpu", weights_only=False)
    # Checkpoints trained before this registry existed have no "architecture" key at all —
    # every one of them was ResNet18, since it was the only backbone Module 07 had.
    architecture = peek.get("architecture", "resnet18")

    if architecture == "resnet18":
        from ai.models.resnet18 import ResNet18Classifier

        return ResNet18Classifier(weights_path=weights_path, device=device)
    if architecture == "mobilenetv3":
        from ai.models.mobilenetv3 import MobileNetV3Classifier

        return MobileNetV3Classifier(weights_path=weights_path, device=device)

    msg = f"{weights_path}: unknown architecture {architecture!r} — cannot pick a wrapper"
    raise ValueError(msg)
