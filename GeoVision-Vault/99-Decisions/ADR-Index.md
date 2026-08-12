---
title: ADR Index
type: decisions
status: canonical
updated: 2026-08-12
---

# Architecture Decision Records

Format: **Context → Decision → Consequences → Alternatives rejected.** Every ADR here is
defensible material — examiners reward reasoned trade-offs far more than unexplained choices.

Append new ADRs; never delete one. If a decision is reversed, add a new ADR that supersedes
it and mark the old one `Superseded by ADR-NNN`.

---

## ADR-001 — Two-layer stage model (10 fine classes → 5 macro stages)
**Status:** Accepted · 2026-08-12
**Context.** The original architecture specified 10 construction classes; the dashboard spec
specified 4 stages worth 20 % each plus a 20 % approval stage. Picking one discards
something valuable: 10 classes make a much stronger ML result, while 5 macro stages are what
a homeowner actually understands.
**Decision.** Keep both as layers. The CNN predicts 10 fine classes; a deterministic,
hand-authored table folds them into 4 macro stages + approval for the UI.
**Consequences.** Richer confusion matrix and ordinal analysis; simple, explainable UI; the
mapping table becomes a reviewable domain artifact rather than a hidden constant. Cost: two
vocabularies to keep straight — mitigated by defining both in one file
([[Construction-Stages]]).
**Rejected.** (a) 4-class model — weaker thesis result, coarse supervision. (b) 10 stages in
the UI — contradicts the spec and overwhelms non-expert users.

## ADR-002 — Two image namespaces (dataset vs runtime)
**Status:** Accepted · 2026-08-12
**Context.** `GV_[PROJECT]_[STAGE]_[NUM].jpg` embeds the stage; at capture time the stage is
unknown — it is what the model predicts.
**Decision.** `GV_*` is the dataset/training namespace (stage = ground-truth label);
`<CODE>_<TIMESTAMP>_<SEQ>.jpg` is the runtime namespace. Promotion from runtime to dataset
renames and records `original_name` in `metadata.csv`.
**Consequences.** No possibility of a predicted label leaking into a filename and being
mistaken for truth. Cost: a documented rename step ([[Naming-Conventions]]).
**Rejected.** A single namespace with a `UNK` stage token — invites exactly the confusion
above and makes the dataset harder to audit.

## ADR-003 — HTTP for image upload; WebSocket for dashboard push
**Status:** Accepted · 2026-08-12
**Context.** The professor suggested WebSocket "so the owner doesn't have to refresh to
upload." Two problems are conflated there: unattended device upload, and live dashboard
updates.
**Decision.** Device → server images travel over HTTPS multipart POST. Server → browser
updates travel over WebSocket. An optional device control channel is deferred.
**Consequences.** Per-image ACKs, trivial retry, proxy/captive-portal friendliness, and no
socket held open through deep sleep — while the owner still never refreshes. Cost: two
transports to implement.
**Rejected.** (a) WebSocket upload from the ESP32 — heavy on ~200 KB heap, no clean per-image
ACK, awkward with deep sleep, and no benefit since the device initiates every transfer.
(b) MQTT — an extra broker to run and defend for no gain at this scale.
Full reasoning: [[Realtime-Events]].

## ADR-004 — Progress aggregated per window, not per image
**Status:** Accepted · 2026-08-12
**Context.** Single-frame classification is noisy (occlusion, weather, light). A headline
number driven by the latest frame jitters and can move backwards.
**Decision.** Median per device per window → weighted multi-camera mean → EMA → stage-advance
guard → monotonic ratchet. See [[Progress-Calculation]].
**Consequences.** Stable, trustworthy numbers; the smoothing is itself an evaluable
contribution; genuine regressions still surface after sustained evidence. Cost: more state
(`project_progress_snapshots`) and a lag of ~2 windows on stage transitions — measured and
reported.
**Rejected.** Last-image-wins (jittery, non-monotonic); simple mean (one bad frame dominates);
hard monotonic-only (cannot represent real rework or typhoon damage).

## ADR-005 — Binaries in object storage, never in PostgreSQL
**Status:** Accepted · 2026-08-12
**Decision.** MinIO (S3-compatible) holds originals, preprocessed frames, thumbnails, assets,
and reports; the database holds keys.
**Consequences.** Backups stay small and fast, images stream directly via signed URLs, storage
scales independently. Cost: a second stateful service, and orphaned-blob cleanup.
**Rejected.** `BYTEA` columns (bloated DB, slow dumps, memory pressure); local filesystem
(breaks multi-container and any future multi-node deployment).

