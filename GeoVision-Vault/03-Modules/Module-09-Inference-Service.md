---
title: Module 09 — Inference Service & Progress Engine
type: module
module: 9
aliases:
  - Module-09-Progress-Engine
  - Module-09-Inference-and-Progress
status: done
updated: 2026-08-14
---

# Module 09 — Inference Service & Progress Engine

## Scope
Wire everything together: the Celery worker that turns an ingested image into a prediction,
a set of detections, and an updated project progress number. **This is the module the whole
system exists for.**

## Deliverables
- `ai/inference/service.py` — `InferenceService`: loads the active classifier and detector
  **once** per worker process, exposes `predict(image_bytes, device_calibration)
  -> InferenceResult`. Thread-safe, `torch.inference_mode()`, warm-up call on startup.
- `ai/inference/schemas.py` — plain dataclasses shared with the backend (no ORM, no Pydantic).
- `ai/progress/mapping.py` — fine class → macro stage → nominal %, loaded from
  `progress_reference.csv` ([[Construction-Stages]]).
- `ai/progress/estimator.py` — per-image raw progress + confidence/quality gating.
- `ai/progress/aggregator.py` — **pure functions**: median per device → weighted multi-camera
  mean → EMA → stage-advance guard → monotonic ratchet → per-stage percentages.
  Exactly [[Progress-Calculation]]. No I/O in this file, ever.
- `ai/progress/constants.py` — the single definition site for every threshold.
- `backend/infrastructure/tasks/inference.py` — Celery task `inference.process_image`.
- `backend/infrastructure/tasks/progress.py` — `progress.recompute_window`.
- `backend/infrastructure/ai/adapter.py` — the backend's port to `ai/` (so the API layer never
  imports torch).
- `application/use_cases/predictions/` — `GetPrediction`, `ReprocessImage`, `PredictAdHoc`
  (the stateless `POST /predict` demo endpoint).
- `api/v1/routers/predictions.py`, `progress.py`, `models.py` (`GET /model/status`).

## Worker task flow
```python
@celery.task(bind=True, max_retries=3, default_retry_delay=30, queue="inference")
def process_image(self, image_id: str) -> None:
    1. load image row → 404-safe guard (deleted mid-flight)
    2. fetch bytes from object storage
    3. preprocessing pipeline + quality gate      → rejected? status='rejected', WS event, return
    4. store preprocessed + thumbnail
    5. classifier.predict()                       → fine class, confidence, probabilities
    6. detector.detect()                          → boxes + counts (failure is non-fatal)
    7. estimator → raw_progress_pct, is_eligible
    8. INSERT predictions + detections; images.status='inferred'
    9. enqueue progress.recompute_window(project_id, window_of(captured_at))
   10. publish WS prediction.completed
```

`recompute_window`:
```
load all eligible predictions in the window (all devices)
→ aggregator.compute(...) (pure)
→ UPSERT project_progress_snapshots
→ UPDATE projects.progress_pct / macro_stage / last_capture_at
→ derive_status() → maybe UPDATE status + system remark
→ if displayed >= 80 and not yet flagged: approval_state='awaiting_inspection',
  notification + remark + WS project.approval.required
→ publish WS project.progress.updated
```

## Critical implementation notes
- **Models load once per worker.** Loading a checkpoint per task is the classic performance
  bug here; use a module-level singleton initialized in Celery's `worker_process_init`.
- Separate queues: `ingest` (fast, high concurrency) and `inference` (concurrency 1–2 —
  torch is already multithreaded and oversubscription makes it slower, not faster).
- `recompute_window` must be **idempotent** and safe under concurrency: take a per-project
  advisory lock, always recompute from stored rows rather than incrementally patching.
- Recomputation reads **only** persisted predictions, so replaying history after an algorithm
  change reproduces the whole timeline (`algorithm_version` records which version produced a row).
- Retries: transient failures (storage timeout) retry; deterministic failures (corrupt image)
  do not — mark `failed` with a reason and stop.
- `GET /model/status` reports architecture, version, class list, metrics, device
  (`cuda`/`cpu`), loaded_at, rolling mean latency, and queue depth.
- `POST /predict` (ad-hoc) runs the identical pipeline but persists nothing — it exists for
  the live defense demo. Rate-limit it.

## Dependencies
Modules 05, 06, 07, 08. `celery`, `redis`, `torch`, `ultralytics`.

