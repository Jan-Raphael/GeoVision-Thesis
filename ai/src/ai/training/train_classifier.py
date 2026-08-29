"""CLI: `python -m ai.training.train_classifier --config ai/configs/train_resnet18.yaml`.

Every run gets its own `outputs/runs/<run_id>/` directory (default: a timestamp), so a thesis
figure can always be traced back to the exact config and metrics that produced it — the
`run_root`/`run_id` split exists so a config file never has to be edited just to avoid
overwriting the previous run.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ai.training.trainer import SUPPORTED_ARCHITECTURES, TrainingConfig, train

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--arch", default=None, choices=SUPPORTED_ARCHITECTURES)
    parser.add_argument("--run-id", default=None, help="Defaults to a UTC timestamp")
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--device", default=None, choices=["auto", "cuda", "cpu"])
    parser.add_argument("--resume", type=Path, default=None)
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Cap training at 2 epochs regardless of --epochs/the config file "
        "(Module 07's testing procedure #4: prove the CPU fallback completes)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse args, resolve the config, and run training. Returns a process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    document = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    arch = args.arch or document.get("arch", "resnet18")
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{arch}"
    run_root = Path(document.get("run_root", "outputs/runs"))

    config = TrainingConfig(
        processed_root=Path(document["processed_root"]),
        run_dir=run_root / run_id,
        arch=arch,
        epochs=args.epochs or document.get("epochs", 60),
        frozen_epochs=document.get("frozen_epochs", 3),
        batch_size=document.get("batch_size", 32),
        lr_head=float(document.get("lr_head", 3e-4)),
        lr_backbone=float(document.get("lr_backbone", 3e-5)),
        weight_decay=float(document.get("weight_decay", 1e-4)),
        label_smoothing=float(document.get("label_smoothing", 0.05)),
        patience=document.get("patience", 10),
        lr_patience=document.get("lr_patience", 4),
        lr_factor=float(document.get("lr_factor", 0.5)),
        device=args.device or document.get("device", "auto"),
        seed=document.get("seed", 42),
        num_workers=document.get("num_workers", 0),
        resume=args.resume,
        max_epochs_override=2 if args.smoke_test else None,
    )

    result = train(config)

    print(f"run directory: {result.run_dir}")
    print(f"epochs run: {result.epochs_run} (early stop: {result.stopped_early})")
    print(f"best validation macro-F1: {result.best_macro_f1:.4f}")
    print(f"best checkpoint: {result.best_checkpoint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
