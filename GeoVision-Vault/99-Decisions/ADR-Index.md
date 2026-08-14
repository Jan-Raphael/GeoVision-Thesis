---
title: ADR Index
type: decisions
status: canonical
updated: 2026-08-14
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

## ADR-015 — Access and refresh tokens are not interchangeable
**Status:** Accepted 2026-08-13
**Context.** The Module 03 spec described short access tokens and long rotating refresh
tokens, but nothing distinguished them once signed. A refresh token presented in an
`Authorization: Bearer` header would have authenticated normally.
**Decision.** Every token carries a `typ` claim; `verify_token` demands the expected type and
raises otherwise. Refresh tokens are additionally *opaque random strings*, not JWTs, since
they are looked up in the database on every use anyway.
**Consequences.** A stolen refresh token cannot be used as an access token, so the 15-minute
access lifetime actually bounds an attacker's window. Cost: one extra claim and one check.
**Rejected.** Separate signing keys per token type — equivalent security, more key material
to manage and rotate.

## ADR-016 — Two independent throttles on login
**Status:** Accepted 2026-08-13
**Context.** The spec called for per-IP rate limiting on `/auth/login`. That stops one host
hammering the endpoint but is bypassed by an attacker with many source addresses, which is
exactly how credential stuffing works. An attempt to key slowapi on the login identifier
failed for a structural reason: its key function runs *before* the endpoint, so the request
body is not yet available.
**Decision.** Keep the per-IP limiter, and add a separate per-account **failed-attempt**
throttle inside the use case, where the identifier exists. Only failures count; success
clears the counter. Keys are hashed, so identifiers never enter the store.
**Consequences.** Single-account attacks are throttled wherever they originate, and a
legitimate user is never limited for logging in correctly. Cost: two mechanisms to
understand. The in-memory backend counts per process, so several API workers multiply the
allowance — replaced by an atomic Redis counter in Module 05.
**Rejected.** Per-IP only (bypassable); account lockout on failure (a denial-of-service
against any known username).

## ADR-017 — Exception types are framework-free; HTTP rendering is not
**Status:** Accepted 2026-08-13
**Context.** `core/exceptions.py` held both the `DomainError` hierarchy and the FastAPI
handlers. Because use cases raise those types, the **application layer transitively imported
the web framework** — caught by the `application-independence` contract in
`backend/.importlinter`.
**Decision.** Types stay in `core/exceptions.py` with `http.HTTPStatus` for status codes;
handler registration moves to `api/error_handlers.py`.
**Consequences.** Use cases stay testable without FastAPI, and the layering contract passes.
Cost: one more file. Worth noting this was found by an automated check, not review.

## ADR-018 - Object storage behind a port, with a local backend for development
**Status:** Accepted 2026-08-13
**Context.** Module 04 needs somewhere to put uploaded blueprints, but Docker (and therefore
MinIO) was not yet installed. The options were to stub the upload, block the module, or
abstract the dependency.
**Decision.** Define an `ObjectStorage` port in the application layer with two
implementations: `LocalObjectStorage` (filesystem) and `S3ObjectStorage` (MinIO/S3). The
backend is chosen by `GV_STORAGE_BACKEND`; a deployed environment may not choose `local`,
enforced by a settings validator.
**Consequences.** Module 04 ships complete today, the test suite needs no object store, and
**Modules 05 and 10 inherit both backends for free** because they depend on the same port.
Development and production differ in one documented way: the local backend cannot issue
genuinely pre-signed URLs, so the asset download route re-checks permission rather than
trusting the URL - which is the safer behaviour under either backend anyway. Cost: two
implementations to keep in step, and a real risk of a "works locally" gap if the S3 path is
not exercised. It is exercised as soon as Docker lands.
**Rejected.** Waiting for Docker (blocks a module for an unrelated reason); storing blobs in
PostgreSQL (contradicts ADR-005); a filesystem-only design (unshippable).

