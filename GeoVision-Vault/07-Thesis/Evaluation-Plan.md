---
title: Evaluation Plan
type: thesis
status: canonical
updated: 2026-08-12
---

# Evaluation Plan

Everything below is produced by `ai/evaluation/` into `outputs/evaluation/<run_id>/` as both
a CSV/JSON table and a print-ready figure, so thesis figures are regenerable, never
hand-copied.

## 1. Classifier (ResNet18) — primary model

| Metric | Why |
|---|---|
| Top-1 accuracy | headline |
| **Per-class** precision / recall / F1 | exposes the rare classes accuracy hides |
| Macro-F1 | the honest single number under class imbalance |
| Confusion matrix (counts + row-normalized) | the single most-examined figure in the defense |
| **Mean absolute ordinal error** | stages are ordered — "1 stage off" ≠ "5 stages off" ([[Construction-Stages]]) |
| Top-2 accuracy | adjacent-stage confusion is often acceptable operationally |
| Calibration (reliability diagram, ECE) | justifies the `MIN_CONFIDENCE = 0.60` gate |
| Per-class confidence distribution | shows where the gate actually bites |

Target: **≥ 85 % top-1**, macro-F1 ≥ 0.80, and no class with recall < 0.60.

## 2. Backbone comparison (the "comparison model" requirement)

Identical data, splits, seed, augmentation, and schedule — only the backbone changes.

| Model | Top-1 | Macro-F1 | Params | Size (MB) | CPU ms/img | GPU ms/img | Epochs to best |
|---|---|---|---|---|---|---|---|
| ResNet18 (ImageNet) | | | 11.7 M | ~45 | | | |
| ResNet18 (scratch) | | | 11.7 M | ~45 | | | ← proves transfer learning helps |
| MobileNetV3-Small | | | 2.5 M | ~10 | | | |
| MobileNetV3-Large | | | 5.5 M | ~21 | | | |

Deliverable: an accuracy-vs-latency scatter plot. Argues the deployment choice quantitatively.

## 3. Detector (YOLOv8)

mAP@0.5, mAP@0.5:0.95, per-class AP, precision/recall curves, inference ms, model size.

**Cross-model agreement** (the interesting part): on the test set, compare the classifier's
stage against a **rule-based stage inferred from YOLO object counts** (e.g. `roof` boxes
present ⇒ ≥ Roofing; `scaffolding` + no `roof` ⇒ ≤ Framing). Report the agreement rate and a
2-way confusion table. This turns "we also trained YOLO" into a real corroboration
experiment — a much stronger chapter than two unrelated models sitting side by side.

## 4. Ablation study

| Variant | Question answered |
|---|---|
| no preprocessing | does the OpenCV pipeline earn its place? |
| no perspective rectification | does the homography matter? |
| no augmentation | how much does Albumentations buy? |
| frozen backbone vs full fine-tune | transfer-learning strategy |
| 224 vs 320 input | resolution/latency trade-off |

## 5. Progress algorithm evaluation

Ground truth: a manually-labelled per-day progress curve for 1–2 real sites.

| Metric | Definition |
|---|---|
| MAE of displayed progress | mean \|predicted − ground truth\| in pp; target ≤ 8 pp |
| Stage transition lag | days between true stage change and system confirmation; target ≤ 3 days |
| Monotonicity violations | count of unjustified backward moves; target **0** |
| Jitter reduction | std-dev of raw vs smoothed series ([[Progress-Calculation]]) |
| Multi-camera gain | 1-camera MAE vs 2-camera MAE |

The jitter and monotonicity results are the empirical justification for the EMA + ratchet —
present the before/after series as one plot.

## 6. System evaluation

| Metric | Method |
|---|---|
| End-to-end latency (capture → dashboard) | timestamped log spans, n ≥ 50 |
| Ingest throughput | `locust`/`k6` against `/ingest/images` |
| Upload success rate in the field | `device_events` over the deployment period |
| Device uptime & battery curve | `device_events` battery series |
| Capture success rate | captured vs scheduled |
| API p50/p95 latency | middleware timing |
| Storage growth | MB/day/device |

## 7. Usability (optional but cheap and valuable)

**SUS questionnaire** (10 items, n ≥ 10: engineers, students, homeowners) plus a task-success
table (register → create project → pair camera → read progress → export report). A SUS score
plus task-completion rates is a strong, low-cost addition to the results chapter.

## 8. Reproducibility

Every run writes `outputs/runs/<run_id>/` containing: the resolved config, git commit hash,
seed, library versions, class distribution, per-epoch CSV, curves, best/last checkpoints, and
the environment (CPU/GPU model, CUDA version). No number appears in the thesis without a
`run_id` behind it.

## Related
[[Dataset-Spec]] · [[Progress-Calculation]] · [[Module-15-Testing-and-Evaluation]] · [[Thesis-Mapping]]
