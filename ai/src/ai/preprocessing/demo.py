"""Before/after strip and latency benchmark — thesis Figure 6.

Two jobs, deliberately in one place: showing what each step does, and reporting
what each step costs. A figure that shows the pipeline works is worth more when
the reader can see it is also affordable on the target hardware.

Run::

    # the figure
    python -m ai.preprocessing.demo --input dataset/raw/CB01/sample.jpg --out outputs/preprocess_demo/

    # with no image to hand — draws a synthetic construction scene
    python -m ai.preprocessing.demo --synthetic --out outputs/preprocess_demo/

    # latency only, median of N runs
    python -m ai.preprocessing.demo --synthetic --benchmark 20
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np

from ai.preprocessing.pipeline import PreprocessingPipeline, load_image
from ai.preprocessing.types import CalibrationContext, Image

__all__ = ["build_strip", "main", "synthetic_site"]

#: Height each panel is scaled to in the strip. Large enough that CLAHE's effect
#: on shadow detail is visible in a printed thesis, small enough that a five-panel
#: strip fits a page width.
PANEL_HEIGHT = 260
LABEL_BAR = 34
MARGIN = 8


def synthetic_site(width: int = 1600, height: int = 1200, *, seed: int = 7) -> Image:
    """Draw a construction scene, for running the demo with no dataset.

    Not a substitute for a real capture in the thesis figure — use a genuine
    site photograph there. This exists so the pipeline is demonstrable and
    testable on day one, months before the dataset exists.

    Deliberately includes the things the pipeline is built to handle: a bright
    sky against a shadowed façade (so CLAHE has something to recover), a warm
    colour cast (for white balance), sensor noise (for the bilateral filter), and
    scaffolding lines (the structural edges that must survive denoising).
    """
    rng = np.random.default_rng(seed)

    # Sky: a bright vertical gradient, warm-tinted like late afternoon. Drawn
    # across the full frame first so no region is ever left unpainted - a black
    # band would give the contrast steps an artificial extreme to work against
    # and make the figure misleading.
    image = np.zeros((height, width, 3), dtype=np.uint8)
    horizon = int(height * 0.72)
    for y in range(horizon):
        shade = 205 - int(55 * y / max(1, horizon))
        image[y, :] = (shade - 25, shade - 8, shade)

    # Ground, with a little tonal variation so it is not a flat plate.
    for y in range(horizon, height):
        shade = 118 + int(22 * (y - horizon) / max(1, height - horizon))
        image[y, :] = (shade - 20, shade - 8, shade)

    # The building: deliberately darker than the sky, so the frame has the wide
    # dynamic range that defeats a naive global contrast stretch.
    top, bottom = int(height * 0.30), int(height * 0.88)
    left, right = int(width * 0.14), int(width * 0.86)
    cv2.rectangle(image, (left, top), (right, bottom), (88, 92, 96), -1)

    # Floor slabs and columns — the structural edges the classifier reads.
    for index in range(1, 6):
        y = top + index * (bottom - top) // 6
        cv2.line(image, (left, y), (right, y), (66, 70, 74), 4)
    for index in range(1, 9):
        x = left + index * (right - left) // 9
        cv2.line(image, (x, top), (x, bottom), (72, 76, 80), 3)

    # Scaffolding over the left half.
    for index in range(0, 14):
        x = left + index * 34
        if x < left + (right - left) // 2:
            cv2.line(image, (x, top), (x, bottom), (150, 160, 170), 1)

    # A shadowed right-hand face: this is what CLAHE should recover.
    shadow = image[top:bottom, (left + right) // 2 : right].astype(np.float32) * 0.45
    image[top:bottom, (left + right) // 2 : right] = shadow.astype(np.uint8)

    # Warm cast plus sensor noise.
    cast = np.array([0.92, 0.98, 1.08], dtype=np.float32)
    noisy = image.astype(np.float32) * cast + rng.normal(0, 7.5, image.shape)
    return np.asarray(np.clip(noisy, 0, 255), dtype=np.uint8)


def build_strip(frames: list[tuple[str, Image]]) -> Image:
    """Lay labelled panels out left to right.

    Every panel is scaled to the same height so the reader compares content
    rather than size — the 224x224 output would otherwise appear as a postage
    stamp beside the 1600x1200 original and look like the pipeline shrank the
    building rather than reframed it.
    """
    panels: list[Image] = []
    for label, frame in frames:
        height, width = frame.shape[:2]
        scaled_width = max(1, round(width * PANEL_HEIGHT / height))
        panel = cv2.resize(frame, (scaled_width, PANEL_HEIGHT), interpolation=cv2.INTER_AREA)

        canvas = np.full((PANEL_HEIGHT + LABEL_BAR, scaled_width, 3), 245, dtype=np.uint8)
        canvas[LABEL_BAR:, :] = panel
        cv2.putText(
            canvas,
            label,
            (6, 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
        panels.append(canvas)

    total_width = sum(panel.shape[1] for panel in panels) + MARGIN * (len(panels) + 1)
    strip_height = PANEL_HEIGHT + LABEL_BAR + MARGIN * 2
    strip = np.full((strip_height, total_width, 3), 245, dtype=np.uint8)

    x = MARGIN
    for panel in panels:
        strip[MARGIN : MARGIN + panel.shape[0], x : x + panel.shape[1]] = panel
        x += panel.shape[1] + MARGIN
    return strip


def _benchmark(pipeline: PreprocessingPipeline, image: Image, runs: int) -> None:
    """Report per-step latency, median over *runs* warm iterations."""
    # Warm up first. OpenCV allocates lookup tables and thread pools on first
    # call, and reporting that as the cost of preprocessing would overstate it by
    # an order of magnitude.
    for _ in range(3):
        pipeline.run(image)

    samples: dict[str, list[float]] = {}
    for _ in range(runs):
        for timing in pipeline.run(image).timings:
            samples.setdefault(timing.name, []).append(timing.milliseconds)

    height, width = image.shape[:2]
    print(f"\nLatency — {width}x{height}, median of {runs} warm runs")
    print("-" * 44)
    total = 0.0
    for name, values in samples.items():
        median = statistics.median(values)
        total += median
        print(f"  {name:<24} {median:7.2f} ms")
    print("-" * 44)
    print(f"  {'TOTAL':<24} {total:7.2f} ms")


def main(argv: list[str] | None = None) -> int:
    """Generate the demo strip and optionally benchmark the pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Source image")
    parser.add_argument("--synthetic", action="store_true", help="Draw a synthetic scene instead")
    parser.add_argument("--config", type=Path, help="Pipeline config; defaults to the packaged one")
    parser.add_argument("--out", type=Path, default=Path("outputs/preprocess_demo"))
    parser.add_argument(
        "--benchmark", type=int, metavar="RUNS", help="Also report per-step latency"
    )
    args = parser.parse_args(argv)

    if not args.input and not args.synthetic:
        parser.error("pass --input PATH or --synthetic")

    image = synthetic_site() if args.synthetic else load_image(args.input)
    pipeline = PreprocessingPipeline.from_config(args.config)

    result = pipeline.run(image, CalibrationContext(), debug=True)

    args.out.mkdir(parents=True, exist_ok=True)
    strip = build_strip([("00 original", image), *_labelled(image, result.debug_frames)])
    strip_path = args.out / "pipeline_strip.png"
    cv2.imwrite(str(strip_path), strip)

    for index, (name, frame) in enumerate(result.debug_frames, start=1):
        cv2.imwrite(str(args.out / f"{index:02d}_{name}.png"), frame)
    cv2.imwrite(str(args.out / "00_original.png"), image)

    print(f"pipeline    {pipeline.source}")
    print(f"fingerprint {pipeline.fingerprint}")
    print(f"steps       {' -> '.join(step.name for step in pipeline.steps)}")
    print(f"quality     {result.quality.as_dict()}")
    print(f"output      {result.image.shape[1]}x{result.image.shape[0]}")
    print(f"figure      {strip_path}")

    if args.benchmark:
        _benchmark(pipeline, image, args.benchmark)
    return 0


def _labelled(original: Image, frames: tuple[tuple[str, Image], ...]) -> list[tuple[str, Image]]:
    """Number the captured frames and mark the ones that changed nothing.

    Marking matters for honesty. The quality gate only measures, and
    rectification is a no-op on an uncalibrated device — so two panels are
    pixel-identical to the one before them. Left unlabelled, a reader reasonably
    concludes those steps do nothing at all, rather than that they did nothing
    *here*.
    """
    labelled: list[tuple[str, Image]] = []
    previous = original
    for index, (name, frame) in enumerate(frames, start=1):
        unchanged = frame.shape == previous.shape and bool(np.array_equal(frame, previous))
        suffix = " (no change)" if unchanged else ""
        labelled.append((f"{index:02d} {name}{suffix}", frame))
        previous = frame
    return labelled


if __name__ == "__main__":
    sys.exit(main())