## ADR-019 - The public view is a separate response model, not a filtered one
**Status:** Accepted 2026-08-13
**Context.** A project folder has both public fields (progress, timeline, location) and
private ones (members, devices, worker counts, inspection notes). The obvious approach is to
serialise the internal model and drop the private keys.
**Decision.** Anonymous callers get `PublicProjectResponse`, a distinct model that simply has
no fields for the private data. The same pattern already applies to `PublicProfile` in
Module 03.
**Consequences.** A field added to the internal model later cannot leak, because there is
nowhere for it to go - the failure mode changes from "somebody forgot a line" to "somebody
has to deliberately add a field to the public model". Cost: two models to maintain, and they
can drift in the *harmless* direction (public missing something it could show).
**Rejected.** Filtering a shared model with an exclude-list - one forgotten entry is a
privacy breach, and nothing fails loudly when it happens.

## ADR-020 - Device secrets are encrypted at rest, not hashed
**Status:** Accepted 2026-08-14 · corrects [[Device-Pairing-Protocol]] Phase 2
**Context.** The pairing protocol note said two things that cannot both be true: store only
the *hash* of `device_secret`, and verify each request with
`HMAC_SHA256(device_secret, canonical_string)`. A password can be hashed because the server
only ever compares it. A MAC key cannot - the server has to recompute the MAC, which means
it needs the key back. Implemented as written, every signed request from every camera would
have failed verification, and the failure would have looked like a firmware bug.
**Decision.** `devices.secret_encrypted` holds the secret encrypted with Fernet
(AES-128-CBC + HMAC-SHA256), keyed on `GV_DEVICE_SECRET_KEY`. Required in staging and
production; a fixed, obviously-fake key in local development so cameras paired in one
session still authenticate after a restart. Decryption failure returns `None` rather than
raising, so a rotated key degrades to "this camera cannot authenticate" instead of a 500.
Pairing *codes* remain hashed - those are only ever compared.
**Consequences.** A stolen database dump is still useless on its own: the ciphertext needs
the key, which lives in the environment, not the database. The cost is that the key is now
a real operational secret - losing or rotating it un-pairs every camera, which must then be
re-provisioned by hand on a roof. That is documented in `.env.example` next to the setting.
Also: the m05 migration drops the old `secret_hash` column rather than migrating it, because
no value stored there could ever have worked.
**Rejected.** Hashing the secret and having the *device* prove knowledge via a
challenge-response handshake - correct, but it adds a round trip per wake to a
battery-powered camera and considerably more firmware. Storing the secret in plaintext -
one dump and every camera is forgeable. Asymmetric signatures (device holds a private key,
server a public one) - genuinely better, and the honest reason against it is cost: ECDSA on
an ESP32 is far slower than HMAC, and the thesis scope does not include a PKI. Worth
revisiting if the project ever leaves a single-operator deployment.

## ADR-021 - Replay protection is a port with a memory and a Redis backend
**Status:** Accepted 2026-08-14
**Context.** Nonce checking needs an atomic "claim this key if unseen". Redis does it in one
`SET … NX EX`. But binding Module 05 to Redis would mean no ingest test could run without a
container, repeating the Module 04 problem that ADR-018 solved for object storage.
**Decision.** A `NonceCache` protocol with two implementations: `InMemoryNonceCache` for
tests and single-process development, `RedisNonceCache` for anything real. Selected by
`GV_NONCE_CACHE_BACKEND`, and `memory` is **refused** in staging and production by the same
settings validator that refuses local storage.
**Consequences.** The full ingest suite runs with no infrastructure, and the Redis path is
exercised by the end-to-end simulator run. The refusal matters more than it looks: an
in-memory cache stops protecting the moment a second worker exists, because each process
holds its own set and a replayed request only has to land on the other one. That failure is
invisible - uploads succeed - so it has to be a startup error rather than a warning.
**Rejected.** Redis-only (blocks all testing on a container); a database table for nonces
(a write per request on the hottest path, plus a sweep job, to store data that is worthless
after five minutes).

## ADR-022 - The daily sequence lock key is a stable digest, never Python's `hash()`
**Status:** Accepted 2026-08-14
**Context.** Filenames carry a per-project per-day sequence number, allocated under a
PostgreSQL advisory lock so two cameras waking at 07:00:00 cannot both be handed `001`. The
first implementation derived the lock key with `hash((str(project_id), day))`.
**Decision.** Derive it with BLAKE2b over `{project_id}:{day}`, masked to 63 bits.
**Consequences.** Python randomises string hashing per interpreter process
(`PYTHONHASHSEED`), so two uvicorn workers - or two containers - would have computed
*different* keys for the same project and day, taken different locks, and serialised
nothing. The bug is invisible in every single-process test, and in production it surfaces as
two images sharing a filename, one silently overwriting the other in object storage, under
exactly the name an owner is expected to reconcile against a site diary. The key is now
pinned to a literal in `test_sequence_allocation.py` so a "cleanup" cannot quietly reopen
it.
**Rejected.** A dedicated `sequences` table (an extra row and write per upload for something
the lock already gives); `SELECT … FOR UPDATE` on the project row (serialises *all* writes
to a project, not just same-day sequence allocation).

