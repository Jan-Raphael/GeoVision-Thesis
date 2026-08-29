#!/usr/bin/env python3
"""Grouped stratified train/validation/test split — the leakage guard [[Dataset-Spec]] demands.

**Group = building, not top-level site folder.** A "site" in the leakage sense is one fixed
camera's view of one physical structure: two images of the same building are near-identical and
must never land in different splits. `dataset/raw/Aldea Grove/` turned out to contain three
different houses (`1/`, `2/`, `3/`), each with its own `Foundation/Structural/Roofing/Finishing`
subfolders — treating "Aldea Grove" as one group would have let the same building leak across
splits despite grouping by folder name. A **group is discovered automatically**: any directory
whose immediate children include at least one of the four class names (case-insensitively) is
one. This also means a real deployed site becomes its own group for free once its captures are
promoted into `dataset/raw/`, with no change to this script.

With only a handful of groups (six today), `sklearn.model_selection.StratifiedGroupKFold` is
built for k-fold cross-validation, not a one-shot 70/15/15 three-way split — shoehorning it
through k-fold machinery is less direct than the actual problem. This instead **exhaustively
searches every way to assign the discovered groups to {train, validation, test}** (whole groups
only — a group is never split) and picks the assignment whose per-class proportions land closest
to 70/15/15, which is exact and reproducible for a small number of groups.

Run from the `ai/` project, which is where `PyYAML`... actually needs nothing beyond the
standard library::

    cd ai
    uv run python ../scripts/split_dataset.py
    uv run python ../scripts/split_dataset.py --ratio 0.70 0.15 0.15 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW_ROOT = ROOT / "dataset" / "raw"
DEFAULT_OUT_ROOT = ROOT / "dataset" / "processed"
DEFAULT_MANIFEST = ROOT / "dataset" / "metadata" / "split_manifest.csv"
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
CLASSES = ("foundation", "structural", "roofing", "finishing")
SPLITS = ("train", "validation", "test")


def discover_groups(raw_root: Path) -> dict[str, dict[str, list[Path]]]:
    """Find every "group" (building/source) and its images per class.

    Returns ``{group_name: {class_name: [image_path, ...]}}``. A directory is a group if at
    least one of its immediate children's name casefolds to a known class name.
    """
    groups: dict[str, dict[str, list[Path]]] = {}
    for directory in sorted(p for p in raw_root.rglob("*") if p.is_dir()):
        children = {child.name.casefold(): child for child in directory.iterdir() if child.is_dir()}
        matched = {name: path for name, path in children.items() if name in CLASSES}
        if not matched:
            continue

        group_name = str(directory.relative_to(raw_root))
        by_class: dict[str, list[Path]] = {}
        for class_name, class_dir in matched.items():
            images = sorted(
                p for p in class_dir.rglob("*") if p.is_file() and p.suffix.casefold() in IMAGE_SUFFIXES
            )
            if images:
                by_class[class_name] = images
        if by_class:
            groups[group_name] = by_class
    return groups


def _class_totals(groups: dict[str, dict[str, list[Path]]]) -> Counter[str]:
    totals: Counter[str] = Counter()
    for by_class in groups.values():
        for class_name, images in by_class.items():
            totals[class_name] += len(images)
    return totals


def best_assignment(
    groups: dict[str, dict[str, list[Path]]], ratios: tuple[float, float, float]
) -> dict[str, str]:
    """Exhaustively pick the group -> split assignment closest to *ratios* per class.

    Score is the sum over classes of |actual_fraction - target_fraction|, weighted by how many
    images that class has (a class with 5 images matters less to get exactly proportional than
    one with 300), *plus* a large penalty for every (class, split) combination that ends up with
    zero images. Degenerate assignments (a split with zero groups, or **train** missing a class
    entirely — a model cannot learn a class it never sees) are excluded outright. A class
    entirely absent from validation or test is heavily penalized rather than rejected: with a
    handful of groups, avoiding it outright is not always possible, and rejecting those
    assignments could leave no valid assignment at all.
    """
    names = list(groups.keys())
    totals = _class_totals(groups)
    targets = dict(zip(SPLITS, ratios, strict=True))
    missing_class_penalty = sum(totals.values())  # dwarfs any proportion-closeness score

    best: tuple[float, dict[str, str]] | None = None
    for combo in itertools.product(SPLITS, repeat=len(names)):
        assignment = dict(zip(names, combo, strict=True))
        if len(set(assignment.values())) < len(SPLITS):
            continue  # some split got no groups at all

        per_split_class: dict[str, Counter[str]] = {split: Counter() for split in SPLITS}
        for group_name, split in assignment.items():
            for class_name, images in groups[group_name].items():
                per_split_class[split][class_name] += len(images)

        if any(per_split_class["train"][class_name] == 0 for class_name in totals):
            continue  # a class the model would never see in training

        score = 0.0
        for class_name, total in totals.items():
            if total == 0:
                continue
            for split in SPLITS:
                count = per_split_class[split][class_name]
                if count == 0:
                    score += missing_class_penalty
                    continue
                actual_fraction = count / total
                score += total * abs(actual_fraction - targets[split])

        if best is None or score < best[0]:
            best = (score, assignment)

    if best is None:
        msg = "no valid train/validation/test assignment exists for these groups"
        raise ValueError(msg)
    return best[1]


def main() -> int:
    """Discover groups, pick the best split assignment, copy files, write the manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--manifest-out", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ratio", type=float, nargs=3, default=(0.70, 0.15, 0.15))
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the plan; do not copy files or write the manifest"
    )
    args = parser.parse_args()

    if abs(sum(args.ratio) - 1.0) > 1e-6:
        print(f"--ratio must sum to 1.0, got {args.ratio}", file=sys.stderr)
        return 1

    groups = discover_groups(args.raw_root)
    if not groups:
        print(f"no groups found under {args.raw_root}", file=sys.stderr)
        return 1

    assignment = best_assignment(groups, tuple(args.ratio))

    print(f"Groups discovered under {args.raw_root}:")
    for group_name, by_class in sorted(groups.items()):
        counts = ", ".join(f"{cls}={len(imgs)}" for cls, imgs in sorted(by_class.items()))
        print(f"  {group_name:<28} -> {assignment[group_name]:<10} ({counts})")

    per_split_class: dict[str, Counter[str]] = {split: Counter() for split in SPLITS}
    rows: list[dict[str, str]] = []
    for group_name, by_class in groups.items():
        split = assignment[group_name]
        for class_name, images in by_class.items():
            per_split_class[split][class_name] += len(images)
            for image_path in images:
                # Prefix by group so two sites' identically-named files never collide, without
                # inventing a naming scheme distinct from what promotion to the dataset already
                # implies elsewhere in this project (a stable, traceable rename).
                digest = hashlib.blake2b(str(image_path).encode(), digest_size=4).hexdigest()
                safe_group = group_name.replace("\\", "_").replace("/", "_").replace(" ", "")
                dest_name = f"{safe_group}_{digest}{image_path.suffix.casefold()}"
                rows.append(
                    {
                        "image_name": dest_name,
                        "original_path": str(image_path.relative_to(args.raw_root)),
                        "group": group_name,
                        "class": class_name,
                        "split": split,
                    }
                )
                if not args.dry_run:
                    dest_dir = args.out_root / split / class_name
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(image_path, dest_dir / dest_name)

    totals = _class_totals(groups)
    print(f"\n{'Class':<12} {'Total':>6} " + " ".join(f"{s:>12}" for s in SPLITS))
    for class_name in CLASSES:
        total = totals.get(class_name, 0)
        if total == 0:
            continue
        cells = " ".join(
            f"{per_split_class[s][class_name]:>5} ({per_split_class[s][class_name] / total * 100:4.0f}%)"
            for s in SPLITS
        )
        print(f"{class_name:<12} {total:>6} {cells}")

    if args.dry_run:
        print("\n--dry-run: no files copied, no manifest written")
        return 0

    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest_out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["image_name", "original_path", "group", "class", "split"])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["split"], r["class"], r["image_name"])))

    print(f"\n{len(rows)} images copied into {args.out_root}")
    print(f"Manifest written to {args.manifest_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
