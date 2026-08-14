#!/usr/bin/env python3
"""Generate `dataset/metadata/progress_reference.csv` from `classes.yaml`.

The CSV is a **generated artifact**, tracked in git so the dataset directory is
self-describing to anyone who receives it without the code — annotators, an
examiner, a future maintainer. `ai/src/ai/configs/classes.yaml` is the source of
truth; editing the CSV by hand is how the two silently diverge, so this script
stamps a header saying so.

Run from the `ai/` project, which is where PyYAML lives::

    cd ai
    uv run python ../scripts/generate_progress_reference.py
    uv run python ../scripts/generate_progress_reference.py --check   # CI: fail if stale

It parses the YAML rather than importing `ai.progress.mapping` so that a
malformed class table produces a clear parse error here instead of an import
failure inside the package it is meant to be validating. (Unlike
`check_constants_parity.py`, this one is *not* dependency-free — it needs
PyYAML, so it belongs in the `test-ai` CI job rather than `constraints`.)
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CLASSES_YAML = ROOT / "ai" / "src" / "ai" / "configs" / "classes.yaml"
OUTPUT_CSV = ROOT / "dataset" / "metadata" / "progress_reference.csv"

COLUMNS = (
    "class_index",
    "class_name",
    "token",
    "macro_stage",
    "nominal_progress_pct",
    "stage_floor_pct",
    "stage_ceiling_pct",
)


def build_csv(document: dict[str, Any]) -> str:
    """Render the reference table as CSV text."""
    bands = {
        entry["name"]: (entry["floor_pct"], entry["ceiling_pct"])
        for entry in document["macro_stages"]
    }

    buffer = io.StringIO(newline="")
    # Newline discipline matters: written with '\n' and compared byte for byte by
    # --check, so a platform-dependent line ending would make CI fail on Windows
    # and pass on Linux for identical content.
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)

    for entry in sorted(document["classes"], key=lambda item: item["index"]):
        floor, ceiling = bands[entry["macro_stage"]]
        writer.writerow(
            [
                entry["index"],
                entry["name"],
                entry["token"],
                entry["macro_stage"],
                entry["nominal_progress_pct"],
                floor,
                ceiling,
            ]
        )
    return buffer.getvalue()


def main() -> int:
    """Regenerate the CSV, or verify it is current."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if the CSV is stale",
    )
    args = parser.parse_args()

    document = yaml.safe_load(CLASSES_YAML.read_text(encoding="utf-8"))
    rendered = build_csv(document)

    existing = OUTPUT_CSV.read_text(encoding="utf-8") if OUTPUT_CSV.is_file() else None

    if args.check:
        if existing == rendered:
            print(f"up to date: {OUTPUT_CSV.relative_to(ROOT)}")
            return 0
        print(
            f"STALE: {OUTPUT_CSV.relative_to(ROOT)} does not match "
            f"{CLASSES_YAML.relative_to(ROOT)}.\n"
            "Run: python scripts/generate_progress_reference.py",
            file=sys.stderr,
        )
        return 1

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_CSV.write_text(rendered, encoding="utf-8", newline="")
    verb = "unchanged" if existing == rendered else "written"
    print(f"{verb}: {OUTPUT_CSV.relative_to(ROOT)} ({len(document['classes'])} classes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