## ADR-023 - Shared constants are parsed, not imported, across `ai/` and `backend/`
**Status:** Accepted 2026-08-14 · corrects [[Progress-Calculation]] §9
**Context.** §9 names `ai/progress/constants.py` as the single definition site for every
threshold, "imported by both `ai/` and `backend/`". That import cannot happen. The backend's
base dependency group deliberately excludes `geovision-ai` so the API process never loads
torch (ADR-011), and installing the package to read two numbers would drag torch into every
API container. The duplication already existed before anyone noticed: `MACHINE_CEILING` and
`MIN_ELIGIBLE` sit in `backend/app/domain/value_objects.py` as well.
**Decision.** `ai/progress/constants.py` stays the definition site. The handful of values the
backend genuinely needs are restated there, and `scripts/check_constants_parity.py` — run in
the `constraints` CI job — **parses both files with `ast` and fails the build if they
disagree**. No import in either direction, no package installed, no torch, no virtualenv;
it runs in under a second against a bare Python.
**Consequences.** The stated invariant is now actually enforced rather than merely asserted
in a note, and it is enforced without weakening the dependency boundary that keeps torch out
of the API. Divergence becomes a red build with the two values printed side by side. Cost: a
small bespoke script, and a `PAIRS` table that must be extended when a genuinely shared
constant is added — a constant used by only one side deliberately does *not* go in it, since
forcing the backend to carry a number it has no use for is worse duplication than none.
**Rejected.** Adding `geovision-ai` to the backend's dev group and writing a normal import
test — pulls torch into every developer environment and CI lint job to check two floats, and
still leaves the runtime duplication unguarded. A shared YAML both packages parse at runtime
— moves the numbers out of code, where they are least readable, and adds a file-read to a
hot path. Accepting undocumented duplication — this is precisely the defect that stays
invisible until a thesis figure disagrees with the running system.

## ADR-024 - Resize before denoise, reversing the documented step order
**Status:** Accepted 2026-08-14 · amends [[Module-06-AI-Preprocessing]]
**Context.** The module note orders the pipeline denoise (5) then resize (6), while also
saying "bilateral filter is slow at full resolution; resize before denoise if latency is
tight (measure it; note the choice in the thesis)". So: measured.
**Decision.** Resize precedes denoise. Median of 10 warm runs on the target CPU over a
1600x1200 frame: bilateral filtering costs **30.1 ms** at full resolution and **4.0 ms** at
224x224 — 7.5x, since its cost scales with pixel count. The whole pipeline goes from ~114 ms
to **~88 ms** per image, about 23%.
**Consequences.** Materially cheaper per image, which matters when a backlog of several days
arrives at once from a camera that was offline. Output is near-identical either way because
`INTER_AREA` averages over the source region and has already removed most sensor noise
before the filter runs. The ordering is a two-line swap in `preprocessing.yaml`, so the
ablation stays runnable for the thesis — and the pipeline fingerprint differs between the two
orderings, so a run can always be attributed to one or the other. Cost: a documented
deviation from the note, and a real (if small) loss of filtering fidelity on noise that only
exists at full resolution.
**Rejected.** Following the note as written — 30% more CPU per image for no measurable
quality gain. Dropping the bilateral filter entirely — it is what preserves the formwork and
scaffolding edges the classifier reads; a Gaussian at the same strength does not.

