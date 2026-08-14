---
title: API Contract
type: api
status: canonical
version: v1
updated: 2026-08-14
---

# REST API Contract — `/api/v1`

Conventions: JSON `snake_case` · UTC ISO-8601 timestamps · cursor pagination
(`?limit=&cursor=`) · errors as
`{"error":{"code":"PROJECT_CODE_TAKEN","message":"...","details":{...}}}` ·
auth via `Authorization: Bearer <access_jwt>` unless noted.

Original spec endpoints (`/upload`, `/predict`, `/history`, `/projects`, `/reports`,
`/model/status`) are all present — namespaced and expanded. Mapping table at the bottom.

---

## Public (no auth) — `/public/*`

| Method | Path | Purpose |
|---|---|---|
| GET | `/public/feed` | Homepage feed of public projects. Returns `project_code, name, intended_use, location_label, lat, lon, progress_pct, macro_stage, status, latest_image{thumb_url, captured_at, lat, lon}, owner{username, display_name, is_public}`. Filters: `?near=lat,lon&radius_km=&stage=&q=&sort=recent\|progress`. |
| GET | `/public/projects/{project_code}` | Public project folder: everything the owner marked public — progress, per-stage %, deadline, status, handler, public remarks, recent geotagged images, `map_url`. |
| GET | `/public/projects/{project_code}/timeline` | Snapshot series for the graph: `[{window_start, displayed_pct, macro_stage}]`. `?from=&to=&granularity=daily\|weekly`. |
| GET | `/public/projects/{project_code}/images` | Public image feed (thumbs + GPS + timestamp), paginated. |
| GET | `/public/users/{username}` | Public profile, or `{"username": "...", "is_private": true}` with no other fields. |
| GET | `/public/search` | Unified search. `?q=&type=user\|project\|location&limit=`. Returns typed results. Rate-limited. |
| POST | `/public/contact` | Contact Us. Body `{name, email, subject, message}` + captcha token. Rate-limited. |

404 (not 403) for private resources — do not leak existence.

## Auth — `/auth/*`

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | `{username, email, password, full_name, professional_role, company?}` → user + tokens |
| POST | `/auth/login` | `{identifier, password}` (username **or** email) |
| POST | `/auth/refresh` | rotating refresh token |
| POST | `/auth/logout` | revokes refresh family |
| GET | `/auth/me` | current user |
| POST | `/auth/check-username` | availability, used live on the register form |

## Users — `/users/*`

| Method | Path | Notes |
|---|---|---|
| GET | `/users/me` | full private profile incl. private projects |
| PATCH | `/users/me` | `{full_name?, company?, bio?, professional_role?, profile_visibility?}` |
| POST | `/users/me/avatar` | multipart |
| GET | `/users/me/projects` | owned + member projects, with `status` and `progress_pct` |
| GET | `/users/me/notifications` · POST `/users/me/notifications/{id}/read` | |

## Projects — `/projects/*`

| Method | Path | Notes |
|---|---|---|
| POST | `/projects` | **Create Project** form: `{name, intended_use?, location_label, latitude, longitude, code_initials, project_number, start_date, deadline_date, worker_count?, visibility, timezone?}` → 201. `409 PROJECT_CODE_TAKEN` with `details.suggestions`. |
| GET | `/projects` | caller's projects; `?status=&role=&q=` |
| GET | `/projects/{id}` | full folder payload (see below) |
| PATCH | `/projects/{id}` | editable fields (`project_code` **immutable**) |
| PATCH | `/projects/{id}/visibility` | owner only |
| POST | `/projects/{id}/approve` | **the final 20 %** — `{inspection_notes, photo_ids?}`; requires `project:approve`; 409 unless `approval_state='awaiting_inspection'` |
| POST | `/projects/{id}/archive` · DELETE `/projects/{id}` | owner only |
| GET | `/projects/{id}/timeline` | full snapshot series: `{points[{window_start, window_end, displayed_pct, raw_pct, ema_pct, macro_stage, eligible_image_count, devices_reporting, algorithm_version}], algorithm_version}`. `?from=&to=`. Windows with no captures are **absent**, never carried forward — the chart must draw the gap |
| GET | `/projects/{id}/progress` | current `{displayed_pct, macro_stage, stages{foundation_pct,framing_pct,roofing_pct,finishing_pct,approval_pct}, updated_at, algorithm_version, eligible_image_count, devices_reporting, has_data}` |
| POST | `/projects/{id}/recompute` | manual re-aggregation; requires `progress:recompute` (manager+). Enqueues, returns **202**. `?window=` for one window. Idempotent |