## ADR-006 — HMAC device authentication instead of mTLS or JWT
**Status:** Accepted · 2026-08-12
**Decision.** Per-device shared secret + HMAC-SHA256 over a canonical string, with a nonce
cache and a ±5 min clock-skew window ([[Device-Pairing-Protocol]]).
**Consequences.** Small code and memory footprint on the ESP32, no certificate infrastructure,
per-device revocation. Depends on the DS3231 for a trustworthy clock. Cost: a shared secret
must be stored on-device (NVS).
**Rejected.** mTLS (correct but needs a CA, per-device certs, rotation, and more flash/heap —
documented as the production hardening path); JWT (refresh flows and asymmetric verification
are awkward on a device that sleeps for hours).

## ADR-007 — The AI cannot mark a project complete
**Status:** Accepted · 2026-08-12
**Context.** Progress readings could plausibly inform payment, scheduling, or handover
decisions.
**Decision.** The machine ceiling is 80 %. Reaching it sets `awaiting_inspection` and
notifies the owner; only an authorized human, on record with inspection notes, adds the final
20 %.
**Consequences.** Accountability stays with a person; the system cannot be the sole basis for
declaring a building finished; it directly satisfies the dashboard spec's checking stage. Cost:
the number never reaches 100 automatically — which is the point, and should be stated as a
deliberate safety property rather than a limitation.
**Rejected.** Auto-complete at high confidence — unsafe and indefensible for a physical
structure.

## ADR-008 — PostgreSQL + Celery/Redis over a lighter stack
**Status:** Accepted · 2026-08-12
**Decision.** PostgreSQL for data, Redis+Celery for async inference, reports, and pub/sub.
**Consequences.** Real concurrency, durable queues, and horizontal room; the API process never
blocks on torch. Cost: more services in compose than a single-file SQLite app.
**Rejected.** SQLite + FastAPI `BackgroundTasks` — simpler, but loses work on restart, cannot
fan out WebSocket events across workers, and locks under concurrent writes.

## ADR-009 — Grouped (by site) stratified dataset split
**Status:** Accepted · 2026-08-12
**Context.** Fixed-angle cameras produce many near-identical frames of the same building. A
random split puts frames of one building in both train and test, inflating accuracy.
**Decision.** Split by site with `StratifiedGroupKFold`; commit `split_manifest.csv`.
**Consequences.** Reported accuracy reflects generalization to *unseen sites*, which is the
real deployment condition. Cost: lower headline numbers than a random split would show — and
a much stronger answer when an examiner asks about leakage. See [[Dataset-Spec]].
**Rejected.** Random split (leaky, indefensible).

## ADR-010 — Reference uploads (blueprints / 3D renders) are stored, not modelled, in v1
**Status:** Accepted · 2026-08-12
**Context.** The spec describes uploading a 3D render or blueprint "for the AI to follow."
Comparing site photos against a plan requires viewpoint registration and plan understanding —
a research project of its own.
**Decision.** v1 stores, displays, and includes references in reports; the model does not
consume them. Documented as future work.
**Consequences.** The feature ships and is useful to humans; the thesis states the boundary
honestly rather than implying capability that isn't there. Tracked in [[Open-Questions]].
**Rejected.** Silently shipping the upload button while implying the AI uses it.

## ADR-011 — Python packaging topology: three dependency groups, `ai` as a src-layout library
**Status:** Accepted · 2026-08-13 (Module 01)
**Context.** The vault requires two things that the original Module 01 plan never reconciled:
`ai/` must be runnable standalone, and *"the API process never runs torch"*. With
`backend/pyproject.toml` and a bare `ai/requirements.txt` there was no defined mechanism for
the worker to import `ai.inference` — the usual outcome is a `sys.path` hack or a copied
directory. Separately, a flat `ai/` (package and project root being the same directory)
cannot be expressed as an installable distribution.
**Decision.**
1. `ai/` is a real distribution, `geovision-ai`, in **src-layout**: `ai/src/ai/`. The import
   path stays `ai.progress.aggregator`; only the on-disk path gains `src/`.
2. `backend` declares three dependency sets: **base** (API — no torch, no OpenCV),
   **`[worker]`** (base + `geovision-ai` as an editable path dependency), **`[dev]`** (tooling).
3. The boundary is enforced mechanically by `backend/.importlinter` (contract
   `no-torch-in-api`) and by `tests/unit/test_architecture.py`, which asserts that importing
   `app.main` does not load `torch` into `sys.modules`.
**Consequences.** The "API is torch-free" rule is now structurally true instead of a
convention someone must remember; the API image stays ~200 MB rather than ~2.5 GB; src-layout
means `pytest` exercises the *installed* package, so a missing `__init__.py` or a bad
packaging config fails locally instead of at deploy time. Cost: one extra directory level in
`ai/`, and `Repository-Structure.md` had to be updated to match.
**Rejected.** (a) Flat `ai/` with `sys.path` manipulation — fragile, breaks IDE resolution and
editable installs. (b) `ai/ai/` double nesting — installable, but confusing to read.
(c) A single merged project — would force torch into the API process, contradicting the vault.

