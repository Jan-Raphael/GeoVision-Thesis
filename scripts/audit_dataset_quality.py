#!/usr/bin/env python3
"""Run the OpenCV quality gate over every raw photo, before training touches any of them.

`ai/src/ai/preprocessing/quality.py`'s `assess()` is what actually runs in production
(`ai.preprocessing.pipeline.PreprocessingPipeline`) to reject blurry, dark, or occluded
captures before they reach the classifier. Running it once, up front, over `dataset/raw/`
answers a question PENDING.md asks for explicitly: how many of the collected photos would
have been rejected — a useful filter before annotation, and an honest thesis figure
("X% of raw captures passed the quality gate").

No calibration context is supplied (occlusion needs a per-device ROI polygon that does not
exist for these historical photos), so occlusion is not tested here — only blur and darkness.

Run from the `ai/` project, which is where the `ai` package and its dependencies live::

    cd ai
    uv run python ../scripts/audit_dataset_quality.py
    uv run python ../scripts/audit_dataset_quality.py --raw-root ../dataset/raw --csv-out ../outputs/quality_audit.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW_ROOT = ROOT / "dataset" / "raw"
#: `.heic` is also present in the raw dataset (iPhone default format, all under
#: `Paramjeet/`) but is handled separately below, since OpenCV cannot decode it.
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
HEIC_SUFFIXES = (".heic",)


def _load_heic(path: Path):  # noqa: ANN202 - returns an `ai.preprocessing.pipeline.Image`
    """Decode a HEIC file to the same BGR uint8 array `load_image` produces.

    OpenCV's `cv2.imdecode` (what `load_image` uses) cannot read HEIC at all, so
    every `.heic` file in the dataset would otherwise be silently invisible to
    this audit — which is exactly what happened the first time this script ran.
    Requires `pillow-heif` (not a project dependency; install ad hoc with
    `uv run --with pillow-heif python scripts/audit_dataset_quality.py`).
    """
    import cv2
    import numpy as np
    import pillow_heif
    from PIL import Image as PILImage, ImageOps

    pillow_heif.register_heif_opener()
    pil_image = ImageOps.exif_transpose(PILImage.open(path)).convert("RGB")
    rgb = np.array(pil_image, dtype=np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _relative_class(path: Path, raw_root: Path) -> str:
    """Best-effort macro-stage bucket from the path, for the summary breakdown.

    Not authoritative — just whichever path component (case-insensitively) matches a known
    stage name, so the summary can show "Foundation: 12/30 rejected" instead of one flat
    number. A photo under no recognisable stage folder is reported as `unsorted`.
    """
    known = {"foundation", "structural", "roofing", "finishing"}
    for part in path.relative_to(raw_root).parts[:-1]:
        if part.casefold() in known:
            return part.capitalize()
    return "unsorted"


def main() -> int:
    """Assess every raw image and print a pass/fail summary, optionally to CSV too."""
    from ai.preprocessing.pipeline import load_image
    from ai.preprocessing.quality import assess

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--csv-out", type=Path, default=None, help="Optional per-image CSV report")
    args = parser.parse_args()

    if not args.raw_root.is_dir():
        print(f"not a directory: {args.raw_root}", file=sys.stderr)
        return 1

    paths = sorted(
        p
        for p in args.raw_root.rglob("*")
        if p.is_file() and p.suffix.casefold() in (*IMAGE_SUFFIXES, *HEIC_SUFFIXES)
    )
    if not paths:
        print(f"no images found under {args.raw_root}", file=sys.stderr)
        return 1

    rows: list[dict[str, object]] = []
    by_class: dict[str, Counter[str]] = {}
    flag_totals: Counter[str] = Counter()

    for path in paths:
        bucket = _relative_class(path, args.raw_root)
        counter = by_class.setdefault(bucket, Counter())
        try:
            if path.suffix.casefold() in HEIC_SUFFIXES:
                image = _load_heic(path)
            else:
                image = load_image(path)
        except ImportError:
            counter["skipped_heic"] += 1
            rows.append({"path": str(path), "bucket": bucket, "passed": None, "flags": "skipped_heic"})
            continue
        except Exception as exc:  # noqa: BLE001 - a corrupt/unreadable file is itself a finding
            counter["unreadable"] += 1
            rows.append({"path": str(path), "bucket": bucket, "passed": False, "flags": "unreadable"})
            print(f"UNREADABLE: {path} ({exc})", file=sys.stderr)
            continue

        report = assess(image)
        counter["passed" if report.passed else "rejected"] += 1
        for flag in report.flags:
            flag_totals[flag.value] += 1
        rows.append(
            {
                "path": str(path.relative_to(args.raw_root)),
                "bucket": bucket,
                "passed": report.passed,
                "flags": ",".join(flag.value for flag in report.flags),
                "blur_score": round(report.blur_score, 2),
                "brightness": round(report.brightness, 2),
            }
        )

    total = len(paths)
    total_passed = sum(counter["passed"] for counter in by_class.values())
    total_unreadable = sum(counter["unreadable"] for counter in by_class.values())
    total_skipped = sum(counter["skipped_heic"] for counter in by_class.values())
    scored = total - total_skipped

    print(f"\nQuality audit — {args.raw_root}")
    print(f"{'Bucket':<12} {'Total':>6} {'Passed':>7} {'Rejected':>9} {'Unreadable':>11} {'Skipped':>8}")
    for bucket, counter in sorted(by_class.items()):
        bucket_total = sum(counter.values())
        print(
            f"{bucket:<12} {bucket_total:>6} {counter['passed']:>7} "
            f"{counter['rejected']:>9} {counter['unreadable']:>11} {counter['skipped_heic']:>8}"
        )
    print(
        f"{'TOTAL':<12} {total:>6} {total_passed:>7} "
        f"{scored - total_passed - total_unreadable:>9} {total_unreadable:>11} {total_skipped:>8}"
    )
    if total_skipped:
        print(
            f"\n{total_skipped} HEIC file(s) skipped — install pillow-heif to include them "
            f"(uv run --with pillow-heif python {Path(__file__).name} ...)."
        )
    if scored:
        print(f"Pass rate (scored images only): {total_passed / scored * 100:.1f}%")
    if flag_totals:
        print("Rejection reasons:", dict(flag_totals))

    if args.csv_out:
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        with args.csv_out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nPer-image report written to {args.csv_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