> **`has_data`** distinguishes "nothing has been measured" from "measured 0 %". A project with
> no captures reports `displayed_pct: 0.0` because that is its stored value, and without the
> flag a dashboard cannot tell that apart from a site where work genuinely has not started.
> Every figure here is **read from a stored snapshot**, never recomputed on the way out, so
> the dashboard, the PDF report, and the thesis appendix render one row rather than three
> live recalculations that can disagree.

`GET /projects/{id}` returns: project fields · `progress` · `stages[]` · `deadline_date` ·
`status` · `devices[]` · `members[]` · `recent_images[]` (with GPS + timestamps) ·
`remarks[]` · `assets[]` · `latest_report`.

## Members (collaboration, B.6) — `/projects/{id}/members`

| Method | Path | Notes |
|---|---|---|
| GET | `/projects/{id}/members` | |
| POST | `/projects/{id}/members` | `{username\|email, membership_role}` → invite (`pending`) |
| PATCH | `/projects/{id}/members/{user_id}` | change role |
| DELETE | `/projects/{id}/members/{user_id}` | remove |
| POST | `/invitations/{id}/accept` · `/invitations/{id}/decline` | invitee acts |

## Devices & Pairing — `/projects/{id}/devices`, `/devices/*`

| Method | Path | Notes |
|---|---|---|
| POST | `/projects/{id}/pairing-tokens` | `{face}` → `{display_code, qr_png_base64, provisioning_payload, expires_at}`. 15-min TTL, single use. |
| GET | `/projects/{id}/devices` | device panel: name, face, status, last_seen, battery, rssi, image count, weight |
| PATCH | `/projects/{id}/devices/{device_id}` | `{weight?, capture_times?, timezone?, jitter_seconds?, enabled?, homography?, roi_polygon?}` |
| POST | `/projects/{id}/devices/{device_id}/unpair` | revokes the secret; device must re-pair. **Its images are kept.** |
| GET | `/projects/{id}/devices/{device_id}/events` | health timeline — *not yet implemented; Module 12 needs it* |

> Device management routes are nested under the project rather than sitting at `/devices/{id}`.
> The permission guard resolves authority from `(caller, project)`, so a project-less path
> would have to look the project up first just to decide whether the caller may see that the
> device exists — and a 403-vs-404 slip there leaks the existence of other people's hardware.

## Device-facing ingest (HMAC auth, **not** JWT) — `/ingest/*`

| Method | Path | Notes |
|---|---|---|
| POST | `/pair/claim` | `{display_code, hardware_id, firmware_version}` → `{device_id, device_secret, device_name, project_code, capture_schedule}`. Secret returned **once**. |
| POST | `/ingest/images` | multipart: `file` + `meta` JSON `{captured_at, latitude, longitude, gps_accuracy_m, altitude_m, satellites, seq_hint, sha256, battery_mv, rssi_dbm}`. Idempotent on **`(project_id, sha256)`**. → `201 {image_id, filename, accepted, duplicate, server_time}` |
| POST | `/ingest/events` | boot / heartbeat / error / sleep |
| GET | `/ingest/config` | current schedule + server time (for RTC drift correction) + upload limits |

Headers: `X-Device-Id`, `X-Timestamp`, `X-Nonce`, `X-Signature` — see
[[Device-Pairing-Protocol]].

> **Idempotency narrowed to `(project_id, sha256)`** (2026-08-14). The original key included
> `device_id` and `captured_at`. Both weaken it: a camera retrying after a lost ACK may
> re-stamp `captured_at`, and the same bytes arriving from a re-paired device — new
> `device_id`, same hardware — is still the same photograph. Content-addressing by project is
> the honest identity of a capture. Sensor noise and JPEG encoding make two genuinely
> different frames byte-identical only if nothing moved *and* nothing was re-encoded, which
> does not happen on a real sensor.
>
> A duplicate returns `201` with `duplicate: true` rather than `200`: the capture is stored
> and the outcome from the camera's point of view is identical, and firmware that branches on
> the status code is firmware that can get the two paths wrong.

## Images & Assets

| Method | Path | Notes |
|---|---|---|
| POST | `/projects/{id}/images` | manual upload (multipart) — the original `/upload`. *Not yet implemented.* |
| GET | `/projects/{id}/images` | `?from=&to=&device_id=&face=&status=&limit=&cursor=`. *Not yet implemented — use `/history`, which returns the same rows joined to their predictions.* |
| GET | `/projects/{id}/images/{image_id}` | image + prediction + detections + signed URLs |
| DELETE | `/projects/{id}/images/{image_id}` | editor+; triggers recompute. *Not yet implemented.* |
| POST | `/projects/{id}/images/{image_id}/reprocess` | re-run AI; requires `progress:recompute` (manager+). Clears the stored prediction and detections, resets to `pending`, returns **202** |
| POST | `/projects/{id}/assets` | blueprint / 3D render / reference upload |
| GET | `/projects/{id}/assets` · DELETE `/assets/{id}` | |

