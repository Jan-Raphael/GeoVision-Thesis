---
title: Build Order
type: modules
status: canonical
updated: 2026-08-14
---

# Build Order

> **Rule: one module per iteration.** Every module delivers all seven artifacts:
> **1** folder structure · **2** explanation · **3** source code · **4** dependencies ·
> **5** how to run · **6** testing procedure · **7** expected output.
> Do not start module *n+1* until module *n*'s tests pass and its `status:` is `done`.

## Sequence

| # | Module | Depends on | Ships when |
|---|---|---|---|
| 01 | [[Module-01-Foundation-Setup]] | — | repos, Docker, config, CI skeleton up |
| 02 | [[Module-02-Database-Schema]] | 01 | all tables migrated, seeded |
| 03 | [[Module-03-Auth-and-Users]] | 02 | register/login/profile/visibility |
| 04 | [[Module-04-Projects-and-Folders]] | 03 | create project, folder payload, members, remarks |
| 05 | [[Module-05-Device-Pairing-and-Ingestion]] | 04 | pairing token/QR, HMAC ingest, simulator uploads |
| 06 | [[Module-06-AI-Preprocessing]] | 01 | OpenCV pipeline + quality gate, unit-tested |
| 07 | [[Module-07-Classifier-Training]] | 06 | trained ResNet18 + MobileNetV3, checkpoints, metrics |
| 08 | [[Module-08-YOLO-Detection]] | 06 | trained YOLOv8, detection outputs |
| 09 | [[Module-09-Inference-Service]] | 05,06 | end-to-end: upload → prediction → progress in DB *(07/08 swap the stub for real weights)* |
| 10 | [[Module-10-Reports-and-Remarks]] | 09 | PDF/CSV reports, status derivation, system remarks |
| 11 | [[Module-11-Public-Dashboard]] | 04,09 | homepage feed, public folder, search, contact |
| 12 | [[Module-12-Owner-Dashboard]] | 11 | auth UI, create project, folder, pairing modal, devices |
| 13 | [[Module-13-Firmware]] | 05 | real ESP32 capturing, geotagging, uploading |
| 14 | [[Module-14-Realtime]] | 09,12 | WebSocket push, live dashboard updates |
| 15 | [[Module-15-Testing-and-Evaluation]] | all | full test suite + every thesis metric/figure |
| 16 | [[Module-16-Deployment]] | all | one-command compose deploy, docs, demo script |

## Dependency graph

```mermaid
flowchart LR
    M01 --> M02 --> M03 --> M04 --> M05 --> M09
    M01 --> M06 --> M07 --> M09
    M06 --> M08 --> M09
    M09 --> M10
    M04 --> M11 --> M12 --> M14
    M09 --> M11
    M05 --> M13
    M09 --> M14
    M10 --> M15
    M13 --> M15
    M14 --> M15 --> M16
```

## Parallel tracks (if working with a partner or in spare time)

- **Track A (backend):** 01 → 02 → 03 → 04 → 05 → 09 → 10
- **Track B (AI):** 01 → 06 → 07 → 08 *(needs the dataset — start collecting on day 1)*
- **Track C (frontend):** 11 → 12 → 14 *(mock the API from [[API-Contract]] until 04 lands)*
- **Track D (hardware):** 13 *(order parts on day 1; lead time is the real risk)*

## Critical-path warnings

1. **Dataset collection is the long pole.** Start gathering and annotating images during
   Module 01, not Module 07. A model cannot be trained the week before the defense.
2. **Order hardware immediately.** ESP32-CAM, GPS, DS3231, and the enclosure have shipping
   lead times that no amount of coding speeds up.
3. **Use `scripts/simulate_device.py`** so modules 05→12 are fully testable before a single
   wire is soldered.
4. **Deploy the camera on a real site as early as possible** — real captures are what make
   this a thesis rather than a demo, and they need weeks of calendar time to accumulate.

## Status board

| Module | Status | Started | Finished | Notes |
|---|---|---|---|---|
| 01 | ✅ **done** | 2026-08-13 | 2026-08-13 | Audited before building; ADR-011…014 recorded. 59 tests green, 4 import contracts kept. Docker Desktop still to install (Q9). |
| 02 | ✅ **done** | 2026-08-13 | 2026-08-13 | 18 tables, 14 repositories, reversible migration. 198 tests. Built on native PostgreSQL (no Docker yet). |
| 03 | ✅ **done** | 2026-08-13 | 2026-08-13 | Auth, profiles, permission matrix, per-account throttling. 327 tests. Audit found 4 security gaps; all fixed. Avatar upload deferred to M04. |
| 04 | ✅ **done** | 2026-08-13 | 2026-08-13 | Projects, folder payload, collaboration, assets, remarks, public surface. 413 tests. Storage port (ADR-018) removed the MinIO dependency. |
| 05 | ✅ **done** | 2026-08-14 | 2026-08-14 | Pairing + QR, HMAC ingest, race-free naming, device health, simulator. 509 tests. Corrected the vault's hashed-secret contradiction (ADR-020) and a per-process lock key that would only have failed in production (ADR-022). |
| 06 | ✅ **done** | 2026-08-14 | 2026-08-14 | Preprocessing pipeline, quality gate, calibration, thesis Figure 6, ~88 ms/image. 113 tests. Added a config fingerprint (ADR-025) and a CI parity guard for shared constants (ADR-023); resize/denoise order reversed on measurement (ADR-024). |
| 07 | ⏸ **blocked** | | | **Needs the dataset** — P1-3, P1-4. Becomes a weights swap: Module 09 already serves a `StageClassifier` protocol. |
| 08 | ⏸ **blocked** | | | Needs the dataset. |
| 09 | ✅ **done** | 2026-08-14 | 2026-08-14 | Progress engine, stub models, worker, and the full HTTP surface. 765 tests. Verified end to end against live PostgreSQL + Redis + MinIO + worker (39/39): upload → prediction → 27.0 % progress → `/predict` → reprocess. Built ahead of 07/08 against a deterministic stub, which unblocked 10-14. ADR-026…029; the E2E caught a worker bug no test could see (ADR-029). |
| 10 | ◑ **reports done** | 2026-08-14 | | **Split at its own seam.** Shipped: PDF (9 sections, 3 charts, required disclaimer), CSV (two tables), period rules, `reports.generate` on its own queue, 4 endpoints. 803 tests. Deferred to a second pass: `derive_status` scheduling, automatic system remarks + dedup, device offline sweep, Celery **beat**. ADR-030. |
| 11 | planned | | | |
| 12 | planned | | | |
| 13 | planned | | | |
| 14 | planned | | | |
| 15 | planned | | | |
| 16 | planned | | | |

Keep this table current — it is the fastest way for a new session to know where things stand.
Longer entries go in [[Progress-Log]].

## Related
[[00-START-HERE]] · [[Master-Architecture]] · [[Repository-Structure]]
