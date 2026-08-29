# GeoVision — Model Training Runbook

Step-by-step process for training both models the classifier/detector pipeline needs:
**YOLOv8** (object detector, annotated via Roboflow, trained on Kaggle) and **ResNet18**
(stage classifier, split locally, trained on Kaggle). Written 2026-08-28, against the actual
code and files in this repo — every path and command below is real, not illustrative.

Related: [[Module-07-Classifier-Training]] · [[Module-08-YOLO-Detection]] ·
`ai/notebooks/kaggle_train_classifier.ipynb` · `ai/notebooks/kaggle_train_detector.ipynb`

---

## At a glance

| | ResNet18 (classifier) | YOLOv8 (detector) |
|---|---|---|
| Needs annotation? | No — folder name **is** the label | Yes — bounding boxes, drawn by hand |
| Annotation tool | — | Roboflow |
| Where images come from | `dataset/raw/` (already sorted into class folders) | `dataset/raw/` (same images, boxes added) |
| Where it trains | Kaggle (or locally on CPU, slower) | Kaggle (CPU is impractically slow) |
| Code that runs it | `ai/src/ai/training/train_classifier.py` | `ai/src/ai/training/train_detector.py` |
| Status as of 2026-08-28 | **Already run once** — `outputs/runs/resnet18-v1-run1/best.pt`, macro-F1 0.4603 | **Cannot run yet** — no annotations exist |

---

## Part 1 — YOLOv8: Roboflow, then Kaggle

### What you need

