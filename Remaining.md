# GeoVision — 7-Day Sprint Plan

**Why this file exists:** the Claude subscription renews in 7 days. This plan is built to get
the most real thesis progress out of those 7 days of AI-assisted coding sessions — not to hit
the actual thesis deadline, which is much further out (defense is planned for October per the
workplan, final submission February 2027). Think of this as "what to burn the subscription on,"
not "what's due this week."

Written 2026-08-27, revised the same day after the team answered every open question in the
vault (`Open-Questions.md`) and Day 1's actual work ran ahead of the original plan — the biggest
blocker didn't just get *decided*, it got *implemented and tested* the same day. That's good
news, but the team's answers also added new work this plan didn't originally account for
(no hardware in hand, notifications as a real feature, a dataset-provenance decision). Both are
reflected below.

---

## Status as of end of Day 1 (2026-08-27)

**Done today:**
- **The single biggest blocker — the fused progress formula (Open-Questions Q18) — is resolved
  *and shipped*, not just decided.** Recorded as ADR-038 in the vault. In plain terms: the AI
  classifier says which broad stage a photo shows and how confident it is; the object-detector
  looks for the specific things expected in that stage (beams, walls, windows, roofing sheets,
  etc.); the two are averaged into "how far through this stage" the photo is. The team
  specifically asked for the contract deadline to be "the main dictator" of progress — that
  deliberately did **not** get folded into this number, because the system already has a
  separate, existing mechanism for schedule/deadline tracking (the "on schedule / delayed"
  badge). Mixing the two would make the AI's percentage stop meaning "what the camera can see
  was built," which is the actual thing the thesis is about.
- All the code this touches is updated and fully tested: 276 AI-side tests and 435 backend
  tests pass, and a real bug was found and fixed along the way (a missing piece of the
  percentage-band lookup that only broke once the "auto-detect finished" class was correctly
  removed).
- Every other open question in the vault got recorded with the team's actual answer — Cloudflare
  Tunnel for hosting, Kaggle for training, GitHub Releases + Kaggle for storing trained models,
  keeping prediction history instead of deleting it, building notifications and the homepage
  feed fix properly, and more. Full detail in `Open-Questions.md`.

**Two answers changed this plan materially:**
- **There is currently no ESP32-CAM camera in hand at all** (previously it was "ordered,
  shipping"). Near-term data collection needs to happen with a phone or a webcam instead,
  through the same upload system.
- **Notifications and the homepage feed fix are now real, first-class features to build**, not
  small cosmetic gaps to defer to the end — the team wants notifications specifically so
  collaborators get alerted to delays and inconsistencies.

**Also finished today (Docker came up, so these got done too):**
- The image quality-check pass ran over all 661 usable raw photos: **619 pass (93.6%)**, all 42
  rejections were blur, none too dark. Script: `scripts/audit_dataset_quality.py`.
- The uncategorized photos got sorted — but not all of them, on purpose. The 11 loose photos in
  `Aldea Grove/1` and the 17 loose photos in `Paramjeet` got visually classified and moved into
  their correct stage folders (calibrated against already-sorted neighbor photos from the same
  shoot). `Aldea Grove`'s other 7 root-level loose photos and its 4-photo `Cleanup Site` folder
  were deliberately left alone.
- **Found and fixed a real problem: 50 of `Paramjeet`'s photos were `.HEIC`** (the iPhone's
  default format) and were invisible to every tool in the pipeline — the image-decoding library
  used everywhere simply cannot read HEIC. They looked like they were part of the dataset by a
  plain file count, but no script or training run would ever actually have used them. All 50 now
  have a `.jpg` copy sitting next to the untouched original, so they finally count.
- **Final, accurate per-class count: Foundation 37, Structural 381, Roofing 110, Finishing
  122.** Foundation is still the one class short of the team's own 80-130 estimate (Q5).
- Docker Desktop got started and the test-coverage re-check (Q17) ran against live services:
  **700 tests passed, 81.03% coverage** — identical to a prior measurement, confirming the
  system's coverage bar is already set correctly.

**Not done today:** the phone/webcam capture tool (Q2) and the Kaggle training notebooks (Q7)
roll into Day 2 as originally planned — there wasn't room for everything in one session.

---

## What I found when I first checked the project's real state

- **The dataset is bigger and more sorted than the vault log suggested**, but one category is
  thin. Final, verified count after today's sorting and a HEIC-to-JPG conversion (see "Status as
  of end of Day 1" above for what that fixed):

  | Stage | Photos on hand | Team's own realistic estimate (Q5) | Vault's documented minimum |
  |---|---|---|---|
  | Foundation (site clearing, digging, footings) | **37** | 80-130 | 150 |
  | Structural (columns, walls, framing) | 381 | 80-130 | 150 |
  | Roofing | 110 | 80-130 | 150 |
  | Finishing | 122 | 80-130 | 150 |

  **Foundation photos are the one thing worth actively going out and getting more of** — every
  other class is at or past what the team itself expects to realistically gather.

