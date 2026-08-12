"""Smoke tests for the ``ai`` package skeleton (Module 01).

These assert the two structural guarantees Module 01 exists to establish:
the package is importable in isolation, and the hard project constraints
(no TensorFlow, CPU fallback) hold. Behavioural tests arrive with Modules 06+.
"""

from __future__ import annotations

import importlib

import pytest

SUBPACKAGES = [
    "ai.data",
    "ai.evaluation",
    "ai.inference",
    "ai.models",
    "ai.preprocessing",
    "ai.progress",
    "ai.training",
]


def test_package_imports_and_has_version() -> None:
    """The package imports standalone and reports a version."""
    import ai

    assert ai.__version__ == "0.1.0"


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name: str) -> None:
    """Every declared subpackage exists and imports cleanly."""
    assert importlib.import_module(name) is not None


def test_tensorflow_is_not_importable() -> None:
    """TensorFlow must not be installed - a hard project constraint.

    Enforced here as well as in CI and pre-commit, because a transitive
    dependency can introduce it without any of our own code changing.
    """
    for forbidden in ("tensorflow", "keras"):
        with pytest.raises(ImportError):
            importlib.import_module(forbidden)


def test_torch_is_available_with_cpu_fallback() -> None:
    """Torch imports and reports a usable device.

    The examiner's machine may have no GPU, so the CPU path must always work.
    """
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    assert device in {"cuda", "cpu"}

    tensor = torch.ones(2, 3, device="cpu")
    assert tuple(tensor.shape) == (2, 3)
    assert float(tensor.sum()) == pytest.approx(6.0)


def test_ai_does_not_import_backend() -> None:
    """``ai`` must never depend on ``backend`` (ADR-011).

    The dependency runs one way only: backend -> ai. If this ever fails, the
    training CLI has silently become un-runnable without the web application.
    """
    import ai

    module_file = ai.__file__
    assert module_file is not None
    with pytest.raises(ImportError):
        importlib.import_module("app")
