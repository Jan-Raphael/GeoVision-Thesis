---
title: Annotation Guide (CVAT)
type: dataset
status: canonical
updated: 2026-08-12
---

# Annotation Guide — CVAT

Two annotation jobs run over the **same images**:

1. **Classification** — one tag per image (10 classes). CVAT *tags*, exported as CSV.
2. **Detection** — bounding boxes (7 classes). Exported as **YOLO 1.1**.

## CVAT setup

- Project `GeoVision-Classification`, labels = the 10 fine classes (see [[Construction-Stages]]).
- Project `GeoVision-Detection`, labels = `column, wall, roof, steel_bar, scaffolding, worker, equipment`.
- Task per data source (`site_CB01`, `timelapse_youtube_01`, …) so provenance survives export.
- Export: **CVAT for images 1.1** (tags) → converted by `scripts/prepare_dataset.py` into
  `dataset/labels/classification.csv`; **YOLO 1.1** → `dataset/labels/detection/`.

## Classification rules (decide ties this way)

1. **Label the most advanced stage that is clearly visible.** Construction is cumulative —
   a building with walls still has a foundation. The label is the *frontier* of progress.
2. **Clearly visible** = you could convince a classmate in one sentence. If you're arguing
   with yourself, use rule 3.
3. **Ambiguous → skip.** A skipped image costs nothing. A wrong label poisons both training
   and the test set. Track skips; if a class has many, that's a finding for the thesis.
4. Judge the **building**, not the site. Debris, parked trucks, and workers are noise.
5. If several structures are in frame, label the **primary subject** (the one the camera was
   mounted for, largest/most central). Note multi-building frames in `notes`.
6. Night, heavily rained-out, or > 50 % occluded images → **exclude** from the dataset (they
   are what the runtime quality gate rejects anyway — [[Progress-Calculation]]).

Boundary table (memorize this): see the "Visual disambiguation notes" in
[[Construction-Stages]].

### The `completed` class
Reserve it for a genuinely finished exterior: no scaffolding, clean site, painted/finished
façade, windows and doors installed. "Almost done" is `finishing`. Being strict here is what
makes the 80 % → manual-inspection handoff meaningful.

## Detection rules

- Box the **visible extent** of the object; do not guess occluded parts beyond ~20 %.
- `column`: one box per distinct vertical structural member.
- `wall`: one box per contiguous wall plane, not per block.
- `steel_bar`: box the *cluster* of exposed rebar, not individual bars.
- `scaffolding`: the whole contiguous assembly as one box.
- `worker`: any person, including partially visible (head + torso is enough).
- `equipment`: excavator, mixer, crane, truck, generator, wheelbarrow.
- Minimum box size 12×12 px; skip anything smaller.
- Do **not** box objects reflected in glass or printed on signage.

## Quality control

- **Double-annotate 10 %** of images with a second annotator and compute **Cohen's κ**.
  Target κ ≥ 0.75. Report the value in the thesis — it quantifies label reliability and is
  a strong methodology point most undergraduate theses skip.
- The advisor (or a civil engineer) reviews a 50-image sample against the stage definitions;
  record the review date and outcome here.
- Every disagreement resolved goes into the boundary table as a new example.

## Consistency log

| Date | Decision | Rationale |
|---|---|---|
| _(append every judgement call you make while annotating — this becomes a thesis appendix)_ | | |

## Related
[[Dataset-Spec]] · [[Construction-Stages]] · [[Module-07-Classifier-Training]] · [[Module-08-YOLO-Detection]]
