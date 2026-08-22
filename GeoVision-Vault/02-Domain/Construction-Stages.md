---
title: Construction Stages
type: domain
status: canonical
updated: 2026-08-18
---

# Construction Stages — Two-Layer Model ⚖

> **Revised 2026-08-18 (ADR-036).** Layer 1 was originally 10 fine classes; the classifier now
> predicts the 4 macro-aligned classes directly, one per macro stage. Layer 2 (macro stages +
> approval) is unchanged. The old 10-class table is kept below, struck through, because the
> "Visual disambiguation notes" it anchors still explain *why* YOLO's detection classes were
> chosen the way they were ([[ADR-Index#ADR-036|ADR-036]]) — it no longer describes what the
> classifier does.

The original architecture specified **10 classes**. The dashboard spec specified **4 stages
at 20% each + a 20% approval stage**. ADR-001 originally kept both as two layers; ADR-036
narrowed Layer 1 to match Layer 2 one-for-one, moving the finer structural/finishing signal to
YOLO detection instead of a 10-way classifier boundary.

- **Layer 1 — Classifier classes (ML layer).** What the ResNet18 actually predicts. **4
  classes**, one per macro stage — chosen because the team's own collected dataset was already
  organized this way, and a 4-way judgement is materially cheaper and less disagreement-prone
  to annotate than a 10-way one.
- **Layer 2 — Macro stages (business/UX layer).** What the owner and the public see.
  A deterministic, hand-authored mapping table. No learning involved — it is a
  domain rule, reviewable by a civil engineer, and defensible in the oral defense.

---

## Layer 1 — Classifier classes (model output)

| # | Class | Token | Macro stage | Nominal progress % (stage ceiling) |
|---|---|---|---|---|
| 0 | Foundation | `FDN` | Foundation | 20 |
| 1 | Structural | `STR` | Framing | 40 |
| 2 | Roofing | `ROF` | Roofing | 60 |
| 3 | Finishing | `FIN` | Finishing | 80 |

**No `Completed` class.** The machine ceiling is still **80%**, but nothing auto-detects
"done" anymore — the owner decides when to inspect and approve. See
[[ADR-Index#ADR-037|ADR-037]] and [[Progress-Calculation]] §5.

**Where a captured image falls *within* a stage's 20-point range (e.g. early vs late
`structural`) is not decided by the classifier at all.** That resolution comes from a fused
signal combining YOLO detections and frame-to-frame physical change — the exact formula is
**undecided**, tracked as [[Open-Questions|Q18]]. Until Q18 is resolved, every image inside a
stage nominally reports that stage's *ceiling* (the table above), which is a regression from
the old 10-class resolution and is the whole reason Q18 exists.

`class_index` order above is **frozen** once trained — it is the index order the checkpoint
will use. Adding a class requires retraining and a new model version; never reorder.

Canonical definition file: `ai/src/ai/configs/classes.yaml` (generated into
`dataset/metadata/progress_reference.csv` by `scripts/generate_progress_reference.py`). **Not
yet updated to the 4-class table above** — still holds the 10-class definition pending the
Q18 decision, since regenerating it is a code change and Rule 0 says vault first.

<details>
<summary>Retired 10-class table (kept for the YOLO class-selection rationale only — click to expand)</summary>

| # | Class | Token | Macro stage | Nominal progress % |
|---|---|---|---|---|
| 0 | Site Clearing | `CLR` | Foundation | 4 |
| 1 | Excavation | `EXC` | Foundation | 9 |
| 2 | Footings | `FTG` | Foundation | 14 |
| 3 | Foundation | `FDN` | Foundation | 20 |
| 4 | Columns | `COL` | Framing | 28 |
| 5 | Slab | `SLB` | Framing | 34 |
| 6 | Walls | `WAL` | Framing | 40 |
| 7 | Roof | `ROF` | Roofing | 60 |
| 8 | Finishing | `FIN` | Finishing | 80 |
| 9 | Completed | `CMP` | Approval (pending) | 80 |

</details>

## Layer 2 — Macro stages (UI)

| Stage | Range | Weight | Completed when |
|---|---|---|---|
| Foundation | 0–20 % | 20 | classifier class `FDN` confirmed |
| Framing | 20–40 % | 20 | classifier class `STR` confirmed |
| Roofing | 40–60 % | 20 | classifier class `ROF` confirmed |
| Finishing | 60–80 % | 20 | classifier class `FIN` confirmed |
| **Approval / Checking** | 80–100 % | 20 | **owner manually inspects and approves — no automatic trigger ([[ADR-Index#ADR-037\|ADR-037]])** |

The Project Folder page shows five bars. The first four are AI-driven (pending
[[Open-Questions\|Q18]] for sub-stage resolution within each); the fifth is a human action with
an explicit "Mark as Inspected & Complete" button, an inspection note, and an optional
inspection photo upload — the owner opens this themselves whenever they judge it ready, not in
response to any system prompt.

## `progress_reference.csv` (tracked in `dataset/metadata/`)

**Not yet regenerated for the 4-class table** — the CSV on disk still reflects the retired
10-class definition (see the collapsed table above) pending the Q18 decision and the
`ai/src/ai/configs/classes.yaml` code change. Once regenerated it will look like:

```csv
class_index,class_name,token,macro_stage,nominal_progress_pct,stage_floor_pct,stage_ceiling_pct
0,Foundation,FDN,foundation,20,0,20
1,Structural,STR,framing,40,20,40
2,Roofing,ROF,roofing,60,40,60
3,Finishing,FIN,finishing,80,60,80
```

> The nominal percentages are **assumptions to be validated**. Before the defense, have them
> reviewed by a civil engineer / project manager and cite that review in the thesis. Record
> the reviewed values here and regenerate the CSV. Tracked in [[Open-Questions]].

## Ordinality

The classes are **ordered** (a monotone construction sequence). Two consequences:

1. Prefer an **ordinal-aware** view of errors: report not just accuracy but *mean absolute
   ordinal error* (how many stages off). Confusing `Structural` with `Roofing` is a much
   smaller failure than confusing `Foundation` with `Finishing`. Include this in
   [[Evaluation-Plan]]. The ordinal-error argument is weaker with only 4 classes than it was
   with 10 — worth stating honestly rather than glossing over.
2. The progress aggregator exploits ordinality via the monotonic ratchet in
   [[Progress-Calculation]].

## Visual disambiguation notes (background for the YOLO class list, not current classifier boundaries)

> These pairs described the retired 10-class classifier's decision boundaries. The classifier
> no longer draws these lines — but they're exactly why ADR-036 picked the YOLO element list it
> did (rebar/column for early structural, wall/CHB for late structural, window/door/tile for
> finishing progression), so kept here as the annotation-relevant background.

| Confusable pair | Discriminator |
|---|---|
| Footings vs Foundation | footings = isolated pads/trench steel; foundation = continuous poured wall/slab base |
| Columns vs Slab | vertical members only vs a horizontal deck cast between them |
| Slab vs Walls | deck present but no enclosure vs CHB/panel enclosure rising |
| Walls vs Roof | open top vs trusses/purlins/roofing sheets present |
| Roof vs Finishing | structure complete, no plaster/paint/openings vs plaster, paint, windows, doors |
| Finishing vs Completed | scaffolding/debris/partial finish vs clean site, no scaffolding, fully finished façade |

## Related
[[Progress-Calculation]] · [[Annotation-Guide]] · [[Dataset-Spec]] · [[Naming-Conventions]]
