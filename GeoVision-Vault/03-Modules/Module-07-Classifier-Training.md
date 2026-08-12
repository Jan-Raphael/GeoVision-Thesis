---
title: Module 07 — Classifier Training (ResNet18 / MobileNetV3)
type: module
module: 7
status: planned
updated: 2026-08-12
---

# Module 07 — Stage Classifier Training

## Scope
Dataset assembly, the training loop, and trained checkpoints for **ResNet18** (primary) and
**MobileNetV3** (comparison). PyTorch only — TensorFlow is forbidden ([[Tech-Stack]]).

## Deliverables
- `scripts/prepare_dataset.py` — CVAT export → `dataset/processed/` class folders + `metadata.csv`.
- `scripts/split_dataset.py` — **grouped stratified** 70/15/15 (`group = site`), seed 42,
  writes `split_manifest.csv`. See the leakage warning in [[Dataset-Spec]].
- `ai/data/datamodule.py` — `ConstructionStageDataset` + dataloaders (workers, pin_memory,
  `WeightedRandomSampler` for imbalance).
- `ai/data/transforms.py` — the Albumentations pipelines from [[Dataset-Spec]].
- `ai/models/resnet18.py` — torchvision ResNet18, ImageNet weights, `fc` → `Linear(512, 10)`,
  optional `Dropout(0.3)`; supports freeze-then-unfreeze.
- `ai/models/mobilenetv3.py` — same interface, different backbone.
- `ai/models/base.py` — `StageClassifier` Protocol: `predict(tensor) -> ClassifierOutput`.
  Both models satisfy it, so Module 09 depends on the protocol, not the class.
- `ai/training/trainer.py` — loop with AMP, grad clipping, scheduler, early stopping,
  checkpointing, CSV logging, resume.
- `ai/training/callbacks.py` — `EarlyStopping(patience=10, monitor='val_macro_f1')`,
  `ModelCheckpoint(save_best + last)`, `CSVLogger`, `LRMonitor`.
- `ai/training/train_classifier.py` — CLI: `--config`, `--arch`, `--epochs`, `--device auto`,
  `--resume`.
- `ai/configs/train_resnet18.yaml`, `train_mobilenetv3.yaml`, `classes.yaml`.

## Training recipe (start here, then tune)
| Setting | Value |
|---|---|
| Input | 224×224 |
| Batch | 32 (16 on ≤ 4 GB VRAM / CPU) |
| Optimizer | AdamW, lr `3e-4` (head) / `3e-5` (backbone), wd `1e-4` |
| Schedule | 3 epochs frozen backbone, then unfreeze all |
| Scheduler | `ReduceLROnPlateau(monitor=val_macro_f1, factor=0.5, patience=4)` |
| Loss | `CrossEntropyLoss(weight=class_weights, label_smoothing=0.05)` |
| Epochs | 60 max, early stop patience 10 |
| AMP | on when CUDA available |
| Seed | 42, `torch.use_deterministic_algorithms(True)` where feasible |
| Selection | best **macro-F1**, not accuracy (imbalanced classes) |

## Critical implementation notes
- **CPU fallback is required**, not optional: `device = "cuda" if torch.cuda.is_available()
  else "cpu"`, AMP disabled on CPU, smaller default batch. The examiner's machine may not
  have a GPU — the demo must still run.
- Checkpoints save `state_dict` + class names + input size + preprocessing config hash +
  git commit + metrics. A `.pt` file that doesn't know its own class order is a landmine.
- Never let augmentation touch val/test.
- Log the per-epoch **confusion matrix** for the validation set — watching which classes
  merge is how you'll actually debug this model.
- Save `outputs/runs/<run_id>/` with the resolved config, so every thesis number is traceable.
- If accuracy plateaus low: check labels first (a 5 % label-noise rate caps you around 90 %),
  then class balance, then augmentation strength, then the model. In that order.

## Dependencies
Modules 01, 06. `torch`, `torchvision`, `albumentations`, `scikit-learn`, `tqdm`, `matplotlib`.

## How to run
```bash
python scripts/prepare_dataset.py --cvat dataset/labels/classification.csv
python scripts/split_dataset.py --ratio 0.70 0.15 0.15 --group-by site --seed 42
python -m ai.training.train_classifier --config ai/configs/train_resnet18.yaml
python -m ai.training.train_classifier --config ai/configs/train_mobilenetv3.yaml
```

## Testing procedure
1. `split_dataset.py`: no image appears in two splits; **no site spans splits**; class
   proportions preserved within ±3 pp.
2. Dataloader smoke test: one batch is `(B,3,224,224)`, labels in `[0,9]`.
3. **Overfit test**: 20 images, no augmentation → training accuracy reaches ~100 % within
   50 epochs. If it can't, the model/loss wiring is broken — fix that before a real run.
4. Train 2 epochs on CPU → completes without error (proves the fallback).
5. Early stopping triggers on a deliberately flat run.
6. Checkpoint round-trip: save → load → identical predictions on a fixed batch.
7. Resume from checkpoint continues at the right epoch and LR.
8. Full run → `best.pt` with val macro-F1 recorded.

## Expected output
```
models/classifier/resnet18/v1/best.pt
outputs/runs/<run_id>/{config.yaml,metrics.csv,curves.png,confusion_matrix.png,best.pt,last.pt}
```
Target ≥ 85 % top-1, macro-F1 ≥ 0.80 on the held-out test set ([[Evaluation-Plan]]).

## Done criteria
- [ ] Dataset prepared, split without leakage, manifest committed
- [ ] ResNet18 trained, target metrics met (or the gap honestly analyzed)
- [ ] MobileNetV3 trained under identical conditions for the comparison table
- [ ] Early stopping, LR scheduling, checkpointing, resume all working
- [ ] Runs on GPU **and** CPU
- [ ] Every run reproducible from `outputs/runs/<run_id>/`

## Related
[[Dataset-Spec]] · [[Construction-Stages]] · [[Module-06-AI-Preprocessing]] · [[Module-09-Inference-Service]] · [[Evaluation-Plan]]
