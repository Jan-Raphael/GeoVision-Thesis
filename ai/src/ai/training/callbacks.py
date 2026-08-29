"""Training callbacks: early stopping, checkpointing, CSV logging.

Kept as small, independent, testable pieces rather than folded into the training loop, so each
rule (`Module-07-Classifier-Training.md`'s "early stopping, LR scheduling, ... checkpointing")
can be demonstrated and pinned on its own, the same way `ai/progress/aggregator.py`'s rules are.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch

__all__ = ["CSVLogger", "EarlyStopping", "ModelCheckpoint"]


@dataclass
class EarlyStopping:
    """Stop once `monitor` has not improved for `patience` consecutive epochs.

    Args:
        patience: Epochs to wait without improvement before signalling stop.
        mode: `"max"` (higher is better — macro-F1) or `"min"` (lower is better — loss).
        min_delta: The smallest change that counts as an improvement, so floating-point noise
            at the fourth decimal place cannot reset the patience counter forever.
    """

    patience: int = 10
    mode: str = "max"
    min_delta: float = 1e-4
    best: float = field(init=False)
    epochs_without_improvement: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        """Seed `best` from `mode`."""
        self.best = float("-inf") if self.mode == "max" else float("inf")

    def step(self, value: float) -> bool:
        """Record one epoch's value. Returns `True` when training should stop."""
        improved = (
            value > self.best + self.min_delta
            if self.mode == "max"
            else value < self.best - self.min_delta
        )
        if improved:
            self.best = value
            self.epochs_without_improvement = 0
        else:
            self.epochs_without_improvement += 1
        return self.epochs_without_improvement >= self.patience


@dataclass
class ModelCheckpoint:
    """Writes `best.pt` (highest monitored value so far) and `last.pt` (every epoch).

    Args:
        run_dir: `outputs/runs/<run_id>/` — created if missing.
        mode: Matches `EarlyStopping.mode` — which direction is "better".
    """

    run_dir: Path
    mode: str = "max"
    best: float = field(init=False)

    def __post_init__(self) -> None:
        """Create `run_dir` and seed `best` from `mode`."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.best = float("-inf") if self.mode == "max" else float("inf")

    def step(self, value: float, payload: dict[str, Any]) -> bool:
        """Save `last.pt` always; save `best.pt` when `value` improves. Returns whether it did."""
        torch.save(payload, self.run_dir / "last.pt")
        is_best = value > self.best if self.mode == "max" else value < self.best
        if is_best:
            self.best = value
            torch.save(payload, self.run_dir / "best.pt")
        return is_best


class CSVLogger:
    """Appends one row per epoch to `outputs/runs/<run_id>/metrics.csv`.

    A run's every thesis number should be traceable to this file — no metric is ever computed
    a second time from a different source once it has been logged here.
    """

    def __init__(self, path: Path) -> None:
        """Bind the logger to *path*; nothing is written until the first `log()` call."""
        self.path = path
        self._fieldnames: list[str] | None = None

    def log(self, row: dict[str, Any]) -> None:
        """Write one epoch's metrics, creating the header from the first call's keys."""
        is_new = not self.path.exists()
        if self._fieldnames is None:
            self._fieldnames = list(row.keys())
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._fieldnames)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
