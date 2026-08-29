---
title: Open Questions & Deferred Scope
type: decisions
status: living
updated: 2026-08-29
---

# Open Questions, Assumptions & Deferred Scope

Three lists. Keep them current — the third one is your thesis "Limitations and Future Work"
chapter, written incrementally instead of invented the night before submission.

---

## 1. Needs a decision or verification (blocking-ish)

| # | Question | Why it matters | Owner | Status |
|---|---|---|---|---|
| Q1 | Are the nominal stage percentages in [[Construction-Stages]] realistic? | They set every progress number in the system. Get a civil engineer / project manager to review and cite it. | you + advisor | **answered 2026-08-27, expert review still open** — the team's own read: not claimed to be precisely realistic, and that's accepted, since they exist so the model can be trained/evaluated at all. What the team actually wants tied to "the deadline in the contract" is the schedule/delay status, not the raw AI percentage — see [[ADR-Index#ADR-038\|ADR-038]], which routes that through the existing [[Project-Status-Rules]] mechanism instead of into the progress number itself. Getting a civil engineer/PM to review the floor/ceiling bands and citing it is still unresolved. |


| Q2 | Exact ESP32-CAM pinout for GPS + DS3231 on *your* board revision | Board revisions differ; camera uses most GPIOs. Verify with a multimeter and record in [[ESP32-CAM-Node]]. | you | **changed 2026-08-27, tooling shipped 2026-08-28 — no hardware in hand right now.** Near-term capture comes from a phone (Wi-Fi upload) or a PC webcam instead, hitting the same ingest API. `backend/scripts/capture_and_upload.py` now does this: reuses `simulate_device.py`'s pairing/HMAC-signing code directly (never reimplemented), supports a one-shot webcam frame, a one-shot existing file, or watching a folder for phone-synced photos, and reads GPS from a photo's own EXIF when present. The pinout question itself stays open until real ESP32-CAM hardware is back in hand. |

| ~~Q3~~ | ~~Which real construction site(s) can you deploy on, and with whose permission?~~ | Real captures are what make this a thesis instead of a demo. Written permission also matters for the images you publish. | you | ✅ **done 2026-08-18** — site identified, written permission in hand, expected ready in ~3–4 weeks |

| Q4 | Where does the server run for the live deployment? | The ESP32 needs a reachable HTTPS endpoint (Cloudflare Tunnel is the cheap answer). | you | ✅ **decided 2026-08-27 — Cloudflare Tunnel.** Implementation belongs to [[Module-16-Deployment]]. |

| Q5 | How many labelled images can you realistically gather before training? | Determines whether the ≥ 85 % target is achievable ([[Dataset-Spec]]). | you | **answered 2026-08-27 — team estimates 80-130/class**, below [[Dataset-Spec]]'s documented 150/class minimum. **Final, verified `dataset/raw/` tally after sorting and de-duplication (2026-08-27): Foundation 37, Structural 381, Roofing 110, Finishing 122** (see [[Dataset-Spec]]). Roofing/Finishing sit within the team's own estimate; Structural is well past it; Foundation is still the one real shortfall, even after sorting recovered 7 previously-uncategorized photos into it. |

| Q6 | Timezone/window policy — daily windows in `Asia/Manila`? | Affects aggregation boundaries and reports. Default assumed daily/Manila. | you | ✅ **confirmed 2026-08-27** — was already the assumed default; now explicit. |


| Q7 | GPU available for training? | If not, budget Colab/Kaggle time for YOLO ([[Module-08-YOLO-Detection]]). | you | ✅ **done 2026-08-28 — Kaggle**, with ready-to-run notebooks: `ai/notebooks/kaggle_train_classifier.ipynb` and `kaggle_train_detector.ipynb`. Both install the `ai` package with `--no-deps` deliberately, so Kaggle's GPU-enabled torch is never overwritten by the project's CPU-pinned wheel (ADR-012). The classifier notebook is fully runnable today; the detector notebook is written and correct but genuinely cannot produce a result until annotation exists. |

| Q8 | Does the panel expect a specific documentation format (IEEE/school template)? | Cheap to ask now, expensive to reformat later. | you + advisor | ✅ **answered 2026-08-27 — no specific format required.** |

| ~~Q9~~ | ~~**Install Docker Desktop (WSL2 backend).**~~ | Not installed on the dev machine as of 2026-08-13. Module 01 verifies fully without it, but Module 02 onward needs a real PostgreSQL, and ADR-013 puts the Celery worker in a Linux container. This is the one prerequisite blocking the next module. | you | ✅ **done 2026-08-14** |


| Q10 | Where will trained checkpoints (`models/*.pt`) live, given they are git-ignored? | They are too large for git and must still be reproducible/shareable for the defense. Options: GitHub Release assets, Google Drive with a documented hash, or git-lfs. | you | ✅ **decided 2026-08-27 — GitHub Releases** for the checkpoint actually used in the defense (free, versioned, lives next to the repo). Since training happens on Kaggle (Q7), also publish interim checkpoints as a **Kaggle Dataset/Model** straight from the training notebook — zero extra upload step, also free. Hugging Face Hub is a third free option if a checkpoint ever exceeds GitHub's 2 GB/file limit (unlikely for ResNet18/YOLOv8-s). Google Drive + a documented SHA-256 hash is the simplest fallback if neither fits. |

| Q11 | Reprocessing an image **deletes** its previous prediction rather than superseding it. | Better provenance would keep both and mark one superseded, so "what did the old model say?" stays answerable after a retrain — genuinely useful for the thesis's model-comparison chapter. Keeping both today is *wrong*, though: `list_eligible_in_window` would count them both and one photograph would vote twice in its own aggregation window, moving the progress number. Doing it properly needs a `superseded_at` (or `is_current`) column on `predictions`, i.e. a Module 02 migration. | you | ✅ **done 2026-08-28 — see [[ADR-Index#ADR-039\|ADR-039]].** `superseded_at` column, partial unique index, `supersede_for_image`/`list_history_for_image` on the repository, all wired through and tested (700 backend tests green). |

| Q14 | **The notification endpoints do not exist.** | [[API-Contract]] lists `GET /users/me/notifications` and `POST /users/me/notifications/{id}/read`, and [[Module-12-Owner-Dashboard]] specifies a `/notifications` page. Neither route is implemented — the OpenAPI schema contains **no path matching `notif`** — although the `notifications` table, entity, and repository all exist, and Modules 09/10 already write rows (inspection required, device offline). So notifications are being *recorded* and never *shown*. The page was not built rather than built against nothing. Needs two endpoints and a bell in the header. | you | ✅ **decided 2026-08-27 — build it as a first-class feature**, not a cosmetic afterthought: the team wants it specifically so collaborators are alerted to inconsistencies, delays, and remarks other collaborators made. Not yet implemented — scheduled in [[Remaining]]. |

| ~~Q15~~ | ~~**`storage_backend` and `nonce_cache_backend` have the same test/production asymmetry that hid the startup bug.**~~ | Tests build settings with `storage_backend="local"` and `nonce_cache_backend="memory"`, while `s3`/`redis` are what a deployed environment is actually required to run (`local`/`memory` are refused there). Those adapters were therefore constructed by *no test* — exactly the condition that let `RealtimeSubscriber` reach production unbuilt (see [[ADR-Index#ADR-033]]). `tests/unit/test_app_boots.py::TestAdapterWiring` now constructs `S3ObjectStorage` and `RedisNonceCache` directly under their real settings (both connect lazily — a boto3 client and a `redis.asyncio.Redis` client do nothing on the network until a command is issued — so no MinIO/Redis needed), plus two tests pinning that a deployed environment actually refuses `local`/`memory`. | you | ✅ **done 2026-08-18 (Module 15)** |

| Q13 | **The homepage feed omits `owner` and `latest_image`, and search has no locations index.** | [[Module-11-Public-Dashboard]] specifies a feed card with a thumbnail and the owner's name; `/public/feed` returns `ProjectSummaryResponse`, which has neither. The card renders without them today (it still shows progress, stage, status, location, coordinates, and — the most decision-relevant field — the relative age of the last capture). Adding them needs a **lateral join** for the latest image per project plus the owner, not a per-card lookup: an N+1 on the anonymous homepage is the worst possible place for one. Separately, `/public/search` returns projects and users only, so the Locations tab is derived from project matches client-side. Both are cosmetic gaps rather than wrong data. | you | ✅ **decided 2026-08-27 — build the lateral join and a real locations endpoint** (delegated to engineering judgement: "do what's more optimized/professional"). Not yet implemented — scheduled in [[Remaining]]. |

| ~~Q16~~ | ~~**The Playwright E2E journeys (`tests/e2e/`) have never actually been run against a live stack.**~~ | Run for real 2026-08-18. The **first** run caught two real bugs no unit or integration test had ever caught, because none of them log in with seeded credentials the way a browser does: (1) `scripts/seed_db.py`'s `DEV_PASSWORD_HASH` was a placeholder — a literal all-zeros Argon2 digest that never verifies against any password — so **every seeded login had been broken since the row was written**; fixed by computing a real hash of `"geovision-dev"`. (2) with that fixed, login got one step further and 500'd: the seeded emails used `@geovision.test`, and `email-validator` (the library behind Pydantic's `EmailStr`) rejects `.test` as an RFC 2606 reserved/special-use domain when validating the **response** model — a check that only fires once a `UserResponse` actually gets built, which login never reached before bug (1) was fixed. Changed to `@gvmail.com`, matching the domain every other test file in the project already used. Both pinned: `tests/unit/test_seed_db.py` (new) asserts the hash verifies; the E2E suite itself is the regression test for the email issue. **12/12 E2E tests pass** as of this run, including the manuscript screenshots. | you | ✅ **done 2026-08-18**|

| Q17 | **Coverage `fail_under` thresholds were set from partial evidence.** | `backend/pyproject.toml`'s `fail_under = 60` is a verified-safe floor from a **unit-only** run (63.10%) — Docker was not available to run `tests/integration/` (needs Postgres/Redis/MinIO) in the same session, so the real combined number CI actually measures (unit + integration together) is unknown but can only be *higher*. `ai/pyproject.toml`'s `fail_under = 85` **is** the full, real number (89.61% measured, no services required). Raise the backend threshold toward the vault's stated ≥80% target once a run against live services confirms the actual combined figure — do not lower either number without a reason recorded here. | you | ✅ **resolved 2026-08-27** — re-run against live Postgres/Redis/MinIO after the ADR-038 changes: **700 tests passed, 81.03% combined coverage.** Identical to the 2026-08-18 measurement, confirming the existing `fail_under = 78` threshold is still correctly calibrated — no change needed. |

| Q18 | **The fused progress formula (classifier + YOLO detections + physical change) is undecided.** | [[ADR-Index#ADR-036\|ADR-036]] narrowed the classifier to 4 macro-aligned classes and moved sub-stage resolution to a fusion of classifier class + YOLO detections + frame-to-frame physical change, replacing the old 10-class nominal-percentage table. | you | ✅ **resolved 2026-08-27 — see [[ADR-Index#ADR-038\|ADR-038]].** `sub_stage_fraction = (classifier confidence + YOLO checklist coverage) / 2`, mapped onto the class's floor-ceiling band; the contract deadline drives the schedule *status* (existing [[Project-Status-Rules]] mechanism), not the raw progress number; frame-to-frame physical change is deferred to future work. Implemented in `ai/progress/estimator.py` + `mapping.py` + `classes.yaml`, wired through `backend/app/worker/inference.py`, verified: 276 ai tests + 435 backend unit tests green, ruff/mypy/lint-imports clean, `progress_reference.csv` regenerated. [[Progress-Calculation]] and [[Construction-Stages]] updated to match. |

| ~~Q12~~ | ~~**`get_session` commits after the response is sent.**~~ | Measured 2026-08-14 on the live API: a project row is committed **6.9 ms after** its `201` reaches the client, so a real network client that reads its own write gets a `404`. The commit sits in a `yield`-dependency's exit code, and FastAPI runs that *after* delivering the response. **The whole test suite is blind to it** — `httpx.ASGITransport` awaits the entire ASGI call, teardown included, before returning the response, so tests always observe the committed state. Affects every write endpoint since Module 03, not just Module 09. Module 12's dashboard does create-then-navigate, which is exactly the failing pattern. Fix is a `TransactionalRoute`/`APIRoute` subclass (or equivalent) that commits inside the endpoint scope, before the response propagates — a foundation change touching every router, hence not done inside Module 09. | you | ✅ **fixed 2026-08-15 (ADR-031)** - verified live: 5/5 writes durable before the response, immediate read-back returns 200 |

| Q19 | **`ultralytics` (YOLOv8) transitively depends on plain `opencv-python`, which collides with this project's pinned `opencv-python-headless` (ADR-012).** Both distributions install a top-level `cv2` package, so whichever installs last wins the directory — a silent, order-dependent footgun, not a resolver error. Discovered 2026-08-29 building Module 16's worker image: adding `geovision-ai[detect]` to the backend's `worker` extra downloaded plain `opencv-python` (42 MB, GUI build) alongside the headless one. | The worker container needs `ultralytics` once Module 08 produces real YOLOv8 weights, but installing it naively risks the GUI `opencv-python` winning, which then fails at import time on a slim/headless base image (`libGL.so.1` missing). Needs a real fix — most likely `--no-deps` for `ultralytics` plus an explicit list of its actual other dependencies, mirroring how `ai/notebooks/*.ipynb` already isolate `ultralytics`'s torch pin (Q7) — not a `uv` override, since overrides only change a version constraint for a given package name, not substitute a different distribution. | you | **open — deferred to Module 08's rollout.** Not blocking anything today: no trained detector exists yet, so `worker = ["geovision-ai"]` (no `[detect]`) is enough, and the deployed worker correctly runs with no detector (`ai/inference/service.py`'s `build_service`, 2026-08-29). Revisit when Module 08 has real weights to serve. |

## 2. Assumptions made (revisit if any proves false)

1. Cameras are **rigidly fixed**; the viewpoint does not change across the project. If a
   camera is bumped, its homography and history are invalidated — currently handled only by
   re-calibration.
2. One primary building per camera view.
3. Construction proceeds in the canonical order in [[Construction-Stages]] (renovations and
   phased/multi-tower builds are out of scope).
4. Daylight captures only; night imagery is rejected by the quality gate.
5. Site Wi-Fi is available at least intermittently.
6. Progress is estimated from **exterior** appearance only — interior work is invisible to
   the system. This is a real and significant limitation: a building can be 40 % complete
   externally and far along internally. **Say this plainly in the thesis.**
7. Linear expected-progress curve for the delay calculation ([[Project-Status-Rules]]).
8. One project = one building.

## 3. Deferred to future work (explicitly out of v1 scope)

| Feature | Note |
|---|---|
| Blueprint/3D-render-aware AI | ADR-010 — v1 stores references but does not model them |
| Automatic weather ingestion (PAGASA/OpenWeather) to justify delays | v1 uses manual weather remarks |
| Email verification + password reset | column exists; flow deferred |
| Push/email/SMS notifications | in-app only in v1 |
| Multi-building and phased projects | one building per project |
| Interior progress monitoring | needs indoor cameras or manual input |
| Device OTA firmware updates | manual flashing in v1 |
| Remote "capture now" over a device WebSocket | only meaningful for mains-powered nodes |
| Solar power | documented in [[Capture-Schedule-and-Power]], not built |
| Mobile app | the dashboard is responsive instead |
| Cost/budget tracking, Gantt integration | out of scope |
| Multi-tenant orgs / teams | projects + members are sufficient for v1 |
| Model retraining from production captures (active learning) | strong future-work section |
| Semantic segmentation for finer progress | a natural next research step |
| Time-lapse video export | nice demo feature, low thesis value |
| i18n / Filipino localization | English only in v1 |
| Frame-to-frame physical change as a progress signal | part of the original Q18 draft; needs calibration data this project does not have yet — deferred by ADR-038 |

## 4. Known risks

| Risk | Impact | Mitigation |
|---|---|---|
| Not enough training data | model underperforms the target | start collecting now; time-lapse frames; transfer learning; report honestly |
| Hardware arrives late or DOA | no field deployment | order early, buy a spare ESP32-CAM, build against `simulate_device.py` |
| Site access withdrawn | no real captures | secure a backup site; keep a public time-lapse fallback |
| Typhoon damages the deployment | data gap | IP65 enclosure, SD buffering, and document the gap (it is itself a finding) |
| Scope creep | nothing finishes | [[Build-Order]] is the contract; new ideas go in section 3 above |
| Model plateaus below 85 % | weak headline result | ablations + error analysis turn a weak number into a strong discussion; a well-analyzed 78 % beats an unexplained 85 % |

## Log

| Date | Change |
|---|---|
| 2026-08-27 | Team answered every item in §1. Q18 resolved (ADR-038, the fused progress formula); Q4/Q6/Q8/Q10/Q11/Q13/Q14 decided; Q1/Q2/Q5/Q7/Q17 answered but leave follow-up work (expert stage-percentage review, a manual capture uploader, Kaggle training notebooks, more Foundation-stage photos, a coverage re-run) — tracked day-by-day in [[Remaining]]. |
| 2026-08-18 | Q16 closed: first live E2E run, 12/12 pass, two real bugs found and fixed (seeded login was unconditionally broken; seeded emails failed response validation). |
| 2026-08-18 | ADR-036/ADR-037 recorded: classifier narrowed to 4 classes, YOLO's object list redefined (10 items), approval handoff made owner-initiated. Added Q18 (fusion formula, blocking). |
| 2026-08-13 | Module 01 shipped. ADR-011…014 recorded (packaging, tooling, Celery/Windows, stringzilla). Added Q9 (Docker Desktop) and Q10 (checkpoint distribution). |
| 2026-08-12 | Initial architecture finalized; ADR-001…010 recorded |

## Related
[[ADR-Index]] · [[Build-Order]] · [[Thesis-Mapping]] · [[Progress-Log]]
