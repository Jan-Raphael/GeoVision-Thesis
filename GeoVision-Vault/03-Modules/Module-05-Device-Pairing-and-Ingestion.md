---
title: Module 05 — Device Pairing & Image Ingestion
type: module
module: 5
status: done
updated: 2026-08-14
---

# Module 05 — Device Pairing & Image Ingestion

## Scope
Spec **B.2** end to end, server side: pairing token + QR, HMAC device auth, image ingest,
server-side naming, storage, idempotency, device health. Plus the device simulator, so
everything downstream is testable without hardware.

**Status: done.** 509 tests pass; the simulator drives the whole pipeline against live
PostgreSQL, Redis, and MinIO with no hardware present.

## What shipped

| File | Purpose |
|---|---|
| `core/device_auth.py` | Canonical string, HMAC verify, secret encryption, pairing codes |
| `infrastructure/cache.py` | `RedisNonceCache` + `InMemoryNonceCache` ([[ADR-Index\|ADR-021]]) |
| `application/ports/task_queue.py` | `TaskQueue` port; logging stub until Module 09 |
| `domain/services/image_naming.py` | Pure filename + storage-key builders |
| `application/use_cases/devices.py` | Issue / claim / update / unpair / record event |
| `application/use_cases/ingest.py` | `IngestImage` (the critical path), `GetDeviceConfig` |
| `api/deps.py` | `get_current_device` — 401 on any failure, generic message |
| `api/v1/routers/devices.py`, `ingest.py` | The endpoints |
| `infrastructure/qr.py` | Provisioning QR, base64 PNG |
| `alembic/…_m05_device_secret_encrypted.py` | `secret_hash` → `secret_encrypted` |
| `scripts/simulate_device.py` | The camera stand-in, with failure injection |

## Ingest algorithm (`POST /ingest/images`)
```
1. verify HMAC (device_auth) ......................... 401 on failure
2. load device → must be paired/online, not revoked ... 403 DEVICE_REVOKED
3. parse multipart: file + meta json
4. verify sha256(file) == meta.sha256 ................ 400 HASH_MISMATCH
5. validate: JPEG magic bytes, ≤ 8 MB, decodable, min 320×240
6. validate captured_at ≤ now + 24 h ................. 400 CLOCK_IMPLAUSIBLE
7. idempotency: (project_id, sha256) exists? ......... 201 {duplicate:true}, no reprocess
8. seq = next daily sequence for (project, utc_date)   -- advisory-locked, no races
9. filename = <CODE>_<captured_at>_<seq>.jpg
10. put original → object store
11. INSERT images (status='pending') + UPDATE devices.last_seen/battery/rssi
12. enqueue inference.process_image(image_id)         -- Module 09 consumes it
13. publish WS image.received                          -- Module 14 (not yet wired)
14. 201 {image_id, filename, accepted:true, server_time}
```

Two orderings here are load-bearing and were chosen deliberately:

- **Idempotency (7) comes before any work.** A camera whose ACK was lost re-sends identical
  bytes. That must cost one indexed lookup — not a storage write, a sequence number, and a
  second inference job. It also means a duplicate does **not** consume a sequence number, so
  a flaky link cannot punch gaps in the day's numbering.
- **Storage (10) precedes the DB insert (11).** A crash between them leaves an orphan blob:
  wasted bytes, garbage-collectable, invisible to users. The reverse leaves a row pointing at
  nothing, which breaks the gallery and the report.

## Critical implementation notes
- **The device never chooses its project or filename.** `device_id` → project. `seq_hint` is
  advisory only. There is no project field in the request to tamper with — the isolation is
  structural, not a check that could be forgotten.
- Daily sequence allocation uses a Postgres advisory lock keyed on `(project_id, utc_date)`,
  with a **stable** BLAKE2b key — see [[ADR-Index|ADR-022]] for why `hash()` was wrong.
- `captured_at` comes from the **device**, `uploaded_at` from the server. The past is
  deliberately unbounded (a camera offline three days uploads its backlog into the days the
  photos were *taken*, which is what the progress windows key on —
  [[Progress-Calculation]]); only the future is capped, at 24 h.
- `_touch_project` only ever moves `last_capture_at` **forward**, so a backlog upload cannot
  make a project look staler than it is and misfire the inactivity rule
  ([[Project-Status-Rules]]).
- Nonce cache TTL = the skew window (300 s), keyed `nonce:{device_id}:{nonce}`.
- Pairing token: hash-at-rest, 15-min TTL, single use, brute-force rate-limited (10/min).
- Pairing codes use Crockford base32 **without I, L, O, U** — the characters people mistype
  reading a code off a screen. Input is normalised for case and hyphens.
- `device_secret` returned exactly once, never logged, never retrievable. Stored
  **encrypted, not hashed** — [[ADR-Index|ADR-020]].
- Unpair keeps historical images (progress history must not be rewritten by a hardware swap).
- Return `413` for oversize uploads with the limit in the body, so the firmware can lower its
  JPEG quality rather than retry the same frame until the battery dies.

