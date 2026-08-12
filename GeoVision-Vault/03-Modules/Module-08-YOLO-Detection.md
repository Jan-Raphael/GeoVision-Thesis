---
title: Module 08 — YOLOv8 Object Detection
type: module
module: 8
status: planned
updated: 2026-08-12
---

# Module 08 — YOLOv8 Detection (comparison & corroboration model)

## Scope
Train and serve a YOLOv8 detector for construction objects, and use it to **corroborate** the
classifier rather than sit beside it decoratively.

## Classes (indices frozen in `data.yaml`)
`0 column · 1 wall · 2 roof · 3 steel_bar · 4 scaffolding · 5 worker · 6 equipment`

## Deliverables
- `dataset/labels/detection/data.yaml` — paths + class names.
- `ai/models/yolov8.py` — thin wrapper implementing the `ObjectDetector` protocol:
  `detect(image) -> list[Detection] + counts + inference_ms`. Ultralytics stays behind this
  wrapper; nothing else in the codebase imports `ultralytics`.
- `ai/training/train_detector.py` — CLI wrapping `YOLO('yolov8n.pt').train(...)`.
- `ai/evaluation/detector_eval.py` — mAP@0.5, mAP@0.5:0.95, per-class AP, PR curves,
  annotated sample images.
- `ai/progress/corroboration.py` — **the interesting part**: rule-based stage inference from
  object counts, compared against the classifier.

## Corroboration rules (heuristic, documented as such)
```python
def stage_from_detections(counts: dict[str, int]) -> MacroStage | None:
    if counts["roof"] >= 1 and counts["scaffolding"] == 0:  return FINISHING
    if counts["roof"] >= 1:                                  return ROOFING
    if counts["wall"] >= 2:                                  return FRAMING
    if counts["column"] >= 2 or counts["steel_bar"] >= 1:    return FRAMING
    return None            # not enough evidence — abstain, don't guess
```
Output per image: `agreement ∈ {agree, disagree, abstain}`. Aggregate agreement rate goes in
the results chapter ([[Evaluation-Plan]] §3).

**The classifier remains authoritative for progress.** Detection results are stored, shown,
and reported, but a disagreement only raises a `low_confidence`/review flag — it never
overrides the progress number. Two models silently fighting over one number is a bug, not a
feature; state this design choice explicitly.

## Training recipe
| Setting | Value |
|---|---|
| Model | `yolov8n.pt` (nano — speed) ; also train `yolov8s` if time allows |
| Image size | 640 |
| Epochs | 100, `patience=20` |
| Batch | 16 (8 on small VRAM) |
| Augment | ultralytics defaults + `hsv_v=0.5` (lighting), `degrees=5`, `fliplr=0.5`, `mosaic=1.0` |
| Device | `0` if CUDA else `cpu` |

> YOLO training on CPU is painfully slow. Use Google Colab/Kaggle free GPU for this module if
> no local GPU exists, then commit the resulting weights. Note the training environment in the
> thesis.

## Critical implementation notes
- Annotate detection on the **same images** used for classification so the two are comparable.
- Non-max suppression: `conf=0.35`, `iou=0.45` for serving (tune on the val set; record it).
- `workers` and `equipment` are volatile between frames — do not let their counts influence
  progress; they are for the "site activity" panel and the reports.
- Store normalized `xywh` in `detections` so boxes render on any thumbnail size.
- Cap stored detections at 50/image (a crowded frame shouldn't bloat the DB).
- Detection runs **after** classification in the worker; if YOLO fails, the prediction still
  succeeds — detection is non-blocking and non-critical.

## Dependencies
Modules 01, 06. `ultralytics`. (Ultralytics pulls torch — confirm it pulls **no** TensorFlow.)

## How to run
```bash
python -m ai.training.train_detector --data dataset/labels/detection/data.yaml \
       --model yolov8n.pt --epochs 100 --imgsz 640
python -m ai.evaluation.detector_eval --weights models/detector/yolov8n/v1/best.pt
```

## Testing procedure
1. `data.yaml` paths resolve; label files match image files 1:1; no out-of-range class index.
2. Label sanity: all bbox values in `[0,1]`, width/height > 0.
3. Train 2 epochs on a 20-image subset → completes, produces weights.
4. Wrapper returns the documented `Detection` objects with normalized coordinates.
5. Empty image (blank sky) → zero detections, no crash.
6. Corroboration unit tests: each rule branch, plus the abstain case.
7. Benchmark inference ms on CPU and GPU.
8. Agreement analysis runs over the test set and writes a confusion table.

## Expected output
```
models/detector/yolov8n/v1/best.pt
outputs/evaluation/detector/{pr_curve.png,confusion.png,samples/*.jpg,metrics.json}
```
Plus the classifier-vs-detector agreement table.

## Done criteria
- [ ] Detection dataset annotated and validated
- [ ] YOLOv8 trained with recorded mAP
- [ ] Wrapper implements the shared protocol; ultralytics is not imported anywhere else
- [ ] Corroboration rules implemented, tested, and evaluated
- [ ] Detection failure cannot break the prediction path

## Related
[[Annotation-Guide]] · [[Module-07-Classifier-Training]] · [[Module-09-Inference-Service]] · [[Evaluation-Plan]]
