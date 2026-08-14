---
title: Module 06 — AI Preprocessing (OpenCV)
type: module
module: 6
status: done
updated: 2026-08-14
---

# Module 06 — OpenCV Preprocessing & Quality Gate

## Scope
The `ai/preprocessing/` package. Pure image-in/image-out — no DB, no HTTP, no torch.
Runs identically at training time and at inference time (this is what prevents train/serve skew).

**Status: done.** 113 AI tests pass with no network, database, GPU, or dataset.

## What shipped

| File | Purpose |
|---|---|
| `preprocessing/pipeline.py` | Composable ordered steps, built from YAML; **fingerprinted** |
| `preprocessing/quality.py` | Blur / darkness / occlusion gate → `QualityReport` |
| `preprocessing/perspective.py` | Homography rectification; no-op when uncalibrated |
| `preprocessing/normalize.py` | CLAHE on LAB L + gray-world white balance |
| `preprocessing/denoise.py` | Bilateral filter |
| `preprocessing/resize.py` | Letterbox to 224x224 / 640x640 |
| `preprocessing/calibration.py` | 4 clicked corners → the matrix on `devices.homography` |
| `preprocessing/demo.py` | Before/after strip (**thesis Figure 6**) + latency benchmark |
| `preprocessing/types.py`, `errors.py` | Step protocol, calibration context, error taxonomy |
| `configs/preprocessing.yaml` | **The pipeline order.** Classifier, 224 |
| `configs/preprocessing_detector.yaml` | Same, 640, for YOLOv8 |
| `progress/constants.py` | Single definition site for every threshold |
| `scripts/check_constants_parity.py` | CI guard against `ai/`↔`backend/` drift ([[ADR-Index\|ADR-023]]) |

## Pipeline order (and why)

```
1. quality gate            ← cheapest first, measured on the ORIGINAL
2. perspective rectify     ← geometry before photometry
3. brightness/WB normalize
4. resize + letterbox      ← swapped with denoise; see ADR-024
5. denoise
```

Steps 1–5 are shared by training and serving, and every one is deterministic.
**Not** in this pipeline, deliberately:

* **Augmentation** (training only) → `ai/data/transforms.py`, Module 07. It is random, and
  this pipeline must be byte-for-byte reproducible.
* **ImageNet normalise → tensor** → `ai/models/`, Module 07. It needs torch, and
  preprocessing stays torch-free so the identical code can run in the API process.

### Three deviations from the original spec, all deliberate

1. **Resize before denoise** ([[ADR-Index|ADR-024]]). The note itself said "measure it".
   Measured: bilateral filtering costs 30.1 ms at 1600x1200 and 4.0 ms at 224x224. The whole
   pipeline drops from ~114 ms to ~88 ms, about 23%, with near-identical output — `INTER_AREA`
   has already averaged away most sensor noise before the filter runs.

2. **The occlusion heuristic requires two conditions, not one.** See below.

3. **A pipeline fingerprint** ([[ADR-Index|ADR-025]]), which the spec did not ask for. Without
   it, "both sides build from the same YAML" prevents accidental divergence but *detects*
   nothing — edit the config after training and the model is served through a pipeline it was
   never trained on, silently.

## The occlusion heuristic — and the false positive it avoids

The obvious implementation is: an obstruction is close to the lens, therefore out of the
depth of field, therefore a large flat region with no texture. Find low-texture regions,
measure how much of the ROI they cover.

**That rejects legitimately smooth façades.** Freshly poured concrete, a rendered finish, and
a tarpaulin stretched flat as weatherproofing are all low-texture and all perfectly valid
subjects. A gate that silently discards good captures of a smooth building is worse than no
gate: the images vanish, the progress curve thins out, and nothing reports an error. This was
caught by a test, not by review.

So a region must be **both** low-texture **and** unlike the rest of the ROI in intensity —
compared against the ROI *excluding that region*, deliberately not against the ROI's overall
median, which fails exactly when it matters most: an occluder covering most of the façade
becomes the median, declares itself normal, and passes.

The cost is a miss when an occluder matches the façade's brightness — a grey truck against
grey concrete. **That trade is the right way round.** A missed occlusion contributes one bad
frame to a window whose value is a *median* over many frames, so it is absorbed
([[Progress-Calculation]] §2). A false rejection removes a good frame permanently.

A fully blocked lens — where there is no unobstructed remainder to compare against — is
caught by the **blur** gate instead: a surface pressed against a lens is never in focus.

## Critical implementation notes
- **Deterministic.** Same input → byte-identical output, including across process restarts.
  Training and serving are different processes; a pipeline that only agreed with itself in
  one would be exactly the skew this module exists to prevent.
- **Quality is measured on the decoded original**, before any resize or contrast pass. Both
  blur variance and mean brightness depend on resolution, so measuring later would make a
  photograph's score depend on pipeline settings — and the dataset audit ("how many of my own
  captures would have been rejected?") would mean nothing.
- **A quality failure is a result, not an exception.** Inference marks the image `rejected`;
  training uses the gate to audit the dataset. Neither is served by a traceback.