## How to run
```bash
# Windows: --pool=solo (ADR-013). Deployed: a Linux container with the default pool.
.\dev.ps1 worker            # celery -A app.worker.celery_app worker
                            #   -Q ingest,inference,interactive,reports --pool=solo
.\dev.ps1 api
uv run python -m scripts.simulate_device --code <CODE> --images ./samples --count 4
```

> The Celery app lives at **`app.worker.celery_app`**, not `app.infrastructure.tasks` —
> tasks are a delivery mechanism, the exact counterpart of an HTTP route, so they sit in the
> outermost layer beside `app.api`. Putting them in `infrastructure` made infrastructure
> import the application layer, which the import contract rejects.
>
> Three queues: `ingest` (cheap, high concurrency), `inference` (models, concurrency 1-2),
> and **`interactive`** for `POST /predict` and the `/model/status` probe, so a live request
> never queues behind a backlog of captures (ADR-026).

## Testing procedure
1. **Full E2E**: simulator uploads → within 10 s the image has a prediction, detections, and
   the project's `progress_pct` has changed.
2. Aggregator unit tests — the full list in [[Progress-Calculation]] §10 (ratchet, advance
   guard, low-confidence exclusion, two-camera average, ceiling, empty window).
3. Idempotency: run `recompute_window` 5× → identical snapshot, one row.
4. Low-confidence image → stored, flagged, excluded from the snapshot.
5. Rejected (blurred) image → `status='rejected'`, no prediction row, no progress change.
6. Detector raises → prediction still saved, `detections` empty, no task failure.
7. Reaching 80 % → `awaiting_inspection` + notification + remark, and progress does **not**
   exceed 80.
8. `POST /projects/{id}/approve` → exactly 100.00, `completed`, audited.
9. Latency benchmark: p50/p95 per image on CPU and GPU.
10. Replay: wipe snapshots, recompute all windows → the timeline is reproduced exactly.

## Expected output
```jsonc
GET /images/{id}
{ "stage": "Walls", "confidence": 0.96, "macro_stage": "framing",
  "raw_progress_pct": 40.0, "project_progress_pct": 38.5,
  "detections": [{"class_name":"wall","confidence":0.91,"bbox":[...]}],
  "counts": {"wall":4,"column":6,"worker":2}, "inference_ms": 210 }
```
Matching the original spec's `{"stage":"Walls","confidence":0.96,"progress":63}` shape, with
the project-level number now properly distinguished from the per-image one.

## Done criteria
- [x] End-to-end: upload → prediction → detections → snapshot → updated project
- [x] Aggregator is pure, fully unit-tested, and matches the worked example in [[Progress-Calculation]]
- [x] Models loaded once per worker; latency within the NFR (~25 ms/image on CPU with stubs)
- [x] Idempotent, replayable recomputation
- [x] 80 % ceiling and approval flow enforced
- [x] `/model/status` and `/predict` live

## Delivered (2026-08-14)

Two sessions. The first landed everything that does not need a checkpoint — the pure
aggregator, the stub models, the Celery worker, and `recompute`. The second landed the HTTP
surface and ran the whole thing against live services.

**Endpoints**

| Method | Path |
|---|---|
| GET | `/projects/{id}/images/{image_id}` · `…/prediction` |
| POST | `/projects/{id}/images/{image_id}/reprocess` |
| GET | `/projects/{id}/history` · `…/progress` · `…/timeline` |
| POST | `/projects/{id}/recompute` |
| GET | `/model/status` · `/models` |
| POST | `/predict` |

**Verified end to end** against PostgreSQL + Redis + MinIO + a live worker, 39/39 checks:
pair a simulated camera → 4 geotagged uploads → all 4 scored → progress **27.0 %**, macro
stage `framing`, one snapshot → recompute idempotent (same value, no duplicate rows) →
`/model/status` reporting a reachable worker on `cpu` at 25 ms mean → `POST /predict`
answering in a 73 ms round trip and storing nothing → reprocess clearing and re-scoring one
image without duplicating its row.

**Not built here** (deliberately, and recorded in [[API-Contract]]): `POST /projects/{id}/images`
(manual upload), `GET /projects/{id}/images` (superseded for now by `/history`), and
`DELETE /images/{id}`. All are Module 04/12 surface rather than inference.

**New decisions:** ADR-026 (`/predict` as a worker round trip on its own queue), ADR-027
(image routes nested under their project), ADR-028 (`progress:recompute` permission),
ADR-029 (the worker's engine is unpooled).

## Related
[[Progress-Calculation]] · [[Construction-Stages]] · [[Module-07-Classifier-Training]] · [[Module-10-Reports-and-Remarks]] · [[Module-14-Realtime]]