## ADR-012 — Tooling: uv + committed lockfiles, ruff-only, CPU-pinned torch
**Status:** Accepted · 2026-08-13 (Module 01)
**Context.** Three separate problems surfaced while implementing Module 01. The original plan
promised "no TensorFlow in either lockfile" while producing no lockfiles at all;
`pip install torch` defaults to the ~2.5 GB CUDA build even on machines with no NVIDIA GPU;
and running both `black` and `ruff` means two tools that can disagree about the same file.
**Decision.**
1. **uv** for both Python projects, with `uv.lock` **committed**. Reproducibility is a stated
   thesis requirement — every reported number must be traceable to an environment.
2. **ruff only** — `ruff check` + `ruff format`. Black and isort are dropped; ruff's formatter
   is black-compatible and roughly 30× faster.
3. **Torch pinned to the CPU index** via `[tool.uv.sources]`. GPU training is a documented
   one-line opt-out; no code changes are needed because every entrypoint already selects
   `cuda if torch.cuda.is_available() else cpu`.
4. The no-TensorFlow rule is enforced by `scripts/check_no_tensorflow.py`, which scans
   declared dependencies, **resolved lockfiles** (where a transitive violation would appear),
   and the live environment. It runs in pre-commit and as its own CI job.
**Consequences.** Fast, reproducible installs; one formatter; a laptop-sized default install;
and a constraint that is checked rather than asserted. Cost: contributors need `uv`
(one `pip install uv`), and the earlier CI check had to be rewritten — `pip list | grep
tensorflow` exits 0 when TensorFlow is *found*, so the original form passed precisely when it
should have failed.
**Rejected.** pip + `requirements.txt` (no real lockfile, slow resolution); Poetry (slower,
and its lock format is less transparent to a reader); leaving torch unpinned (multi-GB
downloads on every fresh machine and CI run).

## ADR-013 — Celery runs in a Linux container; `--pool=solo` locally on Windows
**Status:** Accepted · 2026-08-13 (Module 01)
**Context.** Development happens on Windows 10. Celery's default **prefork** pool depends on
`fork()` and does not work on Windows; the failure appears at Module 09 as tasks that never
execute, which reads like an application bug rather than a platform limitation.
**Decision.** The worker runs in a Linux container (dev and production). For quick local
debugging, `.\dev.ps1 worker` passes `--pool=solo`, and the constraint is documented in
`backend/README.md` and `infrastructure/tasks/__init__.py` where someone will actually meet it.
**Consequences.** No lost days at Module 09; dev and production behave identically; solo pool
remains available for stepping through a task in a debugger. Cost: Docker Desktop becomes a
prerequisite for the full local stack — recorded in [[Open-Questions]].
**Rejected.** `--pool=solo` as the standard everywhere (no concurrency, hides real
parallelism bugs until deployment); eventlet/gevent (extra dependency, subtle monkey-patching
interactions with asyncpg and torch).

## ADR-014 — Pin `stringzilla<4` (transitive, Windows wheel availability)
**Status:** Accepted · 2026-08-13 (Module 01) · *revisit when upstream ships wheels*
**Context.** `albumentations` → `albucore` → `stringzilla`. stringzilla 5.x publishes no
CPython 3.11 Windows wheel, so `uv sync` attempts a source build and fails with *"Microsoft
Visual C++ 14.0 or greater is required"*. Requiring every contributor to install MSVC Build
Tools to train an image classifier is a poor trade.
**Decision.** Pin `stringzilla<4` (resolves to 3.12.6, which ships a Windows wheel and is
API-compatible with albucore's usage) and move to `albumentations>=2.0`, the current stable
line. The pin carries an inline comment explaining that it is transitive, not a direct import.
**Consequences.** `uv sync` succeeds on a clean Windows machine with no compiler toolchain.
Cost: a transitive pin to revisit, and albumentations 2.x changed several transform
signatures — `Dataset-Spec.md` was corrected accordingly (notably
`A.RandomResizedCrop(size=(224, 224))` rather than the 1.x positional form). Module 07 must
be written against the 2.x API.
**Rejected.** Requiring MSVC Build Tools (a real barrier for a thesis project); staying on
albumentations 1.x (same stringzilla dependency, and an unmaintained line).

---

## Template
```markdown
## ADR-NNN — <title>
**Status:** Proposed | Accepted | Superseded by ADR-NNN · <date>
**Context.** …
**Decision.** …
**Consequences.** … (including costs)
**Rejected.** … (and why)
```

## Related
[[Master-Architecture]] · [[Open-Questions]] · [[Thesis-Mapping]]