> **Image routes are nested under their project** (2026-08-14, ADR-027), replacing the
> original top-level `/images/{id}`. Same reasoning as the device routes above: the permission
> guard resolves authority from `(caller, project)`, so a project-less path would have to look
> the image up before deciding whether the caller may know it exists — and a 403 where a 404
> belonged discloses other people's capture history. An image id belonging to a different
> project returns **404**, indistinguishable from one that does not exist.

## Predictions

| Method | Path | Notes |
|---|---|---|
| POST | `/predict` | ad-hoc inference on an uploaded image, **no persistence** — for demos/defense. Multipart `file`. Returns `{rejected, persisted:false, stage, confidence, macro_stage, progress, probabilities{}, detections[], counts{}, quality{}, preprocessing_ms, inference_ms, total_ms, model_name, model_version, model_is_stub, preprocessing_fingerprint}`. Authenticated + rate-limited (10/min). **503** when no worker answers |
| GET | `/projects/{id}/images/{image_id}/prediction` | stored prediction. **404** if the image has not been scored yet, with `details.image_status` |
| GET | `/projects/{id}/history` | the original `/history`: images + predictions joined, chronological, cursor-paginated. Filters `?from=&to=&device_id=&status=&limit=&cursor=`. Rows with no prediction are **included** with null stage fields |

> `POST /predict` is a **synchronous round trip to the worker** (ADR-026): the API process may
> never import torch (ADR-011), so it publishes a task on a dedicated `interactive` queue and
> waits, bounded by `GV_PREDICT_TIMEOUT_SECONDS`. A rejected frame is a **200** carrying
> `rejected: true`, not an error — the quality gate firing is the answer, not a failure to
> answer. `persisted: false` is always present so a demo cannot be mistaken for stored data.

## Remarks

`GET|POST /projects/{id}/remarks` · `PATCH|DELETE /remarks/{id}`
Body: `{message, remark_type, severity, is_public, effective_from?, effective_to?}`

## Reports

| Method | Path | Notes |
|---|---|---|
| POST | `/projects/{id}/reports` | `{kind: weekly\|monthly\|custom, format: pdf\|csv, period_start?, period_end?}` → `202 {report_id, status:"queued"}` |
| GET | `/projects/{id}/reports` | list |
| GET | `/reports/{id}` | status |
| GET | `/reports/{id}/download` | signed URL / streamed file |

## Models & System

| Method | Path | Notes |
|---|---|---|
| GET | `/model/status` | registry reconciled with a live worker probe: `{worker_reachable, using_stubs, classifier, detector, live_classifier, live_detector, preprocessing_fingerprint, preprocessing_matches, loaded_at, mean_latency_ms, images_processed, queue_depth{}}`. Any authenticated user |
| GET | `/models` | all registered models (thesis comparison table: ResNet18 vs MobileNetV3 vs YOLOv8). Stubs included, flagged `is_stub` |

> `/model/status` reads **two sources that can legitimately disagree**: PostgreSQL knows what
> was trained and how it scored; the worker knows what is in memory now, on which device, and
> how long recent images took. It **always returns 200** — when no worker answers,
> `worker_reachable: false` and the live fields are null. An endpoint whose purpose is
> observing health must not fail when things are unhealthy.
>
> Two fields carry weight. `using_stubs` is true while placeholder models are answering, so a
> demo can never be mistaken for a trained result. `preprocessing_matches: false` means the
> running pipeline is no longer the one the weights were trained through (ADR-025) —
> predictions continue and are quietly worse than the reported metrics claim. `null` there
> means the loaded model carries no fingerprint (a stub, or a pre-Module-07 checkpoint);
> unknown and mismatched are deliberately different answers.
| GET | `/health` · `/health/ready` | liveness / readiness |
| GET | `/metrics` | Prometheus (optional) |

---

## Original-spec endpoint mapping

| Original | Now |
|---|---|
| `POST /upload` | `POST /projects/{id}/images` (manual) + `POST /ingest/images` (device) |
| `POST /predict` | `POST /predict` (stateless demo path, worker round trip - ADR-026) |
| `GET /history` | `GET /projects/{id}/history` |
| `GET /projects` | `GET /projects` + `GET /public/feed` |
| `GET /reports` | `GET /projects/{id}/reports` |
| `GET /model/status` | `GET /model/status` |

## Status codes

`200` ok · `201` created · `202` accepted (async) · `204` deleted · `400` validation ·
`401` unauthenticated · `403` authenticated but not permitted · `404` not found **or hidden
by visibility** · `409` conflict (code taken, already approved, token used) ·
`413` payload too large · `422` Pydantic · `429` rate limited · `500`.

## Related
[[Realtime-Events]] · [[Domain-Model]] · [[Roles-and-Permissions]] · [[Device-Pairing-Protocol]]
