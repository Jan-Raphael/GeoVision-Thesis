---
title: Dataset Spec
type: dataset
status: canonical
updated: 2026-08-28
---

# Dataset Specification

## Structure

```
dataset/
├── raw/<PROJECT>/                     # untouched originals, any name
├── processed/
│   ├── train/<class_name>/            # 70 %
│   ├── validation/<class_name>/       # 15 %
│   └── test/<class_name>/             # 15 %
├── augmented/                         # only if pre-baked; runtime aug is preferred
├── labels/
│   ├── classification.csv             # CVAT tag export → filename,class
│   └── detection/{train,val,test}/    # YOLO .txt per image + data.yaml
└── metadata/
    ├── metadata.csv                   # tracked in git
    └── progress_reference.csv         # tracked in git — see [[Construction-Stages]]
```

> **Revised 2026-08-18 ([[ADR-Index#ADR-036|ADR-036]]).** The classifier now has 4 classes,
> not 10 — see [[Construction-Stages]]. `dataset/raw/`'s existing per-site folders
> (`Foundation`, `Structural`, `Roofing`, `Finishing`) already match this table; no relabeling
> is needed at the macro level, only for the images still sitting untagged at a site's root.

Class folder names are the exact lowercase snake_case class names:
`foundation, structural, roofing, finishing`.

## Split policy — 70 / 15 / 15

**Stratified by class AND grouped by project/site.** This matters more than the ratio:

> ⚠ If images of the *same building* appear in both train and test, the model can memorize
> that building and the reported accuracy is inflated. Split **by site**, so every image of a
> given construction site lands entirely in one split. `scripts/split_dataset.py` must
> implement grouped stratified splitting (`sklearn.model_selection.StratifiedGroupKFold`)
> with `group = project_id`. State this explicitly in the thesis methodology — examiners
> ask about leakage.

Seed fixed at `42`; the split manifest is written to `dataset/metadata/split_manifest.csv`
and committed so results are reproducible.

## `metadata.csv`

```csv
image_name,project,stage,gps_lat,gps_lon,captured_at,camera,face,weather,source,original_name,notes
GV_CB01_FDN_0001.jpg,CB01,foundation,13.628000,123.185000,2026-03-04T07:00:00Z,ESP_CB01_FD,front_diagonal,clear,device,NG_00_20260304T070000Z_001.jpg,
```

`original_name` links a promoted production capture back to its runtime filename
([[Naming-Conventions]]).

## Target volume

| Class | Minimum | Comfortable |
|---|---|---|
| each of the 4 | 150 | 400+ |
| **total** | **600** | **1 600+** |

Lower than the old 1,500-total floor because there are fewer classes now, **not** because less
data is needed overall — the resolution that used to come from 10 fine classes now comes from
the classifier-confidence + YOLO-checklist fusion within each of these 4 buckets
([[ADR-Index#ADR-038|ADR-038]], closing Q18), which needs its own detection-annotated image
volume (same images, bounding boxes added) tracked separately.

**Split, 2026-08-28 (`scripts/split_dataset.py`):** groups are discovered automatically (any
folder whose immediate children are the four class names), not assumed from top-level site
folder names — `Aldea Grove` turned out to hold three separate houses (`1/2/3`) under one name,
which a naive per-site split would have leaked across train/test. With only six real groups
today, the closest achievable split to 70/15/15 while keeping every class present in every
split is lumpy rather than clean:

| Class | Total | Train | Validation | Test |
|---|---|---|---|---|
| Foundation | 37 | 16 (43%) | 5 (14%) | 16 (43%) |
| Structural | 381 | 267 (70%) | 49 (13%) | 65 (17%) |
| Roofing | 110 | 37 (34%) | 50 (45%) | 23 (21%) |
| Finishing | 122 | 48 (39%) | 55 (45%) | 19 (16%) |

State this plainly in the thesis methodology, the same way the grouped-split leakage guard
itself should be stated — more groups (more distinct real sites) is what actually fixes this,
not a different split algorithm.

**Team's own estimate (2026-08-27, Q5): 80-130 images/class realistically achievable** —
below the 150/class minimum above. **Final, verified `dataset/raw/` tally (2026-08-27), after
sorting the previously-uncategorized photos and de-duplicating HEIC/JPG pairs:**

| Class | Count | vs. team's 80-130 estimate |
|---|---|---|
| Foundation | 37 | still short — the one class worth actively collecting more of |
| Structural | 381 | well past the "comfortable" band |
| Roofing | 110 | within estimate |
| Finishing | 122 | within estimate |

Two things surfaced doing this count. **50 of `Paramjeet/`'s photos were `.HEIC`** (the iPhone
default format) — invisible to the entire pipeline, since `ai/preprocessing/pipeline.py`'s
`load_image` goes through `cv2.imdecode`, which cannot decode HEIC at all. Every one now has a
`.jpg` copy sitting alongside its original (converted with `pillow-heif`, not a committed
dependency — see `scripts/audit_dataset_quality.py`), so they finally count toward training.
**A separate `Online Dataset/` source turned out to be entirely `.png`**, not `.jpg` — already
readable by the pipeline, just missed by an earlier audit script that only looked for
`.jpg`/`.jpeg`. Both are worth remembering if a future capture source shows up in a format that
looks like an image count but silently isn't one to any script here.

With a fixed-angle camera producing 2 images/day, one site yields ~60 images/month — not
enough alone. **Plan for all four sources:**

1. Your own ESP32 deployments (the authentic, defensible core).
2. Public construction-progress datasets and image sets (cite licences).
3. Web-scraped/stock construction imagery, manually curated (check licences; document).
4. Frames extracted from construction time-lapse videos on YouTube (highest yield per hour
   of work — one time-lapse can cover every stage of one building; record source URLs and
   licence terms in `metadata.csv`).

Class imbalance is still plausible even at 4 classes (a project spends longer in some stages
than others, and `dataset/raw/`'s current counts already skew toward `structural`). Handle
with class-weighted `CrossEntropyLoss` + a `WeightedRandomSampler`, and **report per-class
recall**, not just accuracy.

## Augmentation (Albumentations **2.x**, applied at train time)

> ⚠ The project pins **albumentations 2.x** (ADR-014). Several transforms changed signature
> from 1.x — most notably `RandomResizedCrop`, which now takes `size=(h, w)` instead of two
> positional arguments. Code copied from 1.x tutorials will raise a `TypeError`.

```python
train_tf = A.Compose([
    A.LongestMaxSize(max_size=256),
    A.PadIfNeeded(min_height=256, min_width=256),
    A.RandomResizedCrop(size=(224, 224), scale=(0.75, 1.0)),
    A.HorizontalFlip(p=0.5),
    A.RandomBrightnessContrast(0.25, 0.25, p=0.7),   # time-of-day
    A.HueSaturationValue(10, 20, 10, p=0.3),          # white balance
    A.RandomShadow(p=0.2), A.RandomSunFlare(p=0.05),
    A.RandomRain(p=0.1), A.RandomFog(p=0.1),          # tropical weather
    A.MotionBlur(blur_limit=5, p=0.2), A.GaussNoise(p=0.2),
    A.ShiftScaleRotate(0.05, 0.1, 7, p=0.5),          # slight mount shift
    A.CoarseDropout(max_holes=4, p=0.2),              # partial occlusion (trucks, workers)
    A.Normalize(IMAGENET_MEAN, IMAGENET_STD), ToTensorV2(),
])
```

Val/test: resize + center-crop + normalize **only**. No augmentation, ever.

❌ Do **not** use `VerticalFlip` or large rotations — buildings have a canonical orientation
and an upside-down building is not a real input. ❌ Do not use `RandomCrop` so aggressive
that the building leaves the frame.

## Detection dataset (YOLOv8)

Classes (revised 2026-08-18, [[ADR-Index#ADR-036|ADR-036]]): `wall (CHB wall), beam, column,
rebar, roofing, window, door, tile, railing, lighting` (10 classes — indices to be frozen in
`dataset/labels/detection/data.yaml` once annotation starts; supersedes the old 7-class list
in [[Module-08-YOLO-Detection]]). ~300–500 annotated images is workable for a comparison
model; annotate the *same* images used for classification so the two models can be compared on
identical inputs. Detection is no longer purely a corroboration side-channel — it's a direct
input to the fused progress calculator once [[Open-Questions|Q18]] is resolved, so its
annotated volume matters more than it did under the old advisory-only design.

## Data hygiene

- Deduplicate by perceptual hash before splitting (time-lapse frames are near-identical).
- Drop images where the building is < 20 % of the frame.
- Keep a small **holdout "hard set"** of genuinely ambiguous images for the qualitative
  section of the thesis.
- Never delete `raw/` — every processed image must be traceable to an original.

## Related
[[Annotation-Guide]] · [[Construction-Stages]] · [[Module-07-Classifier-Training]] · [[Evaluation-Plan]]
