"""CLI: `python -m ai.training.train_detector --data dataset/labels/detection/data.yaml`.

Thin by design (`Module-08-YOLO-Detection.md`): ultralytics already implements the training
loop, augmentation, and checkpointing this recipe calls for. This CLI exists to pin the
project's specific recipe (augmentation settings, device fallback, output location) as a
committed, reviewable default rather than something typed fresh into a Kaggle cell every time.

**Cannot be run today** — `dataset/labels/` has no bounding-box annotations yet (Open-Questions
Q5/annotation status, 2026-08-27). This is ready for the moment annotation produces a real
`data.yaml`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="YOLO data.yaml")
    parser.add_argument("--model", default="yolov8n.pt", help="Base checkpoint (nano by default)")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--device", default=None, help='"0" for the first GPU, "cpu", or omit to auto-detect')
    parser.add_argument("--project", default="outputs/runs/detector", help="Ultralytics output root")
    parser.add_argument("--name", default=None, help="Run name; ultralytics picks one if omitted")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse args and hand off to `YOLO(...).train(...)`."""
    args = _build_parser().parse_args(argv)

    import torch
    from ultralytics import YOLO

    device = args.device or ("0" if torch.cuda.is_available() else "cpu")
    if device == "cpu":
        print(
            "warning: training YOLOv8 on CPU is painfully slow (Module 08's own recipe note) — "
            "Kaggle/Colab GPU is strongly recommended for this module.",
            file=sys.stderr,
        )

    model = YOLO(args.model)
    results = model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        patience=args.patience,
        project=args.project,
        name=args.name,
        seed=42,
        # Recipe augmentation (Module-08-YOLO-Detection.md), on top of ultralytics' own
        # defaults: lighting variation (fixed camera, two capture times a day), a small
        # rotation tolerance, and horizontal flip/mosaic left at their standard strength.
        hsv_v=0.5,
        degrees=5,
        fliplr=0.5,
        mosaic=1.0,
    )

    print(f"training complete: {results.save_dir}")
    print(f"best weights: {results.save_dir / 'weights' / 'best.pt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
