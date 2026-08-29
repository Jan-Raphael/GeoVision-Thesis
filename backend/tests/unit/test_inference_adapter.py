"""The adapter's own wiring: turning `Settings` into a real `build_service` call.

Module 09 was built and tested against a deterministic stub for months. The one
piece that never had a test was whether flipping `GV_USE_STUB_MODELS=false`
actually reaches a real checkpoint — `classifier_weights`/`detector_weights`
were declared on `Settings` but never once passed into `build_service`. These
tests exist so that gap cannot reopen silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.infrastructure.ai import adapter
from app.infrastructure.ai.adapter import _resolve_weights, get_inference_service


def _settings(**overrides: object) -> Settings:
    """Hermetic settings for the local/default environment — no `.env` involved."""
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """The service is a module-level singleton; do not leak one test's fake into another."""
    adapter.reset_inference_service()
    yield
    adapter.reset_inference_service()


class TestResolveWeights:
    def test_empty_string_is_unset(self, tmp_path: Path) -> None:
        assert _resolve_weights(tmp_path, "") is None

    def test_relative_path_resolves_against_model_dir(self, tmp_path: Path) -> None:
        resolved = _resolve_weights(tmp_path, "classifier/resnet18/v1/best.pt")
        assert resolved == str(tmp_path / "classifier/resnet18/v1/best.pt")

    def test_absolute_path_is_left_alone(self, tmp_path: Path) -> None:
        absolute = tmp_path / "elsewhere" / "best.pt"
        assert _resolve_weights(tmp_path, str(absolute)) == str(absolute)


class TestGetInferenceService:
    def test_settings_reach_build_service(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The exact gap this rework closes: weights/device settings must actually arrive."""
        captured: dict[str, object] = {}

        class _FakeService:
            def warm_up(self) -> None:
                pass

        def _fake_build_service(**kwargs: object) -> _FakeService:
            captured.update(kwargs)
            return _FakeService()

        monkeypatch.setattr("ai.inference.service.build_service", _fake_build_service)

        settings = _settings(
            model_dir=tmp_path,
            classifier_weights="classifier/resnet18/v1/best.pt",
            detector_weights="",
            use_stub_models=False,
            inference_device="cpu",
        )

        service = get_inference_service(settings)

        assert isinstance(service, _FakeService)
        assert captured["use_stubs"] is False
        assert captured["classifier_weights"] == str(tmp_path / "classifier/resnet18/v1/best.pt")
        assert captured["detector_weights"] is None
        assert captured["device"] == "cpu"

    def test_the_service_is_built_only_once(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Constructing per-task would dwarf inference cost with checkpoint-load time."""
        calls = {"count": 0}

        class _FakeService:
            def warm_up(self) -> None:
                pass

        def _fake_build_service(**_kwargs: object) -> _FakeService:
            calls["count"] += 1
            return _FakeService()

        monkeypatch.setattr("ai.inference.service.build_service", _fake_build_service)
        settings = _settings(model_dir=tmp_path, use_stub_models=True)

        first = get_inference_service(settings)
        second = get_inference_service(settings)

        assert first is second
        assert calls["count"] == 1
