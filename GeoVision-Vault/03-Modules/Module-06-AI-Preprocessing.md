---
title: Module 06 — AI Preprocessing (OpenCV)
type: module
module: 6
status: planned
updated: 2026-08-12
---

# Module 06 — OpenCV Preprocessing & Quality Gate

## Scope
The `ai/preprocessing/` package. Pure image-in/image-out — no DB, no HTTP, no torch.
Runs identically at training time and at inference time (this is what prevents train/serve skew).

## Deliverables
- `pipeline.py` — `PreprocessingPipeline` composed of ordered `PreprocessingStep` objects,
  built from `ai/configs/preprocessing.yaml`. Each step: `apply(image, ctx) -> image`.
- `perspective.py` — `rectify(image, homography)`: 4 source points (from
  `devices.homography`) → canonical rectangle via `cv2.getPerspectiveTransform` +
  `cv2.warpPerspective`. No-op when the device has no calibration.
- `normalize.py` — BGR→LAB, **CLAHE** on L (`clipLimit=2.0, tileGridSize=(8,8)`), back to BGR;
  gray-world white balance. Handles the huge lighting swing between 07:00 and 16:00.
- `denoise.py` — `cv2.bilateralFilter(d=9, sigmaColor=75, sigmaSpace=75)`: removes sensor
  noise while preserving the structural edges the classifier relies on.
- `resize.py` — aspect-preserving longest-side resize + letterbox pad to 224×224 (classifier)
  and 640×640 (detector).
- `quality.py` — the gate: `blur_score` (variance of Laplacian), `brightness` (mean L),
  `occlusion_ratio` (ROI foreground vs the device's `roi_polygon`), returning a
  `QualityReport(passed, flags, scores)`. Thresholds from `ai/progress/constants.py`.
- `calibration.py` — helper that takes one reference frame + 4 clicked points and emits the
  homography JSON stored on the device (used by the dashboard calibration UI later).
- `demo.py` — writes a before/after strip for **thesis Figure 6**.

## Pipeline order (and why)
```
1. decode & EXIF-orient
2. quality gate            ← cheapest first; reject before spending anything
3. perspective rectify     ← geometry before photometry
4. brightness/WB normalize
5. denoise                 ← after normalization, so it isn't amplifying noise it just boosted
6. resize + letterbox
7. (train only) Albumentations augmentation
8. normalize to ImageNet mean/std → tensor
```
Steps 1–6 are shared by training and serving. Step 7 is training-only. **If you change this
order, change it in one place** — `preprocessing.yaml` — or train/serve will silently diverge.

## Critical implementation notes
- Deterministic: same input → byte-identical output. No randomness in steps 1–6.
- Every step is individually toggleable so the [[Evaluation-Plan]] ablation study is a config
  change, not a code change.
- Letterbox, don't stretch: a stretched building changes its aspect and hurts the classifier.
- CLAHE on the **L channel only** — applying it per-RGB-channel wrecks color.
- Bilateral filter is slow at full resolution; **resize before denoise** if latency is tight
  (measure it; note the choice in the thesis).
- The quality gate is used at inference; at training time you use it to *audit* the dataset
  (how many of your own captures would have been rejected? — a genuinely interesting result).

## Dependencies
Module 01. `opencv-python-headless`, `numpy`, `albumentations`, `pyyaml`.

## How to run
```bash
python -m ai.preprocessing.demo --input dataset/raw/CB01/sample.jpg --out outputs/preprocess_demo/
python -m ai.preprocessing.pipeline --config ai/configs/preprocessing.yaml --input DIR --output DIR
```

## Testing procedure
1. Output shape is exactly `(224, 224, 3)`, dtype `uint8`, for portrait, landscape, and square inputs.
2. Determinism: run twice, assert arrays are identical.
3. Blur gate: a synthetically Gaussian-blurred image scores below threshold and is rejected.
4. Darkness gate: an image scaled to 10 % brightness is rejected.
5. Occlusion gate: paste a large black rectangle over the ROI → rejected.
6. Rectification: a synthetic checkerboard photographed at an angle rectifies to square
   (assert corner positions within tolerance).
7. CLAHE increases contrast (std-dev of L rises) without clipping (no channel saturation blow-up).
8. Pipeline handles corrupt/truncated JPEG gracefully → raises `PreprocessingError`, not a segfault.
9. Benchmark: report ms/image on the target CPU.

## Expected output
`outputs/preprocess_demo/` contains a labelled before/after strip showing each step's effect —
this is a thesis figure. Unit tests all pass with no network, DB, or GPU.

## Done criteria
- [ ] All steps implemented and individually toggleable via YAML
- [ ] Quality gate returns scores + flags matching the documented thresholds
- [ ] Deterministic and unit-tested
- [ ] Before/after demo figure generated
- [ ] Latency measured and recorded

## Related
[[Progress-Calculation]] · [[Dataset-Spec]] · [[Module-07-Classifier-Training]] · [[Evaluation-Plan]]