- **The AI training code already exists and has never been run.** `ai/src/ai/training/` and
  the `gv-train-classifier` / `gv-train-detector` commands are built and waiting on the dataset
  above (and, as of today, on Kaggle notebooks the team knows how to run — Q7).

- **No bounding-box annotations exist yet** for the object-detection model (YOLOv8) — the
  `dataset/labels/` folder is empty. That model needs boxes drawn around things like beams,
  windows, and roofing sheets in each photo, and nobody has started. This is the slowest,
  least automatable task on this list — plan for it honestly rather than assuming it happens in
  a spare hour.

- **The hardware and the real construction site will not be ready inside this 7-day window.**
  There is no camera in hand right now (see above), and the site was estimated ready in 3-4
  weeks *as of 2026-08-18* — realistically early-to-mid September. So this week's plan writes the
  camera's firmware code and tests it against the software simulator that already exists
  (`simulate_device.py`), and separately builds a phone/webcam uploader for near-term real data,
  but the actual on-camera test log stays empty until real hardware is back in hand.

---

## Ground rules for the week

- **Foundation photos are the dataset's weak point.** If anyone on the team has time to grab
  more site-clearing/excavation/footings photos or find a time-lapse video covering that stage,
  that's worth more than any hour of coding this week.
- Some tasks below need you (a human decision, a phone camera in your hands, going out to a
  site) — those are marked **[you]**. Everything else is a Claude Code session.

---

## Day 1 — complete

Everything originally planned for today is done (see "Status as of end of Day 1" above), plus
Q17's coverage re-check, since Docker ended up getting started today too.

**[you]** The project already lives on GitHub, so no separate backup step is needed — but
everything from today (the code changes, the vault updates, the dataset sorting) is still only
sitting **uncommitted** on this machine. Commit and push before ending the session, or a crash
tonight loses a full day of work despite the GitHub safety net.

---

## Day 2 — done, and it went further than planned

**A correction first:** the original plan assumed `gv-train-classifier`/`gv-train-detector`
already existed and just needed a Kaggle wrapper. They didn't — `ai/src/ai/training/` was an
empty placeholder. Today built the real thing instead of just a notebook around nothing, which
is why this list looks bigger than "produce two notebooks."

**Done:**
- **The classifier can now actually train, and did.** Built the dataset split script, the data
  loading/augmentation code, the ResNet18 model wrapper, and the full training loop (early
  stopping, checkpointing, CPU-safe). Ran it for real on the sorted dataset: 24 epochs,
  **best validation macro-F1 = 0.4603**. That's well under the 85% target — expected and honest,
  since Foundation has only 16 training images after the split. This is a real number to put in
  the thesis's results chapter, with a clear, defensible reason for why it's not higher yet
  (more Foundation photos, most likely, not a code problem).
- **The dataset split** — done by **building**, not by site name: `Aldea Grove` turned out to
  contain three separate houses under one folder, which would have let the same building appear
  in both training and test if split naively. Six real groups exist today; the closest possible
  split to 70/15/15 that still keeps every class present everywhere is lumpy (see
  `Dataset-Spec.md`) — a real, documented limitation rather than a hidden one.
- **The object-detector's training code is written too** (same reasoning as above — it also
  didn't exist), but it genuinely cannot run yet: no bounding-box annotation exists. This is now
  the single clearest non-hardware blocker left with no code-side workaround.
- **Two Kaggle notebooks** (Q7) — one fully runnable today (classifier), one ready but blocked on
  annotation (detector). Both are careful not to let Kaggle's GPU-enabled PyTorch get silently
  replaced by this project's CPU-only pinned version.
- **The phone/webcam uploader** (Q2) is built — reuses the existing camera simulator's security
  code directly rather than reimplementing it, supports a webcam shot, a single file, or
  watching a folder for phone-synced photos, and reads GPS from the photo itself when the phone
  provides it.
- **Prediction history** (Q11) — the database change is done: reprocessing an image now keeps
  the old prediction (marked superseded) instead of deleting it, so "what did the model say
  before the retrain?" stays answerable. A related, previously-unnoticed bug got fixed in the
  same change: the database's safety check on which stage values are valid still allowed the
  old, retired 10-class range instead of today's 4 — closed at the same time.

**Not done — bounding-box annotation** got explicitly deprioritized today in favor of building
the training code that annotation feeds into. It's still the slowest, least automatable item on
the whole list; getting CVAT running and annotating a first batch is now Day 4's job as
originally planned, once there's more headroom.

**[you]** If anyone has a spare hour, this is the day to go find more Foundation-stage photos
or video — or use the new phone/webcam uploader to shoot some directly.

---

## Day 3 — Moved up: the classifier already trained on Day 2

Day 2 got ahead of this plan (see above) — a real ResNet18 checkpoint exists already. Day 3
becomes:

**[Claude]** Publish the trained checkpoint (Q10 — GitHub Releases and/or a Kaggle Dataset), and
run the evaluation tool that already exists (`gv-evaluate`) against it to produce the confusion
matrix and per-class figures the thesis needs.

