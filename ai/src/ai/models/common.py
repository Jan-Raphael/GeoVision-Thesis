"""Freeze/unfreeze helpers shared by every classifier backbone.

Kept architecture-agnostic (a `head_prefix` argument rather than a hardcoded name) because
`resnet18`'s head is `model.fc` while `mobilenet_v3`'s is `model.classifier.3` — the freeze
recipe (`Module-07-Classifier-Training.md`: "3 epochs frozen backbone, then unfreeze all") is
otherwise identical between them, and duplicating it per architecture is exactly the kind of
thing that drifts.
"""

from __future__ import annotations

from torch import nn

__all__ = ["freeze_backbone", "unfreeze_all"]


def freeze_backbone(model: nn.Module, *, head_prefix: str) -> None:
    """Freeze every parameter except the final head — the recipe's "3 epochs frozen" phase."""
    for name, param in model.named_parameters():
        param.requires_grad = name.startswith(head_prefix)


def unfreeze_all(model: nn.Module) -> None:
    """Release every parameter for fine-tuning, after the frozen warm-up phase."""
    for param in model.parameters():
        param.requires_grad = True
