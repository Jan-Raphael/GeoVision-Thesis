---
title: Construction Stages
type: domain
status: canonical
updated: 2026-08-12
---

# Construction Stages — Two-Layer Model ⚖

The original architecture specified **10 classes**. The dashboard spec specified **4 stages
at 20% each + a 20% approval stage**. Both are kept, in two layers (ADR-001):

- **Layer 1 — Fine classes (ML layer).** What the ResNet18 actually predicts. 10 classes.
  Fine-grained because visually distinct sub-phases are what a CNN can separate, and because
  a 10-class confusion matrix is a far stronger thesis result than a 4-class one.
- **Layer 2 — Macro stages (business/UX layer).** What the owner and the public see.
  A deterministic, hand-authored mapping table. No learning involved — it is a
  domain rule, reviewable by a civil engineer, and defensible in the oral defense.

---

## Layer 1 — Fine classes (model output)

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
| 9 | Completed | `CMP` | Approval (pending) | 80 † |

† **`Completed` does not produce 100%.** The machine ceiling is **80%**. Detecting `CMP`
sets the project to `awaiting_inspection` and notifies the owner. Only the owner's manual
sign-off adds the final 20%. See [[Progress-Calculation]].

`class_index` order above is **frozen** — it is the index order used by the trained
checkpoint. Adding a class requires retraining and a new model version; never reorder.

Canonical definition file: `ai/configs/classes.yaml` (generated into
`dataset/metadata/progress_reference.csv` by `scripts/generate_progress_reference.py`).

## Layer 2 — Macro stages (UI)

| Stage | Range | Weight | Completed when |
|---|---|---|---|
| Foundation | 0–20 % | 20 | fine class ≥ `FDN` confirmed |
| Framing | 20–40 % | 20 | fine class ≥ `WAL` confirmed |
| Roofing | 40–60 % | 20 | fine class ≥ `ROF` confirmed |
| Finishing | 60–80 % | 20 | fine class ≥ `FIN` confirmed |
| **Approval / Checking** | 80–100 % | 20 | **owner manually inspects and approves** |

The Project Folder page shows five bars. The first four are AI-driven; the fifth is a
human action with an explicit "Mark as Inspected & Complete" button, an inspection note,
and an optional inspection photo upload.

## `progress_reference.csv` (tracked in `dataset/metadata/`)

```csv
class_index,class_name,token,macro_stage,nominal_progress_pct,stage_floor_pct,stage_ceiling_pct
0,Site Clearing,CLR,foundation,4,0,20
1,Excavation,EXC,foundation,9,0,20
2,Footings,FTG,foundation,14,0,20
3,Foundation,FDN,foundation,20,0,20
4,Columns,COL,framing,28,20,40
5,Slab,SLB,framing,34,20,40
6,Walls,WAL,framing,40,20,40
7,Roof,ROF,roofing,60,40,60
8,Finishing,FIN,finishing,80,60,80
9,Completed,CMP,approval,80,80,100
```

> The nominal percentages are **assumptions to be validated**. Before the defense, have them
> reviewed by a civil engineer / project manager and cite that review in the thesis. Record
> the reviewed values here and regenerate the CSV. Tracked in [[Open-Questions]].

## Ordinality

The classes are **ordered** (a monotone construction sequence). Two consequences:

1. Prefer an **ordinal-aware** view of errors: report not just accuracy but *mean absolute
   ordinal error* (how many stages off). Confusing `Columns` with `Slab` is a much smaller
   failure than confusing `Excavation` with `Roof`. Include this in [[Evaluation-Plan]].
2. The progress aggregator exploits ordinality via the monotonic ratchet in
   [[Progress-Calculation]].

## Visual disambiguation notes (for the annotation guide)

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