**[you]** If more Foundation-stage photos turn up (from Day 2's uploader, or anywhere else),
re-run `scripts/split_dataset.py` and training again — the code already handles this, it's just
a matter of having more to feed it. This is the single highest-leverage way to improve on the
0.46 macro-F1 baseline.

**[Claude]** Start the bounding-box annotation work for the object-detector model (moved from
Day 2, which ran long). Get the annotation tool (CVAT) running and annotate the Structural-stage
photos first (the most images, best return on time).

---

## Day 4 — Continue annotation, train the object detector (Module 08)

**[Claude]** Continue and finish as much bounding-box annotation as realistically possible
(Roofing, Finishing). Honest expectation: fully annotating everything in one day is unlikely —
partial coverage is fine to start training with, and more can be added later without redoing
anything.

**[Claude]** Train YOLOv8 on whatever is annotated by this point, using the Kaggle notebook
already built (`ai/notebooks/kaggle_train_detector.ipynb`).

**[you]** Keep the Kaggle session alive/monitored while it trains — a free Kaggle session can
time out unattended.

---

## Day 5 — Plug the real AI models into the running system (Module 09 rework)

**[Claude]** Swap the placeholder "stub" classifier and detector that the system has been
running on for the real trained models from Days 3-4 — the code was already built to make this
a clean swap, not a rewrite; the fused-percentage formula from Day 1 is already wired in and
does not need to change.

**[Claude]** Re-run the full automated test suite plus a live end-to-end check (upload a photo →
get a real prediction → see a real percentage) to confirm nothing broke.

**[Claude]** Build the homepage feed fix and the notifications feature (Q13, Q14) — both are
now real features the team wants, not small deferred gaps: the feed should show the project
owner and a thumbnail on each card, and notifications should actually alert collaborators to
delays, inconsistencies, and remarks instead of being recorded and never shown.

---

## Day 6 — Camera firmware code + one-command deployment

**[Claude]** Write the ESP32-CAM firmware (Module 13): capture on a schedule, read GPS location
and the real-time clock, save to the memory card, upload to the server with the security
signature the server already expects. Test it against the existing device simulator
(`simulate_device.py`) — this fully exercises the upload/pairing/security logic without needing
the physical camera in hand.

**[Claude]** Build the one-command deployment setup (Module 16), including the Cloudflare
Tunnel decided on Day 1 (Q4): a single command that starts the whole system (database, storage,
AI worker, website) the way it'll run for the actual defense demo, reachable over the internet,
plus a written runbook.

**[you]** Once the physical camera arrives (expect early-to-mid September, not this week), the
`Hardware-Test-Log.md` template in the vault is ready and waiting for real measurements — boot
time, battery life, upload reliability. Nothing to do about it this week except know it's ready.

---

## Day 7 — Polish, figures, and catching up the paperwork

**[Claude]** Re-run the evaluation tool one more time now that everything is wired up, and
generate the final set of thesis figures (confusion matrix, per-class accuracy, detection
accuracy, the progress-over-time chart).

**[you + Claude]** Rehearse the full demo end-to-end once, including a fallback plan in case
the internet or a live service misbehaves during the actual defense.

**[Claude]** Update the vault to reflect everything shipped this week: the module status board,
a new entry in the running project log, and closing out any remaining questions. This is what
makes next week's session — on whatever's left — start from an accurate picture instead of
re-discovering all of this from scratch.

**[you]** Separately from code: this is a good week to keep writing the thesis manuscript
chapters that don't depend on final numbers — methodology, architecture, related work — using
the design spec and workplan already in `Paper/`. The results chapter is the only part that
needs to wait for Day 7's figures.

---

## Things that stay on your plate no matter what (not fixable by coding)

These don't take Claude Code time, but they're on the project's critical path and nothing above
replaces them:

1. **Get the construction-stage percentages reviewed by a civil engineer or project manager**
   (`Open-Questions.md` Q1) — every progress number the system reports rests on that table being
   defensible in front of a panel. Worth scheduling this week even if the meeting itself happens
   later.
2. **Get a real ESP32-CAM back in hand** — the phone/webcam uploader is a good stand-in for
   dataset collection, but the actual thesis hardware still needs to exist, be tested, and be
   deployed on-site eventually.
3. **Keep an eye on the site's readiness date** so the camera goes up the day it's usable —
   every week of real accumulated site photos is worth more to the thesis than another week of
   coding.

---

## Where this leaves the project after 7 days, if it goes to plan

- The AI models are trained on real data instead of placeholders, with real accuracy numbers.
- The full pipeline — photo in, percentage out — runs end-to-end on the real models, using the
  fused formula finalized on Day 1.
- Notifications and the homepage feed actually work the way the team wants them to.
- The camera's code is written and tested (against the simulator), ready for the moment the
  hardware and site are both ready.
- The system can be started with one command, reachable over the internet, the way it'll run
  for the defense.
- The thesis has real figures to put in the results chapter instead of placeholders.
- What's left after that is genuinely calendar-bound, not coding-bound: getting a camera back
  in hand, waiting for the site, letting real photos accumulate over weeks, and getting the
  expert review of the stage percentages.
