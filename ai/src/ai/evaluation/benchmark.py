"""Inference latency, throughput, and the hardware they were measured on.

Measured **through the ``StageClassifier``/``ObjectDetector`` protocols**
(``ai/models/base.py``), never against a concrete backbone. That is what lets
this module benchmark the deterministic stub today — producing a real number
that exercises the whole reporting path — and a trained ResNet18 or YOLOv8n
tomorrow, with the caller changing one line, not this file.

"210 ms" means nothing without knowing what it ran on
(``Module-15-Testing-and-Evaluation.md`` — critical implementation notes), so
every result carries the CPU model, core count, RAM, and whether a CUDA device
was available, captured at measurement time rather than typed in by hand later
where it can drift from what actually ran.
"""

from __future__ import annotations

import platform
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from ai.models.base import Image, ObjectDetector, StageClassifier

_ResultT = TypeVar("_ResultT")

__all__ = [
    "BenchmarkResult",
    "HardwareInfo",
    "benchmark_classifier",
    "benchmark_detector",
    "hardware_info",
]


@dataclass(frozen=True, slots=True)
class HardwareInfo:
    """What ran the benchmark — recorded, never assumed.

    ``cuda_available``/``gpu_name`` are best-effort: torch is always installed
    in this package (it is a base dependency, not optional — unlike
    ``ultralytics``), so importing it here to ask ``torch.cuda`` costs nothing
    and never needs a try/except around the import itself.
    """

    system: str
    machine: str
    processor: str
    python_version: str
    cpu_count: int | None
    cuda_available: bool
    gpu_name: str | None


def hardware_info() -> HardwareInfo:
    """Snapshot the machine running the current process."""
    import os

    cuda_available = False
    gpu_name: str | None = None
    try:
        import torch

        cuda_available = torch.cuda.is_available()
        if cuda_available:
            gpu_name = torch.cuda.get_device_name(0)
    except ImportError:  # pragma: no cover - torch is a base ai/ dependency
        pass

    return HardwareInfo(
        system=platform.system(),
        machine=platform.machine(),
        processor=platform.processor() or platform.machine(),
        python_version=platform.python_version(),
        cpu_count=os.cpu_count(),
        cuda_available=cuda_available,
        gpu_name=gpu_name,
    )


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Timing summary for one model over one batch of images.

    ``params``/``size_mb`` are optional because the ``StageClassifier`` /
    ``ObjectDetector`` protocols deliberately do not expose the underlying
    module (that is what lets the stub, which has no parameters at all,
    satisfy the same protocol) — a caller with a real torch model on hand
    passes them in; a caller with only the protocol leaves them ``None``, and
    the report renders "n/a" rather than a fabricated zero.
    """

    model_name: str
    architecture: str
    is_stub: bool
    device: str
    n_images: int
    n_warmup: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    throughput_ips: float
    params: int | None = None
    size_mb: float | None = None


def _timed_runs(
    call: Callable[[Image], _ResultT], images: list[Image], n_warmup: int
) -> list[float]:
    """Run ``call`` over ``images`` after ``n_warmup`` throwaway passes.

    Warm-up matters here specifically because it is what the number is *for*:
    the first forward pass through a real torch model resolves kernels and
    allocates buffers, costing hundreds of milliseconds that a live server
    never pays twice (``StageClassifier.warm_up``'s own docstring). Timing that
    once into a "mean" would misreport steady-state latency, which is the only
    number that matters once the worker has been running for more than one
    request.
    """
    for image in images[:n_warmup] or images[:1]:
        call(image)

    timings: list[float] = []
    for image in images:
        started = time.perf_counter()
        call(image)
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def _summarize(timings: list[float]) -> tuple[float, float, float, float, float, float]:
    """mean, median, p95, min, max, throughput (images/second)."""
    mean_ms = statistics.mean(timings)
    median_ms = statistics.median(timings)
    p95_ms = statistics.quantiles(timings, n=20)[18] if len(timings) >= 20 else max(timings)
    throughput = 1000.0 / mean_ms if mean_ms > 0 else 0.0
    return (
        round(mean_ms, 3),
        round(median_ms, 3),
        round(p95_ms, 3),
        round(min(timings), 3),
        round(max(timings), 3),
        round(throughput, 2),
    )


def benchmark_classifier(
    classifier: StageClassifier,
    images: list[Image],
    *,
    n_warmup: int = 3,
    params: int | None = None,
    size_mb: float | None = None,
) -> BenchmarkResult:
    """Time ``classifier.predict`` over ``images``.

    Calls :meth:`~ai.models.base.StageClassifier.warm_up` first — the
    dedicated warm-up hook, not just a throwaway prediction — because a real
    model may do more there (e.g. cuDNN autotuning) than one forward pass
    triggers on its own.
    """
    classifier.warm_up()
    timings = _timed_runs(classifier.predict, images, n_warmup)
    mean_ms, median_ms, p95_ms, min_ms, max_ms, throughput = _summarize(timings)
    info = classifier.info

    return BenchmarkResult(
        model_name=info.name,
        architecture=info.architecture,
        is_stub=info.is_stub,
        device=info.device,
        n_images=len(images),
        n_warmup=min(n_warmup, len(images)),
        mean_ms=mean_ms,
        median_ms=median_ms,
        p95_ms=p95_ms,
        min_ms=min_ms,
        max_ms=max_ms,
        throughput_ips=throughput,
        params=params,
        size_mb=size_mb,
    )


def benchmark_detector(
    detector: ObjectDetector,
    images: list[Image],
    *,
    n_warmup: int = 3,
    params: int | None = None,
    size_mb: float | None = None,
) -> BenchmarkResult:
    """Time ``detector.detect`` over ``images``. Mirrors :func:`benchmark_classifier`."""
    detector.warm_up()
    timings = _timed_runs(detector.detect, images, n_warmup)
    mean_ms, median_ms, p95_ms, min_ms, max_ms, throughput = _summarize(timings)
    info = detector.info

    return BenchmarkResult(
        model_name=info.name,
        architecture=info.architecture,
        is_stub=info.is_stub,
        device=info.device,
        n_images=len(images),
        n_warmup=min(n_warmup, len(images)),
        mean_ms=mean_ms,
        median_ms=median_ms,
        p95_ms=p95_ms,
        min_ms=min_ms,
        max_ms=max_ms,
        throughput_ips=throughput,
        params=params,
        size_mb=size_mb,
    )
