---
title: PENDING — master priority board
type: index
status: living
updated: 2026-08-29
---

# PENDING — what needs doing, in priority order

> **How to use this file.** It answers one question: *"what should I do next?"*
> [[Build-Order]] holds module sequence and status; [[Open-Questions]] holds unresolved
> decisions; [[Progress-Log]] holds history. **This file ranks everything by urgency.**
> Review it at the start of every working session and tick things off.

**Priority key**
`P0` blocks work right now · `P1` **calendar-bound — start now regardless of code** ·
`P2` needed before the defense · `P3` deferred / optional

> ⚠ **The single most important thing on this page is the P1 section.** Coding time can be
> compressed; calendar time cannot. Hardware shipping, dataset collection, and weeks of real
> site captures are the things that will actually decide whether this thesis lands.

---

## 🚩 Fill this in first

| Item | Value | Why it matters |
|---|---|---|
| **Defense / submission date** | ❓ *unknown* | Every deadline below is relative to it. Fill this in and the rest of the plan becomes concrete. |
| Adviser check-in cadence | ❓ | Determines how often you need a demoable state |
| Panel documentation format | ❓ (Q8) | Cheap to ask now, expensive to reformat later |

---

## P0 — Blocking right now

| # | Task | Blocks | Notes |
|---|---|---|---|
| ~~P0-1~~ | ~~Get a PostgreSQL running~~ | — | ✅ **done 2026-08-13.** PostgreSQL 16 installed natively at `F:\PostgreSQL\16`, port 5433, with `geovision` + `geovision_test` databases and all four extensions. Unblocked Modules 02–03. |
| ~~P0-2~~ | ~~Update Windows~~ | — | ✅ **not needed.** Build 19045 already meets Docker's minimum. |
| ~~P0-3~~ | ~~Install Docker Desktop~~ | — | ✅ **done 2026-08-14.** Docker 29.6.2 + Compose v5.3.1, WSL data root on `F:\Docker\wsl`. Redis and MinIO containerised; PostgreSQL stays native behind a compose `db` profile. `/health/ready` returns 200 ready. |

**Nothing is blocking code right now.** Modules 01–06, **09–12**, **14**, and **16** are done,
and the whole stack has been exercised end to end against live services — including, as of
2026-08-29, the fully containerised deployment itself (real images, real HTTPS, real trained
checkpoint serving live through it).

**In progress: [[Module-15-Testing-and-Evaluation]] (started 2026-08-18).** Everything buildable
without hardware or a labelled dataset has shipped — `ai/evaluation/` (metrics, benchmark,
detector eval, progress eval, the `gv-evaluate` CLI), coverage thresholds enforced in CI, the
generalised client/server contract test, `documentation/openapi.json` + `erd.mmd` export, a
Playwright E2E scaffold (now run for real, 12/12 passing, Q16 closed), two k6 load scripts, and
[[Hardware-Test-Log]]. **13 waits on hardware; 07/08 on the dataset (specifically
Foundation-class volume, Q5) and YOLO annotation** — Module 09 was built ahead of both against a
deterministic `StubClassifier`, so neither blocks the *code*: 07 has already swapped in a real
ResNet18 checkpoint (2026-08-29, both training and live serving), 08 is a weights swap behind the
same `StageClassifier` protocol once annotation exists, and `gv-evaluate` already reports exactly
which of its artifacts are still waiting, by name, every time it runs.

> Small things worth clearing before the defense: **Q14** (notification endpoints - rows are
> being written and never shown) and **Q13** (feed owner/thumbnail, search locations). ~~Q17~~
> closed 2026-08-18 — a full run against live Postgres/Redis/MinIO measured 81.00%; the
> threshold is set to 78.

