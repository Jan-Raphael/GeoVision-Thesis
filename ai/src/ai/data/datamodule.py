"""`ConstructionStageDataset` and the dataloaders built from it.

Every image is run through the shared, deterministic preprocessing pipeline **once**, at
dataset-construction time, not per `__getitem__` call — augmentation is what needs to differ
between epochs, quality/geometry/photometry normalisation does not, and re-running an 88 ms
pipeline on every access across every epoch would dominate training time for no benefit. Images
the quality gate would reject in production (blur, darkness) are excluded here too, with a
logged count: training on a frame the serving path would have thrown away teaches the model
something it will never be asked to reproduce.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

from ai.data.transforms import eval_transforms, to_rgb, train_transforms
from ai.preprocessing.pipeline import PreprocessingPipeline, load_image
from ai.progress.mapping import class_names, reference_for_name

__all__ = ["ConstructionStageDataset", "build_dataloaders"]

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


class ConstructionStageDataset(Dataset):
    """One split (`train`, `validation`, or `test`) of `dataset/processed/<class>/*`.

    Args:
        root: A split directory containing one subfolder per class name (case-insensitive,
            matched against `ai.progress.mapping`'s frozen class table — the single source of
            truth for label order everywhere in this project).
        transform: An Albumentations pipeline (`train_transforms()` or `eval_transforms()`).
            Applied fresh on every `__getitem__` call; everything upstream of it is cached.
        pipeline: The shared preprocessing pipeline. Defaults to the packaged config — pass an
            explicit instance only to test against a different one.

    Raises:
        ValueError: If a subfolder name does not match any known class, or if no image in the
            whole split survives the quality gate (an empty dataset is a configuration error,
            not a valid training run).
    """

    def __init__(
        self,
        root: Path,
        transform: Any,  # an albumentations.Compose; the library ships no public type alias
        *,
        pipeline: PreprocessingPipeline | None = None,
    ) -> None:
        """Load and quality-filter every image in *root* eagerly — see the class docstring."""
        self.root = Path(root)
        self.transform = transform
        self._pipeline = pipeline or PreprocessingPipeline.from_config()
        self._images: list[np.ndarray] = []
        self._labels: list[int] = []
        self._load()

    def _load(self) -> None:
        rejected = 0
        for class_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            try:
                reference = reference_for_name(class_dir.name)
            except KeyError:
                logger.warning("%s: not a known construction-stage class, skipping", class_dir)
                continue

            paths = sorted(
                p for p in class_dir.iterdir() if p.is_file() and p.suffix.casefold() in IMAGE_SUFFIXES
            )
            for path in paths:
                result = self._pipeline.run(load_image(path))
                if not result.quality.passed:
                    rejected += 1
                    continue
                self._images.append(to_rgb(result.image))
                self._labels.append(reference.index)

        if not self._images:
            msg = f"no image in {self.root} survived the quality gate — nothing to train on"
            raise ValueError(msg)
        if rejected:
            logger.info("%s: %d image(s) rejected by the quality gate, excluded", self.root, rejected)

    def __len__(self) -> int:
        """How many images survived the quality gate."""
        return len(self._images)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        """Augment (train) or plainly convert (eval) one cached image to a tensor."""
        augmented = self.transform(image=self._images[index])
        return augmented["image"], self._labels[index]

    @property
    def labels(self) -> tuple[int, ...]:
        """Every image's class index, in dataset order — one weight lookup per sample."""
        return tuple(self._labels)

    @property
    def class_counts(self) -> dict[int, int]:
        """How many examples of each class index this split holds."""
        counts: dict[int, int] = dict.fromkeys(range(len(class_names())), 0)
        for label in self._labels:
            counts[label] += 1
        return counts


@dataclass(frozen=True, slots=True)
class Dataloaders:
    """The three split loaders, plus the datasets themselves for metrics/reporting."""

    train: DataLoader
    validation: DataLoader
    test: DataLoader
    train_dataset: ConstructionStageDataset
    validation_dataset: ConstructionStageDataset
    test_dataset: ConstructionStageDataset


def build_dataloaders(
    processed_root: Path,
    *,
    batch_size: int = 32,
    num_workers: int = 0,
) -> Dataloaders:
    """Build train/validation/test loaders from `dataset/processed/{train,validation,test}/`.

    Args:
        processed_root: The `dataset/processed/` directory produced by `scripts/split_dataset.py`.
        batch_size: Per Module 07's recipe (32 on GPU, 16 recommended on CPU/small VRAM — the
            caller decides, this just applies whatever is passed).
        num_workers: Defaults to 0. `DataLoader` workers on Windows need the calling script
            guarded by `if __name__ == "__main__":`; 0 keeps this safe to import anywhere,
            including inside a Jupyter/Kaggle notebook cell where that guard does not exist.

    Returns:
        Loaders for all three splits, with a `WeightedRandomSampler` on **train only** — the
        classes are unevenly represented (see `Dataset-Spec.md`), and sampling inversely
        proportional to frequency is what keeps a rare class from being drowned out by a common
        one, without discarding a single image the way undersampling would.
    """
    train_dataset = ConstructionStageDataset(processed_root / "train", train_transforms())
    validation_dataset = ConstructionStageDataset(processed_root / "validation", eval_transforms())
    test_dataset = ConstructionStageDataset(processed_root / "test", eval_transforms())

    counts = train_dataset.class_counts
    weight_per_class = {label: 1.0 / count for label, count in counts.items() if count > 0}
    sample_weights = [weight_per_class[label] for label in train_dataset.labels]
    sampler = WeightedRandomSampler(sample_weights, num_samples=len(sample_weights), replacement=True)

    return Dataloaders(
        train=DataLoader(
            train_dataset, batch_size=batch_size, sampler=sampler, num_workers=num_workers
        ),
        validation=DataLoader(
            validation_dataset, batch_size=batch_size, shuffle=False, num_workers=num_workers
        ),
        test=DataLoader(test_dataset, batch_size=batch_size, shuffle=False, num_workers=num_workers),
        train_dataset=train_dataset,
        validation_dataset=validation_dataset,
        test_dataset=test_dataset,
    )
