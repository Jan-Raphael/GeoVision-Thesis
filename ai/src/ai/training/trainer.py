"""The classifier training loop — AMP, freeze/unfreeze, LR scheduling, early stopping, resume.

Shared by both backbones Module 07 calls for (ResNet18, the primary model; MobileNetV3, the
comparison) — `_ARCHITECTURES` is the one place that knows how to build each and where its
classification head lives, so the loop itself never branches on architecture.

Selection is by **macro-F1**, never accuracy: the classes are unevenly represented (see
`Dataset-Spec.md`), and accuracy alone rewards a model that just always predicts the majority
class. Every rule in `Module-07-Classifier-Training.md`'s recipe is implemented here as a
single, inspectable function (`train`) rather than spread across a framework's callback soup,
so a specific run can be explained line by line during the defense.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
import torch
from sklearn.metrics import confusion_matrix, f1_score
from torch import nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader

from ai.data.datamodule import Dataloaders, build_dataloaders
from ai.models.common import freeze_backbone, unfreeze_all
from ai.preprocessing.pipeline import PreprocessingPipeline
from ai.progress.mapping import class_names
from ai.training.callbacks import CSVLogger, EarlyStopping, ModelCheckpoint

__all__ = ["SUPPORTED_ARCHITECTURES", "TrainingConfig", "TrainingResult", "train"]

logger = logging.getLogger(__name__)


class _ArchSpec(NamedTuple):
    build: Callable[..., nn.Module]
    head_prefix: str


def _resnet18_spec() -> _ArchSpec:
    from ai.models.resnet18 import HEAD_PREFIX, build_resnet18

    return _ArchSpec(build_resnet18, HEAD_PREFIX)


def _mobilenetv3_spec() -> _ArchSpec:
    from ai.models.mobilenetv3 import HEAD_PREFIX, build_mobilenetv3

    return _ArchSpec(build_mobilenetv3, HEAD_PREFIX)


#: Lazily imported (each pulls in its own torchvision constructor) so training one
#: architecture never has to import the other's.
_ARCHITECTURES: dict[str, Callable[[], _ArchSpec]] = {
    "resnet18": _resnet18_spec,
    "mobilenetv3": _mobilenetv3_spec,
}
SUPPORTED_ARCHITECTURES = tuple(_ARCHITECTURES)


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """Every knob in `Module-07-Classifier-Training.md`'s recipe table."""

    processed_root: Path
    run_dir: Path
    arch: str = "resnet18"
    epochs: int = 60
    frozen_epochs: int = 3
    batch_size: int = 32
    lr_head: float = 3e-4
    lr_backbone: float = 3e-5
    weight_decay: float = 1e-4
    label_smoothing: float = 0.05
    patience: int = 10
    lr_patience: int = 4
    lr_factor: float = 0.5
    device: str = "auto"
    seed: int = 42
    num_workers: int = 0
    resume: Path | None = None
    #: Caps a run for smoke tests ("train 2 epochs on CPU" — Module 07's testing procedure #4)
    #: without needing a second code path.
    max_epochs_override: int | None = None


@dataclass(frozen=True, slots=True)
class TrainingResult:
    """Where a completed (or early-stopped) run's artifacts landed."""

    run_dir: Path
    best_macro_f1: float
    best_checkpoint: Path
    epochs_run: int
    stopped_early: bool


def _set_seed(seed: int) -> None:
    """Seed every RNG a training run touches (Python, NumPy, torch)."""
    random.seed(seed)
    np.random.seed(seed)  # noqa: NPY002 - global seed, deliberately: sklearn/torch/albumentations
    # all draw from this global state too, not from a Generator instance passed around by hand.
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def _resolve_device(device: str) -> str:
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device


def _class_weights(dataloaders: Dataloaders, num_classes: int, device: str) -> torch.Tensor:
    """Inverse-frequency weights for `CrossEntropyLoss`, complementing the sampler.

    The `WeightedRandomSampler` already rebalances which examples a batch contains; this
    additionally rebalances how much each misclassification costs, which matters once a batch
    is drawn — a rare class sampled into a batch should not be a "free" mistake relative to a
    common one just because the sampler already gave it a fair shot at being seen.
    """
    counts = dataloaders.train_dataset.class_counts
    total = sum(counts.values())
    weights = [total / (num_classes * counts[i]) if counts.get(i, 0) > 0 else 0.0 for i in range(num_classes)]
    return torch.tensor(weights, dtype=torch.float32, device=device)


def _run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: str,
    optimizer: torch.optim.Optimizer | None,
    scaler: torch.amp.GradScaler,
) -> tuple[float, np.ndarray, np.ndarray]:
    """One pass over `loader`. Trains if `optimizer` is given, otherwise evaluates.

    Returns `(mean_loss, y_true, y_pred)` over the whole loader.
    """
    is_train = optimizer is not None
    model.train(is_train)
    amp_enabled = device == "cuda"

    total_loss = 0.0
    n_batches = 0
    all_true: list[int] = []
    all_pred: list[int] = []

    context = torch.enable_grad() if is_train else torch.no_grad()
    with context:
        for images, labels in loader:
            images = images.to(device)
            labels = labels.to(device)

            if optimizer is not None:
                optimizer.zero_grad(set_to_none=True)

            with torch.amp.autocast(device_type="cuda", enabled=amp_enabled):
                logits = model(images)
                loss = criterion(logits, labels)

            if optimizer is not None:
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()

            total_loss += float(loss.item())
            n_batches += 1
            all_true.extend(labels.detach().cpu().tolist())
            all_pred.extend(logits.detach().argmax(dim=1).cpu().tolist())

    mean_loss = total_loss / max(n_batches, 1)
    return mean_loss, np.array(all_true), np.array(all_pred)


