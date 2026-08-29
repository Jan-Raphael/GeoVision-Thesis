---
title: Progress Calculation
type: domain
status: canonical
updated: 2026-08-27
---

# Progress Calculation — the core algorithm

> This is the **thesis contribution**. It must be implemented as **pure functions** in
> `ai/progress/aggregator.py` with no I/O, no ORM, no torch — so it is fully unit-testable
> and can be walked through line by line during the defense.

> **Revised 2026-08-27 (ADR-038, closing Q18).** §1 now describes the fused
> classifier-confidence + YOLO-checklist formula, implemented and tested (`ai/progress/
> estimator.py`, `ai/progress/mapping.py`, `classes.yaml`). §5 was separately superseded by
> [[ADR-Index#ADR-037|ADR-037]] (owner-initiated approval, no automatic trigger) — unchanged by
> this revision. §2–§7 were never affected by either change: they operate on whatever `raw_pct`
> §1 hands them, regardless of how it's computed.

---

## 0. Why not "the model output is the progress"

A single frame classification is noisy: a truck parked in front of the façade, a rainy
afternoon, a low sun angle, or scaffolding can each flip a class. If the headline number
follows raw per-image predictions it will jitter and can go *backwards*, which destroys
trust. So progress is computed in **four stages**: per-image → per-device-per-window →
per-project-per-window → smoothed & ratcheted.

---

## 1. Per-image raw progress (ADR-038)

```python
def fused_raw_pct(class_index: int, confidence: float, detected_classes: Iterable[str]) -> float:
    """Where within a class's 20-point band one image falls."""
```

A classifier class only says *which* 20-point band an image falls in. Where within that band
is resolved by fusing two independent signals, **averaged**:

- `classifier_fraction = confidence` — the softmax probability of the predicted class, used as
  a proxy for how far into the stage's typical appearance the photo sits.
- `detector_fraction = (checklist elements detected) / (checklist size)` — YOLO's physical
  corroboration, using the per-class checklist in `classes.yaml`'s `detection_checklists`:

  | Class | Checklist |
  |---|---|
  | Foundation (`FDN`) | rebar, column |
  | Structural (`STR`) | rebar, beam, wall, roofing |
  | Roofing (`ROF`) | roofing, window, door, tile |
  | Finishing (`FIN`) | window, door, tile, railing, lighting |

  Each stage's own elements measure how settled it is; one element borrowed from the *next*
  stage catches an early transition (a window frame appearing near the end of roofing is real
  evidence the roof is nearly done, not noise).

```
sub_stage_fraction = (classifier_fraction + detector_fraction) / 2
raw_pct = stage_floor_pct + sub_stage_fraction * (stage_ceiling_pct - stage_floor_pct)
```

- **Confidence gate:** `MIN_CONFIDENCE = 0.60`, unchanged and independent of the above.
  - `confidence >= 0.60` → `eligible = True`
  - `confidence < 0.60` → stored, `low_confidence = True`, `eligible = False`
    (shown in the image feed with a badge; excluded from aggregation). Note that confidence now
    also shapes `raw_pct`'s *magnitude* (it is half of `sub_stage_fraction`), not just
    eligibility — a low-confidence prediction that still clears the gate pulls the fused
    percentage toward the stage floor, which the retired flat-lookup design did not do.
- **Quality gate** (runs before the model, in `ai/preprocessing/quality.py`): images
  rejected for blur (variance of Laplacian < 60), darkness (mean L < 25), or occlusion
  (> 40 % of the reference façade ROI covered by a near-field blob) are marked
  `status='rejected'` and never scored.
- **Deferred:** frame-to-frame physical change (comparing consecutive captures from the same
  device) was part of the original proposal but needs calibration data this project does not
  yet have — tracked in [[Open-Questions]] §3, future work.
- **The contract deadline plays no part in this formula.** It drives the project's schedule
  *status* instead — see [[Project-Status-Rules]]'s `is_behind_schedule`. Folding it into
  `raw_pct` would make the number stop meaning "what the camera can see was built" (ADR-038).

## 2. Per-device, per-window value

Default window = **1 calendar day** in the project's local timezone (configurable per
project: `daily` | `weekly`).

```
device_value(d, w) = median{ raw_pct(i) : i ∈ eligible images from device d in window w }
```

Median, not mean — one bad frame cannot drag the value.
If a device produced no eligible image in the window, it does not participate (it is not
treated as 0).

## 3. Per-project, per-window value (multi-camera fusion)

Each device carries a weight `devices.weight` (default `1.0`, owner-adjustable; a
`front_diagonal` camera seeing two façades may reasonably be weighted higher than a single
`back` view — the default weights below are the recommendation):

| Face | Faces seen | Default weight |
|---|---|---|
| `front_diagonal` | 2 | 1.5 |
| `back_diagonal` | 2 | 1.5 |
| `front` | 1 | 1.0 |
| `back` | 1 | 1.0 |

```
raw_project(w) = Σ_d ( weight_d · device_value(d, w) ) / Σ_d weight_d
```

This is the generalization of the spec's `(Cam1 + Cam2) / 2` — with equal weights it
reduces to exactly that.

## 4. Temporal smoothing + monotonic ratchet

```python
ALPHA = 0.30            # EMA factor
ADVANCE_CONFIRMATIONS = 2   # windows needed to move UP a macro stage
REGRESS_CONFIRMATIONS = 3   # windows needed to allow the number to move DOWN
```

1. **EMA:** `ema(w) = ALPHA * raw_project(w) + (1 - ALPHA) * ema(w-1)`
   (seed: `ema(w0) = raw_project(w0)`).
2. **Stage advancement guard:** the *macro stage* only advances when
   `ADVANCE_CONFIRMATIONS` consecutive windows place the project at the higher stage with
   eligible predictions. Prevents a one-day fluke from jumping "Framing → Roofing".
3. **Monotonic ratchet:** `displayed(w) = max(displayed(w-1), ema(w))`
   **unless** `REGRESS_CONFIRMATIONS` consecutive windows are lower — in which case the
   ratchet releases and `displayed(w) = ema(w)`, and a system remark is written
   (`"Progress regression detected — possible rework, demolition, or camera obstruction"`).
   Construction genuinely can go backwards (rework, typhoon damage); the system must
   represent that, but only on sustained evidence.
4. **Cap:** `displayed = min(displayed, 80.0)` — the machine ceiling.

## 5. Approval stage (the last 20%)

**Superseded 2026-08-18 by [[ADR-Index#ADR-037|ADR-037]].** There is no automatic
`awaiting_inspection` transition and no ML-triggered notification — the `completed`/`CMP`
class this depended on no longer exists ([[ADR-Index#ADR-036|ADR-036]]). The owner watches the
dashboard themselves and opens the approval action whenever they judge the exterior work
finished; nothing prompts them. (Retired design, kept for history:)

```
# retired — no longer runs
if displayed >= 80.0 and all four macro stages confirmed complete:
    project.approval_state = 'awaiting_inspection'
    → notification to owner + collaborators with inspect permission
    → remark: "All exterior stages complete. Manual inspection required."
```

Owner action `POST /projects/{id}/approve` (requires membership role with
`can_approve`, i.e. `owner` or `manager`) supplies `inspection_notes` and optional photos:

```
project.progress_pct   = 100.00
project.approval_state = 'approved'
project.status         = 'completed'
project.completed_at   = now()
```

Approval is **auditable**: who approved, when, with what notes. It cannot be done by the AI,
by a viewer, or by an unauthenticated request.

## 6. Per-stage percentages shown in the UI

For macro stage `S` with floor `f` and ceiling `c` (from [[Construction-Stages]]):

```
stage_pct(S) = clamp( (displayed - f) / (c - f) * 100, 0, 100 )
```

So a project at `displayed = 47%` shows: Foundation 100 %, Framing 100 %, Roofing 35 %,
Finishing 0 %, Approval 0 %.

## 7. Persistence

Every recomputation UPSERTs one row into `project_progress_snapshots` keyed by
`(project_id, window_start)`, storing `raw_pct`, `ema_pct`, `displayed_pct`, `macro_stage`,
the four stage percentages, `contributing_image_ids`, `device_weights`, and
`algorithm_version`. **The timeline graph reads this table** — never recomputed on the fly,
and reproducible after an algorithm change because `algorithm_version` is recorded.

`projects.progress_pct` / `projects.macro_stage` are denormalized copies of the latest
snapshot for cheap list rendering.

## 8. Worked example (put this in the thesis)

Project `NG_00`, two cameras, window = day.

| Day | Cam FD (w=1.5) images → median | Cam B (w=1.0) median | raw | ema (α=.3) | displayed |
|---|---|---|---|---|---|
| 1 | COL 28, COL 28 → 28 | COL 28 → 28 | 28.0 | 28.0 | 28.0 |
| 2 | SLB 34, COL 28 → 31 | SLB 34 → 34 | 32.2 | 29.3 | 29.3 |
| 3 | SLB 34 → 34 | SLB 34 → 34 | 34.0 | 30.7 | 30.7 |
| 4 | *(rain, all rejected)* | SLB 34 → 34 | 34.0 | 31.7 | 31.7 |
| 5 | WAL 40 → 40 | SLB 34 → 34 | 37.6 | 33.5 | 33.5 |
| 6 | truck occludes → COL 28 | WAL 40 → 40 | 32.8 | 33.3 | **33.5** ← ratchet held |

Day 6 shows the design working: a single occluded camera pulled the raw value down, the EMA
dipped, and the ratchet held the displayed number steady because only one window regressed.

## 9. Constants (single definition site)

`ai/progress/constants.py` — the definition site. Never re-typed by hand.

> **Corrected 2026-08-14.** This previously said "imported by both `ai/` and `backend/`".
> The backend **cannot** import it: its base dependency group deliberately excludes
> `geovision-ai` so the API process never loads torch (ADR-011), and installing the package
> to read two floats would pull torch into every API container.
>
> So the two or three values the backend genuinely needs are restated in
> `backend/app/domain/value_objects.py`, and `scripts/check_constants_parity.py` — run in CI
> — **parses both files and fails the build if they disagree**. No import in either
> direction, nothing installed. See [[ADR-Index|ADR-023]]. A constant used by only one side
> is not mirrored: making the backend carry a number it has no use for is worse duplication
> than none.

```python
MIN_CONFIDENCE = 0.60
ALPHA = 0.30
ADVANCE_CONFIRMATIONS = 2
REGRESS_CONFIRMATIONS = 3
MACHINE_CEILING_PCT = 80.0
APPROVAL_WEIGHT_PCT = 20.0
BLUR_THRESHOLD = 60.0
DARKNESS_THRESHOLD = 25.0
OCCLUSION_MAX_RATIO = 0.40
ALGORITHM_VERSION = "progress-v1"
```

## 10. Required unit tests

- monotonic ratchet holds on a single-window dip; releases after 3
- stage advances only after 2 confirmations
- low-confidence images excluded but persisted
- single-camera project == plain EMA of that camera
- equal-weight two-camera == simple average (matches the spec's formula)
- ceiling never exceeds 80 without approval
- approval sets exactly 100 and `completed`
- empty window (no eligible images) carries the previous value forward, does not zero it

## Related
[[Construction-Stages]] · [[Project-Status-Rules]] · [[Module-09-Progress-Engine]] · [[Evaluation-Plan]]
