"""Unit tests for `ai.evaluation.benchmark`.

Run entirely against `StubClassifier`/`StubDetector` — the whole point of
benchmarking through the `StageClassifier`/`ObjectDetector` protocols is that
these tests do not change one line when a real ResNet18 is benchmarked later.
"""

from __future__ import annotations

import numpy as np

from ai.evaluation.benchmark import benchmark_classifier, benchmark_detector, hardware_info
from ai.models.stub import StubClassifier, StubDetector


def _images(n: int, size: int = 32) -> list[np.ndarray]:
    rng = np.random.default_rng(1)
    return [rng.integers(0, 255, size=(size, size, 3), dtype=np.uint8) for _ in range(n)]


class TestHardwareInfo:
    def test_reports_a_python_version_and_cpu_count(self) -> None:
        info = hardware_info()
        assert info.python_version
        assert info.system

    def test_cuda_absent_implies_no_gpu_name(self) -> None:
        info = hardware_info()
        if not info.cuda_available:
            assert info.gpu_name is None


class TestBenchmarkClassifier:
    def test_measures_every_image(self) -> None:
        result = benchmark_classifier(StubClassifier(), _images(5), n_warmup=2)
        assert result.n_images == 5
        assert result.mean_ms >= 0.0
        assert result.throughput_ips > 0.0

    def test_flags_the_stub_so_a_result_cannot_be_mistaken_for_real(self) -> None:
        result = benchmark_classifier(StubClassifier(), _images(3))
        assert result.is_stub is True
        assert result.architecture == "stub"

    def test_params_and_size_default_to_none_without_a_torch_model(self) -> None:
        result = benchmark_classifier(StubClassifier(), _images(2))
        assert result.params is None
        assert result.size_mb is None

    def test_params_and_size_pass_through_when_supplied(self) -> None:
        result = benchmark_classifier(StubClassifier(), _images(2), params=11_700_000, size_mb=45.0)
        assert result.params == 11_700_000
        assert result.size_mb == 45.0

    def test_p95_falls_back_to_max_under_twenty_samples(self) -> None:
        result = benchmark_classifier(StubClassifier(), _images(3))
        assert result.p95_ms == result.max_ms


class TestBenchmarkDetector:
    def test_measures_every_image(self) -> None:
        result = benchmark_detector(StubDetector(), _images(4), n_warmup=1)
        assert result.n_images == 4
        assert result.is_stub is True