## ADR-025 - The preprocessing config carries a fingerprint
**Status:** Accepted 2026-08-14
**Context.** Module 06 exists to prevent train/serve skew, and the mechanism given for that is
"both sides build from `preprocessing.yaml`". That prevents *accidental* divergence but
detects nothing: edit the config after training and the model is served through a pipeline it
was never trained on. Skew does not raise an error. The test set stays excellent while
production accuracy quietly collapses.
**Decision.** `PreprocessingPipeline.fingerprint` is a 16-hex-character SHA-256 over every
step's position, name, and declared parameters. Module 07 writes it into the checkpoint
metadata (the `ai_models.metrics` JSONB column, so no migration is needed); Module 09
compares it at model load and refuses to serve on a mismatch.
**Consequences.** The one failure this module exists to prevent becomes a loud startup error
instead of a silent accuracy loss, and every stored prediction is attributable to an exact
pipeline. Each step must declare its parameters honestly in `describe()` — a parameter
omitted there is one that can still differ unnoticed, which is the single thing to check when
reviewing a new step. YAML lists are normalised to tuples so that a pipeline built from the
config and the identical pipeline built in Python do not fingerprint apart.
**Rejected.** Hashing the config *file* — whitespace and comment edits would change it, so
the check would cry wolf and get disabled. A hand-maintained version integer — it is only
correct while somebody remembers to bump it, and the failure mode of forgetting is exactly
the one being guarded against.

## ADR-026 - `POST /predict` is a round trip to the worker, on its own queue
**Status:** Accepted · 2026-08-14
**Context.** [[API-Contract]] specifies `POST /predict` as a synchronous, stateless demo
endpoint returning a stage and confidence in the response body, and `GET /model/status` as
reporting the device a model sits on, when it loaded, and its rolling latency. Both need a
model. **The API process is forbidden from importing torch** (ADR-011), enforced by the
`no-torch-in-api` import contract — so the API cannot answer either question itself. The
existing `TaskQueue` port is fire-and-forget and cannot express a reply.
**Decision.** A second outbound port, `InferenceGateway`, sends a Celery task and waits on the
result backend, bounded by `GV_PREDICT_TIMEOUT_SECONDS` (30 s) and
`GV_MODEL_STATUS_TIMEOUT_SECONDS` (3 s). The wait runs in a worker thread, never on the event
loop. Both tasks are routed to a **third queue, `interactive`**, separate from `inference`.
Failure is asymmetric by design: `predict` raises 503, while `status` and `queue_depth`
degrade to `None`/`{}`.
**Consequences.** torch stays out of the API image (~200 MB, not ~2.5 GB) with a synchronous
endpoint anyway. The separate queue means a site with a hundred queued captures cannot delay
the live defense demo — sharing `inference` would have made the endpoint time out for reasons
unrelated to whether it works. `/model/status` still answers when the worker is down, which is
the moment it is most needed. Costs: `/predict` needs a running worker (503 otherwise, stated
plainly), and image bytes travel base64 through Redis, so the size limit is enforced *before*
the enqueue. The worker's JSON payload and the gateway's parser are a hand-written contract
that nothing type-checks, so `tests/unit/test_inference_gateway.py` builds the payload with
the real producer and reads it with the real consumer.
**Rejected.** (a) Letting the API import torch for this one endpoint — breaks ADR-011 and the
contract that enforces it, for one demo route. (b) `202 + poll` — the contract specifies a
synchronous body, and a defense demo is precisely where a second round trip is unwelcome.
(c) Reusing the `inference` queue — see above. (d) Pickle serialisation to avoid base64 — any
writer to the broker would gain code execution in the worker.

## ADR-027 - Image routes are nested under their project
**Status:** Accepted · 2026-08-14
**Context.** [[API-Contract]] listed `GET /images/{id}`, `POST /images/{id}/reprocess`, and
`DELETE /images/{id}` at the top level. The permission guard (`require_permission`) resolves
authority from `(caller, project)` and reads `project_id` from the path.
**Decision.** Nest them: `/projects/{project_id}/images/{image_id}[/prediction|/reprocess]`.
This is the same reasoning already applied to the device routes in Module 05, now applied
consistently.
**Consequences.** The guard is structural rather than something each handler must remember. A
project-less path would have to look the image up *before* it could decide whether the caller
may know the image exists, and a 403-where-a-404-belonged there discloses other people's
capture history. The use cases additionally verify `image.project_id == project_id` and answer
404 either way, so an id from another project is indistinguishable from one that does not
exist. Cost: longer URLs, and [[API-Contract]] was corrected to match.
**Rejected.** Keeping `/images/{id}` with an internal lookup — it works, but it puts the
403-vs-404 decision in every handler instead of in one dependency, and that is a mistake that
is invisible until it leaks.