def train(config: TrainingConfig) -> TrainingResult:
    """Run the full training loop and return where its artifacts landed.

    Writes `outputs/runs/<run_id>/{config.json,metrics.csv,best.pt,last.pt,confusion_matrix.json}`
    as it goes, so a crash mid-run still leaves every epoch trained so far inspectable.
    """
    if config.arch not in _ARCHITECTURES:
        msg = f"arch must be one of {SUPPORTED_ARCHITECTURES}, got {config.arch!r}"
        raise ValueError(msg)
    arch_spec = _ARCHITECTURES[config.arch]()

    _set_seed(config.seed)
    device = _resolve_device(config.device)
    logger.info("training %s on device=%s", config.arch, device)

    config.run_dir.mkdir(parents=True, exist_ok=True)
    (config.run_dir / "config.json").write_text(
        json.dumps(dataclasses.asdict(config), indent=2, default=str),
        encoding="utf-8",
    )

    pipeline = PreprocessingPipeline.from_config()
    dataloaders = build_dataloaders(
        config.processed_root, batch_size=config.batch_size, num_workers=config.num_workers
    )
    classes = class_names()
    num_classes = len(classes)

    model = arch_spec.build(num_classes)
    freeze_backbone(model, head_prefix=arch_spec.head_prefix)
    model.to(device)

    head_params = [
        p for name, p in model.named_parameters() if name.startswith(arch_spec.head_prefix)
    ]
    backbone_params = [
        p for name, p in model.named_parameters() if not name.startswith(arch_spec.head_prefix)
    ]
    optimizer = AdamW(
        [
            {"params": head_params, "lr": config.lr_head},
            {"params": backbone_params, "lr": config.lr_backbone},
        ],
        weight_decay=config.weight_decay,
    )
    scheduler = ReduceLROnPlateau(
        optimizer, mode="max", factor=config.lr_factor, patience=config.lr_patience
    )
    criterion = nn.CrossEntropyLoss(
        weight=_class_weights(dataloaders, num_classes, device),
        label_smoothing=config.label_smoothing,
    )
    scaler = torch.amp.GradScaler(device="cuda", enabled=(device == "cuda"))
    early_stopping = EarlyStopping(patience=config.patience, mode="max")
    checkpoint = ModelCheckpoint(config.run_dir, mode="max")
    csv_logger = CSVLogger(config.run_dir / "metrics.csv")

    start_epoch = 0
    if config.resume and config.resume.is_file():
        # weights_only=False: see the matching note in ai/models/resnet18.py — this
        # checkpoint carries plain-Python metadata alongside tensors, written by this
        # project's own code, never an untrusted source.
        state = torch.load(config.resume, map_location=device, weights_only=False)
        model.load_state_dict(state["model_state"])
        optimizer.load_state_dict(state["optimizer_state"])
        scheduler.load_state_dict(state["scheduler_state"])
        start_epoch = state["epoch"] + 1
        early_stopping.best = state.get("early_stopping_best", early_stopping.best)
        checkpoint.best = state.get("checkpoint_best", checkpoint.best)
        logger.info("resumed from %s at epoch %d", config.resume, start_epoch)

    max_epochs = config.max_epochs_override or config.epochs
    epochs_run = 0
    stopped_early = False

    for epoch in range(start_epoch, max_epochs):
        if epoch == config.frozen_epochs:
            unfreeze_all(model)
            logger.info("epoch %d: backbone unfrozen", epoch)

        train_loss, _, _ = _run_epoch(model, dataloaders.train, criterion, device, optimizer, scaler)
        val_loss, val_true, val_pred = _run_epoch(model, dataloaders.validation, criterion, device, None, scaler)
        val_macro_f1 = f1_score(val_true, val_pred, average="macro", zero_division=0)
        scheduler.step(val_macro_f1)
        epochs_run = epoch + 1

        csv_logger.log(
            {
                "epoch": epoch,
                "train_loss": round(train_loss, 5),
                "val_loss": round(val_loss, 5),
                "val_macro_f1": round(float(val_macro_f1), 5),
                "lr_head": optimizer.param_groups[0]["lr"],
            }
        )
        logger.info(
            "epoch %d: train_loss=%.4f val_loss=%.4f val_macro_f1=%.4f",
            epoch, train_loss, val_loss, val_macro_f1,
        )

        matrix = confusion_matrix(val_true, val_pred, labels=list(range(num_classes)))
        (config.run_dir / "confusion_matrix.json").write_text(
            json.dumps({"epoch": epoch, "classes": list(classes), "matrix": matrix.tolist()}, indent=2),
            encoding="utf-8",
        )

        checkpoint.step(
            val_macro_f1,
            {
                "model_state": model.state_dict(),
                "architecture": config.arch,
                "optimizer_state": optimizer.state_dict(),
                "scheduler_state": scheduler.state_dict(),
                "epoch": epoch,
                "class_names": classes,
                "input_size": 224,
                "preprocessing_fingerprint": pipeline.fingerprint,
                "val_macro_f1": float(val_macro_f1),
                "early_stopping_best": early_stopping.best,
                "checkpoint_best": checkpoint.best,
            },
        )

        if early_stopping.step(val_macro_f1):
            logger.info("early stopping triggered at epoch %d", epoch)
            stopped_early = True
            break

    return TrainingResult(
        run_dir=config.run_dir,
        best_macro_f1=checkpoint.best,
        best_checkpoint=config.run_dir / "best.pt",
        epochs_run=epochs_run,
        stopped_early=stopped_early,
    )