> ⚠ **2026-08-18 domain rescope, completed 2026-08-27 — read before touching Module 07, 08, or
> 09 code.** The classifier narrows from 10 fine classes to 4 macro-aligned ones, YOLO's object
> list is redefined, and detection is a direct fusion input rather than an advisory
> corroboration signal. See [[ADR-Index#ADR-036|ADR-036]], [[ADR-Index#ADR-037|ADR-037]], and
> [[ADR-Index#ADR-038|ADR-038]] (the fused progress formula — now implemented, not just
> decided). `dataset/raw/`'s existing Foundation/Structural/Roofing/Finishing folders already
> match the new class list — no relabeling needed at the macro level, though ~39 images are
> still sitting unsorted and Foundation's volume (~30 images) is well short of target (Q5).

> ⚠ **Fix Q12 before Module 12.** `get_session` commits *after* the response is sent
> (measured 6.9 ms), so a real browser that creates a project and immediately navigates to it
> gets a 404. The test suite cannot see it. Module 12's dashboard does exactly that.
> See [[Open-Questions]] Q12.

> Note the dependency correction: [[Build-Order]] says 12 depends only on 11, while
> [[Module-12-Owner-Dashboard]] lists 11, 05, 10 **and 14** — and 14 lists 12. That circle
> needs resolving (build 14 first, or have the pairing modal poll with a WebSocket upgrade).

> The preprocessing pipeline was deliberately settled *before* annotation begins. Annotate
> first and you annotate twice, because the quality gate decides which images are worth
> labelling at all. Run the dataset audit (`ai.preprocessing.quality.assess` over your
> collected images) as you gather them — how many would have been rejected is both a useful
> filter and an interesting thesis result.

> **Before deploying anything beyond your laptop**, set `GV_DEVICE_SECRET_KEY` and keep a
> backup of it. It encrypts every paired camera's secret (ADR-020); lose it and every camera
> must be re-provisioned by hand, on site.

---

## P1 — Calendar-bound: start now, in parallel with coding

These have lead times that no amount of coding speed can recover. **This is the real critical
path of the thesis.**

| # | Task | Lead time | Why now |
|---|---|---|---|
| P1-1 | ~~Order hardware~~ **ESP32-CAM ordered.** | shipping in transit | ◑ **in progress, 2026-08-18.** Confirm a spare board and the rest of the BOM (GPS, DS3231, microSD, programmer, enclosure) shipped too — [[ESP32-CAM-Node]] — and start [[Hardware-Test-Log]] the moment it arrives. |
| P1-2 | ~~Secure a real construction site + written permission~~ | site ready in ~3–4 weeks | ✅ **done, 2026-08-18.** Site identified and permit in hand (Q3 closed). Use the remaining weeks to finish [[Module-16-Deployment]] and rehearse pairing (P2-9) so the camera goes up the day the site is ready. |
| P1-3 | **Start dataset collection** — target ≥ 1 500 images, ≥ 150/class | weeks | Highest-yield source: construction time-lapse videos on YouTube (one video can cover all 10 stages of one building). Record source URLs + licences as you go. [[Dataset-Spec]] |
| P1-4 | **Set up CVAT and start annotating** | ongoing | Annotation is slow and cannot be rushed at the end. [[Annotation-Guide]] |
| P1-5 | **Get the stage percentages reviewed** by a civil engineer / project manager (Q1) | days–weeks to schedule | Every progress number in the system rests on this table. A cited expert review turns an assumption into a defensible methodology choice. [[Construction-Stages]] |
| P1-6 | Deploy the camera on site as early as possible | weeks of accumulation | A rising progress curve over real calendar time is the single most convincing demo artifact. |
| P1-7 | ~~Confirm GPU access for training (Q7)~~ | — | ✅ **answered 2026-08-27 — Kaggle.** Team does not yet know how to run training there; ready-to-run notebooks for `gv-train-classifier`/`gv-train-detector` are next. |
| ~~P1-8~~ | ~~No ESP32-CAM in hand right now (Q2). Build a phone/webcam capture uploader.~~ | — | ✅ **done 2026-08-28** — `backend/scripts/capture_and_upload.py`. Unblocks real (non-synthetic) dataset collection without waiting on hardware or the site. |
| P1-9 | **Collect more Foundation-stage photos/video specifically (Q5).** | ongoing | Final verified count 2026-08-27: Foundation 37, Structural 381, Roofing 110, Finishing 122 — every other class is at or past the team's own 80-130/class estimate; Foundation is the one real shortfall. |

> **If you do nothing else this week, do P1-1, P1-2, and P1-3.** They are all waiting on other
> people or on shipping, and every day of delay is unrecoverable.

---

## P2 — Needed before the defense

| # | Task | Owner module |
|---|---|---|
| ~~P2-1~~ | ~~Modules 10 → 16 built and tested~~ | ✅ **done 2026-08-29** — only 13 (hardware) and the dataset-dependent parts of 07/08/15 remain, see [[Build-Order]] |
| P2-2 | Decide where trained checkpoints live (Q10) — Release assets / Drive + hash / git-lfs | [[Module-07-Classifier-Training]] |
| P2-3 | Verify the ESP32 pinout for *your* board revision (Q2) and record it | [[ESP32-CAM-Node]] |
| P2-4 | Decide the public server host + HTTPS endpoint for the field device (Q4) — Cloudflare Tunnel is the cheap answer | [[Module-16-Deployment]] |
| P2-5 | Measure real deep-sleep current and battery life (measured, not estimated) | [[Capture-Schedule-and-Power]] |
| P2-6 | Generate all evaluation figures by script | [[Evaluation-Plan]] |
| P2-7 | Double-annotate 10 % and compute Cohen's κ | [[Annotation-Guide]] |
| P2-8 | Write the manuscript alongside the build, not after | [[Thesis-Mapping]] |
| P2-9 | Rehearse the demo end-to-end, with an offline fallback | [[Module-16-Deployment]] |
| P2-10 | Back up the vault + repo somewhere off this machine | — |

---

## P3 — Deferred / optional

Everything in section 3 of [[Open-Questions]] (blueprint-aware AI, weather API, OTA, mobile
app, i18n, multi-building…). **Do not start any of these until P0–P2 are done.** They are
future-work material for the conclusion chapter, not v1 scope.

---

## Module status (summary)

Authoritative board: [[Build-Order]].

| | Module | Status | Blocked by |
|---|---|---|---|
| 01 | Foundation & Setup | ✅ done | — |
| 02 | Database Schema | ✅ done | — |
| 03 | Auth & Users | ✅ done | — |
| 04 | Projects & Folders | ✅ done | — |
| 05 | Device Pairing & Ingestion | ✅ done | — |
| 06 | AI Preprocessing | ✅ done | — |
| 07 | Classifier Training | ◑ in progress | Code shipped and run for real 2026-08-28: split script, dataset/transforms, ResNet18 model + trainer + CLI, Kaggle notebook. First real checkpoint trained — macro-F1 0.46, honestly below target due to dataset size/imbalance, not a bug. More Foundation-class images (P1-9) is the highest-leverage next step to improve it. |
| 08 | YOLO Detection | ⏸ blocked | Code shipped 2026-08-28 (wrapper, training CLI, Kaggle notebook, placeholder `data.yaml`) — the only real blocker left is bounding-box annotation, which has not started. |
| 09 | Inference & Progress | ✅ done | — *the [[ADR-Index#ADR-038\|Q18]] formula and the real-checkpoint serving path both landed 2026-08-27/29* |
| 10 | Reports & Remarks | ✅ done | — |
| 11 | Public Dashboard | ✅ done | — |
| 12 | Owner Dashboard | ✅ done | - |
| 13 | Firmware | pending | **P1-1** (hardware — ordered, in transit) |
| 14 | Realtime | ✅ done | — |
| 15 | Testing & Evaluation | ◑ in progress | classifier/detector figures need P1-3/P1-4; hardware log needs P1-1 |
| 16 | Deployment | ✅ done | — *verified end to end 2026-08-29: real stack, real checkpoint, real HTTPS* |

---

## Decision queue

Unresolved questions, from [[Open-Questions]]. Each one blocks or reshapes work:

| | Question | Priority |
|---|---|---|
| Q1 | Are the stage percentages realistic? | **P1** |
| Q5 | How many labelled images can you realistically get? | **P1** |
| Q7 | GPU for training? | P1 |
| Q2 | Exact ESP32 pinout for your board | P2 |
| Q4 | Where does the server run? | P2 |
| Q10 | Where do checkpoints live? | P2 |
| Q13 | Feed owner/thumbnail + search locations | P2 — before the demo |
| ~~Q18~~ | ~~Fused progress formula (classifier + YOLO + physical change) undecided~~ | ✅ resolved 2026-08-27, [[ADR-Index#ADR-038\|ADR-038]] |
| Q11 | Superseding predictions needs a migration | P3 |
| Q8 | Panel documentation format | P2 |
| Q6 | Timezone / window policy | assumed daily, `Asia/Manila` |

---

## Top risks

Full register in [[Open-Questions]] §4. The three most likely to hurt:

1. **Not enough training data** → start P1-3 today; time-lapse frames are the highest-yield source.
2. **Hardware arrives late or dead** → ordered (P1-1); confirm a spare shipped, and keep building
   against `scripts/simulate_device.py` until it arrives.
3. ~~**Site access falls through**~~ → resolved: site identified, permit in hand (Q3). Residual
   risk is now purely the ~3–4 week wait — use it for Module 16 and pairing rehearsal (P2-9).

---

## Suggested weekly rhythm

- **Every session:** read this file → check [[Build-Order]] → build one module → update
  [[Progress-Log]].
- **Weekly:** re-rank this file; annotate a batch of images; check the deployed camera.
- **Never:** start a P3 item while a P1 item is untouched.

## Related
[[00-START-HERE]] · [[Build-Order]] · [[Open-Questions]] · [[Progress-Log]] · [[Local-Environment-Setup]]