## ADR-028 - `progress:recompute` is its own permission, at manager+
**Status:** Accepted · 2026-08-14
**Context.** [[API-Contract]] marks `POST /projects/{id}/recompute` and image reprocessing as
"manager+", but the permission matrix in [[Roles-and-Permissions]] had no row for either, and
no existing permission fits: `PROJECT_EDIT` is held by editors, while `MEMBER_MANAGE` and
`PROJECT_APPROVE` are semantically unrelated.
**Decision.** Add `Permission.PROGRESS_RECOMPUTE = "progress:recompute"`, granted from
**manager** upward, covering both re-running the AI over one image and rebuilding a project's
whole timeline. The matrix in [[Roles-and-Permissions]] gains a matching row.
**Consequences.** The contract's stated authority level is now enforced rather than
approximated. Editing a project's deadline and rewriting the AI-derived figure the project is
judged on are separated, which is the distinction that matters: the second is the number a
payment or scheduling decision might rest on. Cost: one more permission in the matrix, and it
appears in the folder payload's `permissions` block, so the Module 12 UI can render the
buttons from server truth.
**Rejected.** (a) Overloading `PROJECT_EDIT` — grants it to editors, contradicting the
contract. (b) Overloading `PROJECT_APPROVE` — right role, wrong meaning; a permission named
for approval guarding a recompute is the kind of thing that gets mis-granted later.

## ADR-029 - The Celery worker's database engine is unpooled
**Status:** Accepted · 2026-08-14
**Context.** Found by the first end-to-end run against a live worker, not by any
test. Each Celery task calls `asyncio.run`, which creates an event loop and **closes it**
when the task returns. The SQLAlchemy engine was a process-wide singleton with a real
connection pool, and an asyncpg connection belongs to the loop that opened it — so the
second task checked out a connection whose loop was dead. The symptom was not a clean
error: the first task or two succeeded, then every subsequent one failed with
`RuntimeError: Event loop is closed` surfacing as
`AttributeError: 'NoneType' object has no attribute 'send'` from inside the driver, images
stopped being scored, and the reported mean latency inflated from 27 ms to 3 707 ms as
connection retries piled up. Invisible to the whole suite, because integration tests build
their own engine per fixture and never call `asyncio.run` twice against the shared one.
**Decision.** A second engine for the worker, built with `NullPool`, used by `session_scope`.
Every task additionally disposes it inside its own loop via the `_run` wrapper in
`app.worker.inference`. The API keeps the pooled engine.
**Consequences.** Each task opens one connection and closes it — a few milliseconds against
an inference of hundreds, and in exchange the worker is correct over an unbounded number of
tasks. The API is untouched: it serves many requests on one long-lived loop, which is exactly
what pooling is for. `tests/unit/test_worker_session.py` pins both halves so the pool cannot
quietly come back. Note the failure mode for anyone debugging something similar: tasks that
work in isolation and fail in sequence point at loop-scoped resources, not at the task logic.
**Rejected.** (a) One long-lived event loop per worker process with coroutines submitted to
it — faster, but it changes how every task is written for a saving of milliseconds on work
that takes hundreds. (b) Disposing the shared engine after each task — that would repeatedly
tear down the pool the API process also uses if the two ever ran in one process, and it
treats the symptom rather than the loop-scoping that causes it.

## ADR-030 - The report data contract lives in the domain, not the application layer
**Status:** Accepted · 2026-08-14
**Context.** A report is assembled once (query everything the period covers) and then
rendered twice over (PDF, CSV). The renderers import ReportLab and matplotlib, so they are
unambiguously **infrastructure**. The obvious home for the assembled bundle was the
application layer beside the use cases — and putting it there immediately broke the layers
contract, because `app.infrastructure` may not import `app.application`. The violation was
real rather than pedantic: it is the direction that, left alone, ends with renderers calling
repositories.
**Decision.** `ReportData` and `CaptureRow` live in `app/domain/reporting.py`, beside
`ReportPeriod` in `app/domain/services/reporting.py`. They aggregate domain entities and
nothing else, so both the application layer (which fills them) and infrastructure (which
formats them) may read them.
**Consequences.** The builders are pure functions from a domain aggregate to bytes: they
query nothing, which is precisely what guarantees a report cannot disagree with the dashboard
by fetching its own numbers. The same property makes them testable without a database — the
PDF is rendered for real in a unit test, including an assertion that the required disclaimer
is present. Cost: one more concept in the domain that is arguably a read model rather than a
business rule; the precedent is `StageBreakdown` and `ProjectSignals`, which are the same
shape.
**Rejected.** (a) Leaving it in application and exempting infrastructure from the contract —
the exemption would apply to every future infrastructure module, not just this one. (b)
Moving the builders into the application layer — it would put ReportLab and matplotlib in the
layer whose job is orchestration, and the contract that keeps SQLAlchemy out of there exists
for the same reason. (c) Passing primitives (dicts) across the boundary — untyped, and every
renderer would re-derive the same aggregates by hand.