- A free [Roboflow](https://roboflow.com) account.
- A free [Kaggle](https://kaggle.com) account, **phone-verified** (Settings → Phone
  Verification) — this is what unlocks GPU quota; an unverified account cannot attach an
  accelerator to a notebook.
- The images to annotate — already sitting in `dataset/raw/<site>/<class>/`. Start with
  **Structural** (381 images, the most of any class — best return on annotation time).
- The 10 object names this project already committed to (ADR-036), spelled **exactly** this
  way, lowercase: `wall, beam, column, rebar, roofing, window, door, tile, railing, lighting`.
  Spelling matters more than the order you create them in — see the note at the end of this
  section for why.

### Step 1 — Create the Roboflow project

1. Roboflow dashboard → **Create New Project**.
2. Project type: **Object Detection**.
3. Name it something identifiable, e.g. `geovision-detection`.
4. Annotation group: leave default.

### Step 2 — Upload images

1. On the project's **Upload** tab, drag in images from `dataset/raw/Malinoville/Structural/`
   and `dataset/raw/Aldea Grove/2/Structural/` (and `.../3/Structural/`) to start — these are
   the Structural-class images.
2. Roboflow accepts batches; upload in whatever chunks are convenient. You don't need to
   upload every class at once — annotate Structural first, generate a first dataset version,
   and add Roofing/Finishing images in a later batch (Roboflow lets you add images to an
   existing project and regenerate a new version).

### Step 3 — Annotate

1. Open the **Annotate** tab. Roboflow queues every unannotated image.
2. For each image, draw a bounding box around every visible instance of the 10 objects that
   applies — a Structural-stage photo will mostly show `column`, `beam`, `rebar`, `wall`
   (CHB blockwork); a Finishing-stage photo will show `window`, `door`, `tile`, `railing`,
   `lighting`. Not every image has every object — that's expected and correct, it's exactly
   what makes detection informative.
3. Type the class name when prompted. **Use the exact lowercase names above** — Roboflow
   creates a new class the first time you type it, and a typo (`"Wall"` vs `"wall"`, or
   `"windows"` vs `"window"`) becomes a second, wrong class silently.
4. This is the slowest part of the whole pipeline. A few dozen images is a meaningful start;
   don't feel obligated to annotate all 381 Structural images before moving on — partial
   coverage trains a real (if data-limited) model, the same way the classifier's first run did.

### Step 4 — Generate and export a dataset version

1. **Health Check** tab (optional but useful): shows class balance across what's annotated so
   far — a quick sanity check before spending Kaggle GPU time.
2. **Generate** tab → **Create New Version**:
   - **Preprocessing**: Resize → **Stretch to 640×640** (matches this project's training
     recipe, `imgsz=640`).
   - **Augmentation**: **skip this** — `ai/training/train_detector.py` already applies its own
     augmentation (`hsv_v`, `degrees`, `fliplr`, `mosaic`) through ultralytics when it trains.
     Doubling up augmentation at the dataset level makes results harder to reason about for no
     benefit.
   - **Train/Valid/Test split**: Roboflow defaults to something like 70/20/10 at the image
     level. Note the same leakage caveat `Dataset-Spec.md` raises for the classifier applies
     here too — Roboflow's free tier splits by image, not by building, so if near-duplicate
     frames from one camera session exist, they can land in different splits. Worth knowing,
     not worth blocking on for a first pass.
   - Click **Create**.
3. **Export** tab → Format: **YOLOv8**. Two ways to get it into Kaggle:
   - **Recommended — "Show download code":** Roboflow gives you a short Python snippet using
     the `roboflow` package and your API key. This downloads the dataset directly onto Kaggle's
     disk inside the notebook — no manual zip/upload round-trip. Copy this snippet; you'll
     paste it into the Kaggle notebook in Step 5.
   - **Alternative — "Download zip"**: downloads to your computer; you'd then upload it as a
     Kaggle Dataset (**kaggle.com/datasets → New Dataset**) and attach it like the classifier
     dataset in Part 2. Slower, but works if you'd rather not put a Roboflow API key in a
     notebook cell.

### Step 5 — Train on Kaggle

1. Open `ai/notebooks/kaggle_train_detector.ipynb` in Kaggle: **kaggle.com/code → New
   Notebook → File → Import Notebook**, and select this file from your machine.
2. **Add Input** (right sidebar) → attach the **`geovision-ai-src`** dataset (a zip of this
   repo's `ai/` folder — same one the classifier notebook uses; see Part 2 Step 2 if you
   haven't made this yet).
3. **Settings** (right sidebar) → **Accelerator** → **GPU T4 x2** (or whatever's available).
   YOLOv8 on CPU is, in this project's own training recipe notes, "painfully slow" — this
   model genuinely needs the GPU, more than the classifier does.
4. Add a new cell right after the "Install the ai package" cell with your Roboflow download
   snippet from Step 4, e.g.:

   ```python
   !pip install -q roboflow
   from roboflow import Roboflow
   rf = Roboflow(api_key="YOUR_API_KEY")
   project = rf.workspace("YOUR_WORKSPACE").project("geovision-detection")
   dataset = project.version(1).download("yolov8")
   print(dataset.location)  # this is your DATA_YAML's folder
   ```

5. In the **Configuration** cell, point `DATA_YAML` at what the snippet printed, e.g.:

   ```python
   DATA_YAML = Path(dataset.location) / "data.yaml"
   ```

6. **Run All.**

Roboflow's own `data.yaml` is what actually describes the downloaded images/labels — use it
directly rather than the placeholder committed at `dataset/labels/detection/data.yaml` (that
file exists as a spec of the target class list, not as something Roboflow's export needs to
match). **A checkpoint is self-describing**: `ultralytics` stores its own trained class mapping
inside the `.pt` file, and `ai/models/yolov8.py` reads class names from the loaded checkpoint at
inference time — not from any `data.yaml` on disk. So Roboflow doesn't need to use the same
*class index order* as this project's placeholder file; it only needs to use the same *class
names*, spelled identically, since `classes.yaml`'s detection checklists (`ai/progress/
estimator.py`) match by name, not by index.

### Step 6 — Get the weights, evaluate

1. Kaggle's **Output** tab (after the run finishes) has
   `outputs/runs/detector/<name>/weights/best.pt`, plus ultralytics' own training curves and
   PR curves.
2. Download it to this repo at `models/detector/yolov8n/v1/best.pt`.
3. Run the evaluation module that already exists:

   ```bash
   cd ai
   uv run python -m ai.evaluation.detector_eval --weights ../models/detector/yolov8n/v1/best.pt
   ```

   Produces mAP@0.5, mAP@0.5:0.95, per-class AP, and PR curves under
   `outputs/evaluation/detector/`.
4. Publish the checkpoint (Open-Questions Q10): a **Kaggle Dataset/Model** for the working
   copy (from the Output tab — zero extra step, it's already there), and a **GitHub Release**
   asset for whichever version actually goes in front of the panel.

---

## Part 2 — ResNet18: split locally, then Kaggle

### What you need

- The `ai/` project already set up locally with `uv` (it is, in this repo).
- The sorted dataset at `dataset/raw/<site>/<class>/` (already done — see
  `Dataset-Spec.md`/`Progress-Log.md` for the current counts).
- A free, phone-verified Kaggle account (same requirement as Part 1).

### Step 1 — Split the dataset (run locally)

```bash
cd ai
uv run python ../scripts/split_dataset.py
```

This writes `dataset/processed/{train,validation,test}/<class>/` and
`dataset/metadata/split_manifest.csv`. It groups by **building**, not just top-level site
folder (see the script's own docstring for why — `Aldea Grove` turned out to hold three
separate houses), so re-run this any time new sorted images are added to `dataset/raw/` rather
than editing `dataset/processed/` by hand.

Use `--dry-run` first if you just want to see the planned split without copying files:

```bash
uv run python ../scripts/split_dataset.py --dry-run
```

### Step 2 — Package for Kaggle

Two Kaggle Datasets, uploaded once and re-uploaded (as a new **version**) whenever their
contents change:

1. **`geovision-ai-src`** — zip this repo's `ai/` folder (needs `ai/src/`, `ai/pyproject.toml`;
   `ai/.venv/` can be excluded, it isn't needed). Re-zip and upload a new version whenever the
   training code changes.
2. **`geovision-dataset-processed`** — zip `dataset/processed/` (the output of Step 1).
   Re-zip whenever the dataset or split changes.

Upload both at **kaggle.com/datasets → New Dataset → Upload**, one zip each.

### Step 3 — Train on Kaggle

1. Open `ai/notebooks/kaggle_train_classifier.ipynb` in Kaggle (**File → Import Notebook**).
2. **Add Input** → attach both `geovision-ai-src` and `geovision-dataset-processed`.
3. **Settings → Accelerator → GPU** (optional but much faster — the local CPU run in this repo
   took about 15 minutes for 24 epochs; a GPU run is faster still and lets you iterate).
4. In the **Configuration** cell, confirm `PROCESSED_ROOT` matches your dataset's actual slug —
   Kaggle shows the exact mount path (`/kaggle/input/<slug>/...`) once attached; edit the
   variable if it doesn't match what's printed.
5. **Run All.**

### Step 4 — Get the weights, evaluate

1. Kaggle's **Output** tab has `outputs/runs/resnet18-kaggle/{best.pt, last.pt, metrics.csv,
   confusion_matrix.json, config.json}` directly after the run.
2. Download `best.pt` to this repo at `models/classifier/resnet18/v1/best.pt`.
3. Run the evaluation CLI that already exists:

   ```bash
   cd ai
   uv run gv-evaluate --classifier ../models/classifier/resnet18/v1/best.pt \
       --test-images ../dataset/processed/test
   ```

   Produces the confusion matrix, per-class precision/recall/F1, and accuracy figures under
   `outputs/evaluation/`.
4. Publish the checkpoint (Q10): GitHub Release asset for the defense copy, Kaggle Dataset/
   Model for the working copy — same pattern as the detector.

### Alternative — train locally instead of on Kaggle

Kaggle is for GPU speed and for a second machine's spare compute, not a hard requirement — the
classifier's first real checkpoint in this repo (`outputs/runs/resnet18-v1-run1/best.pt`,
macro-F1 0.4603) was trained entirely on a local CPU:

```bash
cd ai
uv run python -m ai.training.train_classifier --config src/ai/configs/train_resnet18.yaml
```

Add `--smoke-test` to cap it at 2 epochs first, as a quick "does this even run" check before a
full training run:

```bash
uv run python -m ai.training.train_classifier --config src/ai/configs/train_resnet18.yaml --smoke-test
```

---

## Notes and common pitfalls

- **Re-run the split after adding images.** `scripts/split_dataset.py` is idempotent and safe
  to re-run — it recomputes the best group assignment and re-copies everything. Don't hand-edit
  `dataset/processed/`.
- **Class name spelling is what matters for YOLO, not class order.** See the note at the end of
  Part 1, Step 5.
- **The classifier's checkpoint refuses to load against a mismatched `classes.yaml`.**
  `ai/models/resnet18.py`'s `ResNet18Classifier` checks the checkpoint's saved class list
  against the currently-loaded `classes.yaml` and raises rather than silently mislabeling — if
  you ever see that error, it means training happened against a different class definition than
  the one now in the repo (e.g. before a rescope like ADR-036/038).
- **CPU fallback works for both**, but only the classifier is fast enough for it to be a
  reasonable default — YOLOv8 on CPU is a last resort, not a workflow.
- **A partially-annotated YOLO dataset is a valid training set.** You do not need every image
  boxed before running Step 5 — more annotation later just means retraining, not redoing.