## Dependencies
Module 04. `qrcode[pil]`, `redis`, `python-multipart`, `cryptography` (Fernet).

## How to run
```bash
# 0. bring up Redis + MinIO (Postgres runs natively on 5433)
.\dev.ps1 up

# 1. start the API. Set GV_JWT_SECRET_KEY explicitly — see the note below.
uv run uvicorn app.main:app

# 2. as an owner, issue a pairing code
http POST :8000/api/v1/projects/$PID/pairing-tokens face=front_diagonal "Authorization:Bearer $TOK"

# 3. pretend to be a camera
uv run python -m scripts.simulate_device --code K7M2-9XQF --images ./samples --interval 5

# 4. exercise the rejection paths
uv run python -m scripts.simulate_device --bad-signature   # -> 401
uv run python -m scripts.simulate_device --replay          # -> 401
uv run python -m scripts.simulate_device --clock-skew 900  # -> 401
uv run python -m scripts.simulate_device --tamper          # -> 401
```

> **Set `GV_JWT_SECRET_KEY` when running uvicorn locally.** Left empty, the key is generated
> per *Settings instance*, and uvicorn's Windows launcher imports the app in more than one
> process — so tokens get signed with one key and verified with another. Every authenticated
> request returns `401 Invalid or expired token`, which looks exactly like a bug in the auth
> code and is not. Cost an afternoon; documented in `.env.example`.

## Testing procedure — results

| # | Check | Result |
|---|---|---|
| 1 | Issue token → code + QR + expiry; second token, same face → 409 | pass |
| 2 | Claim valid code → `ESP_SM_07_FD` created, secret returned once | pass |
| 3 | Claim twice → 409; unknown code → 400 | pass |
| 4 | Signed upload → 201, correct filename, blob in MinIO, row in `images` | pass |
| 5 | Tampered body / replayed nonce / clock skew / bad signature / revoked | 401 each |
| 6 | Duplicate upload (same sha256) → `duplicate:true`, one row, no seq consumed | pass |
| 7 | Cross-project injection — the request carries no project at all | pass |
| 8 | 20 concurrent uploads in one day → `001..020`, no duplicates, no gaps | pass |
| 9 | Unpair → subsequent upload 401; existing images intact | pass |
| 10 | Naming units: UTC conversion, midnight boundaries, sequence rollover | pass |

Test files: `tests/unit/test_device_auth.py` (38), `tests/unit/test_image_naming.py` (13),
`tests/integration/test_ingest_api.py` (36), `tests/integration/test_sequence_allocation.py` (7).

The concurrency test lives in its own file on purpose. The shared integration `session`
fixture puts every request in **one** transaction, and an advisory lock taken twice in the
same transaction is reentrant — a concurrency test run through that fixture would pass
whether or not the lock existed. It opens genuinely independent connections instead, and
additionally asks `pg_locks` directly whether the lock is held, so a green result cannot
just mean "the work finished too fast to overlap".

## Expected output — actual
```
paired as ESP_SM_07_FD on project SM_07
  config: capture at 07:00, 16:00 (Asia/Manila), clock drift 0.1s
  capture_01.jpg -> SM_07_20260814T014405Z_001.jpg
  capture_02.jpg -> SM_07_20260814T014407Z_002.jpg
  capture_03.jpg -> SM_07_20260814T014408Z_003.jpg
  capture_04.jpg -> SM_07_20260814T014409Z_004.jpg
  capture_01.jpg -> SM_07_20260814T014405Z_001.jpg (duplicate)
  heartbeat ok
6/6 accepted
```
Objects in MinIO under
`projects/{id}/images/2026/08/14/front_diagonal/SM_07_…_001.jpg`; nonces in Redis with a
273 s TTL; the owner's folder shows four geotagged captures and
`ESP_SM_07_FD status=online battery=3615mV rssi=-61dBm`.

## Done criteria
- [x] Pairing token + QR + claim + unpair
- [x] HMAC auth with replay and skew protection, all failure tests passing
- [x] Ingest with server-side naming, idempotency, race-free sequencing
- [x] Device health events, battery, RSSI, last-seen
- [x] Simulator can drive the whole pipeline

## Handoffs
- **Module 09** consumes `inference.process_image` from the `TaskQueue` port. Until its
  worker exists the queue is a logging stub, and that loses nothing: `images.status =
  'pending'` is the durable backlog, so work queued today is still there when the worker
  arrives.
- **Module 13 (firmware)** must reproduce the canonical string exactly. Verify mbedTLS
  against the fixed vector in `test_device_auth.py::test_signature_matches_an_independent_implementation`
  *before* attempting a real upload — debugging a signature mismatch through a full multipart
  request on a roof is miserable; against a fixed vector it takes minutes.
- **Module 14** publishes `image.received`; the hook is step 13 above.

## Related
[[Device-Pairing-Protocol]] · [[Naming-Conventions]] · [[ESP32-CAM-Node]] · [[Module-09-Inference-Service]]
