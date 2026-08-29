"""The classifier registry: dispatching a checkpoint to the wrapper that trained it."""

from __future__ import annotations

import torch

from ai.models.mobilenetv3 import MobileNetV3Classifier, build_mobilenetv3
from ai.models.registry import load_classifier
from ai.models.resnet18 import ResNet18Classifier, build_resnet18
from ai.progress.mapping import class_names


def _checkpoint(tmp_path, *, architecture: str | None, build) -> str:
    path = tmp_path / "checkpoint.pt"
    payload = {
        "model_state": build(len(class_names()), pretrained=False).state_dict(),
        "class_names": class_names(),
        "input_size": 224,
        "preprocessing_fingerprint": "test-fingerprint",
    }
    if architecture is not None:
        payload["architecture"] = architecture
    torch.save(payload, path)
    return str(path)


class TestLoadClassifier:
    def test_resnet18_checkpoint_loads_the_resnet18_wrapper(self, tmp_path) -> None:
        path = _checkpoint(tmp_path, architecture="resnet18", build=build_resnet18)
        assert isinstance(load_classifier(path), ResNet18Classifier)

    def test_mobilenetv3_checkpoint_loads_the_mobilenetv3_wrapper(self, tmp_path) -> None:
        path = _checkpoint(tmp_path, architecture="mobilenetv3", build=build_mobilenetv3)
        assert isinstance(load_classifier(path), MobileNetV3Classifier)

    def test_a_checkpoint_with_no_architecture_key_defaults_to_resnet18(self, tmp_path) -> None:
        """Checkpoints trained before this registry existed predate the field entirely —
        every one of them was ResNet18, since it was the only backbone at the time."""
        path = _checkpoint(tmp_path, architecture=None, build=build_resnet18)
        assert isinstance(load_classifier(path), ResNet18Classifier)

    def test_an_unknown_architecture_raises_rather_than_guessing(self, tmp_path) -> None:
        path = _checkpoint(tmp_path, architecture="some-future-backbone", build=build_resnet18)
        try:
            load_classifier(path)
        except ValueError as exc:
            assert "some-future-backbone" in str(exc)
        else:
            raise AssertionError("expected a ValueError for an unknown architecture")