- **CLAHE on the L channel only.** Per-RGB-channel equalisation changes the channel ratios
  and therefore the hue — concrete comes out green. There is a test pinning this.
- **Letterbox, never stretch.** A stretched building changes its aspect, and the model learns
  those proportions. Padding is neutral grey (114,114,114), not black: after ImageNet
  normalisation black is a strong negative across all channels, which a first conv layer
  reads as a real edge along the padding boundary.
- **Every step is toggleable from YAML**, so the [[Evaluation-Plan]] ablation study is a
  config change and never a code change. A disabled step is *removed*, which also changes the
  fingerprint — correct, because a pipeline without denoising is a different pipeline.
- **An unknown step name is a startup error**, not a silently skipped stage. A typo should
  stop a training run before it spends an hour producing a model nobody intended.
- Thresholds are **not** restated in the YAML. They default to `ai/progress/constants.py`,
  their single definition site; setting them in the config would create a second one.

## Dependencies
Module 01. `opencv-python-headless`, `numpy`, `pillow`, `pyyaml` — all already declared.

## How to run
```bash
cd ai

# thesis figure + latency table, no dataset required
uv run python -m ai.preprocessing.demo --synthetic --out outputs/preprocess_demo --benchmark 20

# on a real capture
uv run python -m ai.preprocessing.demo --input dataset/raw/CB01/sample.jpg --out outputs/preprocess_demo

uv run pytest -q
```

```python
from ai.preprocessing import PreprocessingPipeline, CalibrationContext

pipeline = PreprocessingPipeline.from_config()      # or (path) for the detector
result = pipeline.run(image, CalibrationContext(homography=..., roi_polygon=...))
if result.quality.passed:
    ...  # result.image is 224x224x3 uint8
```

## Testing procedure — results

| # | Check | Result |
|---|---|---|
| 1 | Output exactly `(224,224,3)` uint8 for portrait, landscape, square, panorama | pass |
| 2 | Determinism: two runs byte-identical, and across fresh pipelines | pass |
| 3 | Gaussian-blurred and motion-blurred frames rejected | pass |
| 4 | 10 %-brightness frame rejected | pass |
| 5 | Large flat obstruction over the ROI rejected; small one tolerated | pass |
| 6 | Angled checkerboard rectifies to square (all 64 squares alternate correctly) | pass |
| 7 | CLAHE raises L std-dev without saturation, and preserves hue | pass |
| 8 | Truncated / empty / non-image bytes raise `DecodeError`, never segfault | pass |
| 9 | Benchmark on the target CPU | see below |

Plus, beyond the vault's list: fingerprint changes on parameter / order / toggle edits;
YAML and Python construction fingerprint identically; unknown step and bad parameter refused
at construction; a bad calibration degrades to "no rectification" rather than "no captures".

Test files: `tests/test_quality.py` (22), `tests/test_pipeline.py` (43),
`tests/test_transforms.py` (37), `tests/test_package.py` (11). **113 total.**

## Expected output — actual

```
pipeline    ai/configs/preprocessing.yaml
fingerprint e9d6212afd8c49b5
steps       quality_gate -> perspective_rectify -> normalize -> resize -> denoise
quality     {'passed': True, 'flags': [], 'blur_score': 680.678, 'brightness': 129.178, ...}
output      224x224

Latency — 1600x1200, median of 15 warm runs
  quality_gate               16.99 ms
  perspective_rectify         0.00 ms   (no-op: uncalibrated)
  normalize                  62.38 ms
  resize                      4.61 ms
  denoise                     3.91 ms
  TOTAL                      87.89 ms
```

`outputs/preprocess_demo/pipeline_strip.png` is the labelled before/after strip. Panels that
changed nothing are marked "(no change)" — without that, a reader reasonably concludes those
steps do nothing at all, rather than that they did nothing *here*.

**~88 ms/image on CPU** means a day's captures from four cameras cost well under a second of
preprocessing. This is not the bottleneck; inference will be.

## Done criteria
- [x] All steps implemented and individually toggleable via YAML
- [x] Quality gate returns scores + flags matching the documented thresholds
- [x] Deterministic and unit-tested
- [x] Before/after demo figure generated
- [x] Latency measured and recorded

## Handoffs
- **Module 07** builds `ai/data/transforms.py` (augmentation) *downstream* of this pipeline,
  and must write `pipeline.fingerprint` into the checkpoint metadata.
- **Module 08** uses `configs/preprocessing_detector.yaml` — separate file, separate
  fingerprint, so the two models can disagree about preprocessing without one silently
  inheriting the other's.
- **Module 09** compares the checkpoint's fingerprint against the live pipeline at model load
  and refuses a mismatch. It also converts `QualityReport` into `images.status='rejected'`.
- **Module 12** builds the calibration UI on `calibration.homography_from_corners`.

## Related
[[Progress-Calculation]] · [[Dataset-Spec]] · [[Module-07-Classifier-Training]] · [[Evaluation-Plan]]