## ADR-031 - The request transaction commits before the response, not after it
**Status:** Accepted 2026-08-15 - resolves Q12
**Context.** `get_session` was a `yield` dependency that committed in its exit code. FastAPI
runs that exit code from `AsyncExitStackMiddleware`, the **outermost** middleware - so it runs
*after the response has been delivered*. Measured on the live API: a project row committed
**6.9 ms after its `201` reached the client**, so a caller that read its own write got a `404`.
Create-then-navigate is exactly what a dashboard does, which is why this blocked Module 12.
The suite was blind to it, and the reason matters: `httpx.ASGITransport` awaits the entire ASGI
call - teardown included - before returning a response, so tests *always* observe the committed
state. Only a real network client could see the gap.
**Decision.** A `TransactionalRoute(APIRoute)` subclass wraps each generated handler and commits
the request's session after the handler returns but **before** Starlette sends the response.
`get_session` parks the session on `request.state` and no longer commits; it still rolls back on
exception, so the all-or-nothing guarantee is unchanged - only the *timing* of the success path
moved. Every router that touches the database sets `route_class=TransactionalRoute`; `health`
does not, because it has no session and should not pay for one.
**Consequences.** A write is durable before the client is told it succeeded, which is what every
caller already assumed. `session.in_transaction()` guards the commit, so a read-only endpoint
issues no pointless `COMMIT` - the public feed is the hottest path in the system. The regression
test drives the ASGI app **directly**, recording the order of the commit against the
`http.response.start` message, because that ordering is the entire property and no HTTP client
can observe it. A second test fails the build if a router is added without the route class,
since forgetting it reintroduces the defect silently. Cost: one more thing to remember when
adding a router - hence that test.
**Rejected.** (a) Committing inside each handler - invasive, easy to forget, and it puts
transaction scope back into business logic the repositories were designed to keep it out of.
(b) Middleware - it runs outside the dependency's exit stack, so the session is already gone by
the time it could act. (c) Living with it and having clients retry - that pushes a server defect
into every consumer, and Module 12 has several.

## ADR-032 - Audit rows for refused requests are committed before the refusal
**Status:** Accepted 2026-08-15
**Context.** Module 05 states that a device authentication failure is "logged and audited
server-side", and the generic 401 is deliberately uninformative precisely *because* the detail
was supposed to live in the audit trail. It did not: `_deny` wrote the row, the dependency then
raised, and the request rolled back - taking the evidence with it. Verified with a test before
the fix: three refused uploads produced **zero** rows. The failure mode is the nastiest kind -
the endpoint behaves exactly as designed, the log line appears, and only the durable, queryable
record is missing, so nobody notices until they go looking for a brute-force attempt that left
no trace.
**Decision.** `_deny` commits the audit row before returning the error. Safe and tightly scoped:
device authentication is a dependency that runs *before* the handler, so the audit row is the
only pending write at that moment.
**Consequences.** Attempt counting - the entire reason for auditing failures - now works, pinned
by `tests/integration/test_audit_durability.py`. Note the general shape for anything added
later: **any audit row describing a refusal has to be committed by whatever refuses**, because
the refusal itself rolls the request back. The `/ws` endpoint already does this for denied
subscriptions.
**Rejected.** A separate session or engine for audit writes - correct in principle, and the right
answer if audit ever needs to survive a *handler* failure too, but it doubles the connection cost
of the hottest unauthenticated path in the system to solve what one `commit()` solves.

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
