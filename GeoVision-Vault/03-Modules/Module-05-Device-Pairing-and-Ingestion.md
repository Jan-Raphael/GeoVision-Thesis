---
title: Module 05 — Device Pairing & Image Ingestion
type: module
module: 5
status: planned
updated: 2026-08-12
---

# Module 05 — Device Pairing & Image Ingestion

## Scope
Spec **B.2** end to end, server side: pairing token + QR, HMAC device auth, image ingest,
server-side naming, storage, idempotency, device health. Plus the device simulator, so
everything downstream is testable without hardware.

## Deliverables
- `application/use_cases/devices/` — `IssuePairingToken`, `ClaimPairingToken`,
  `ListProjectDevices`, `UpdateDeviceSettings`, `UnpairDevice`, `RecordDeviceEvent`.
- `application/use_cases/ingest/` — `IngestImage` (the critical path), `GetDeviceConfig`.
- `core/device_auth.py` — canonical-string builder, HMAC verify, replay-nonce cache (Redis),
  clock-skew window. Implements [[Device-Pairing-Protocol]] exactly.
- `api/deps.py` — `get_current_device` dependency (401 on any failure, generic message).
- `domain/services/image_naming.py` — pure: `(project_code, captured_at, seq) -> filename`
  and the storage key builder. Fully unit-tested ([[Naming-Conventions]]).
- `infrastructure/qr.py` — QR PNG of the provisioning payload, base64-encoded.
- Routers: `pairing.py` (`/projects/{id}/pairing-tokens`, `/pair/claim`), `ingest.py`,
  `devices.py`.
- `scripts/simulate_device.py` — **build this first**; it is how the rest of the project gets
  tested. Flags: `--images DIR --project-code NG_00 --face FD --interval --jitter-gps
  --fail-rate --replay --bad-signature --clock-skew`.

## Ingest algorithm (`POST /ingest/images`)
```
1. verify HMAC (device_auth) ......................... 401 on failure
2. load device → must be paired/online, not revoked
3. parse multipart: file + meta json
4. verify sha256(file) == meta.sha256 ................ 400 on mismatch
5. idempotency: (project_id, sha256) exists? ......... 200 {duplicate:true}, no reprocess
6. validate: JPEG magic bytes, ≤ 8 MB, decodable, min 320×240
7. seq = next daily sequence for (project, utc_date)   -- advisory-locked, no races
8. filename = <CODE>_<captured_at>_<seq>.jpg
9. put original → object store
10. INSERT images (status='pending') + UPDATE devices.last_seen/battery/rssi
11. INSERT device_events('upload')
12. enqueue inference.process_image(image_id)         -- Module 09 consumes it
13. publish WS image.received                          -- Module 14
14. 201 {image_id, filename, accepted:true, server_time}
```
Steps 9–11 run in **one transaction**; the object-store write precedes the DB insert so a
crash leaves an orphan blob (harmless, GC'd) rather than a DB row pointing at nothing.

## Critical implementation notes
- **The device never chooses its project or filename.** `device_id` → project. `seq_hint` is
  advisory only.
- Daily sequence assignment must be race-free: `SELECT ... FOR UPDATE` on a per-project
  counter row, or a Postgres advisory lock keyed on `(project_id, utc_date)`.
- `captured_at` comes from the **device**, `uploaded_at` from the server; backlog uploads
  keep their original capture time (windowing depends on it — [[Progress-Calculation]]).
- Reject `captured_at` more than 24 h in the future (clock corruption).
- Nonce cache TTL = the skew window (300 s), keyed `nonce:{device_id}:{nonce}`.
- Pairing token: hash-at-rest, 15-min TTL, single use, brute-force rate-limited.
- `device_secret` returned exactly once, never logged, never retrievable.
- Unpair keeps historical images (progress history must not be rewritten by a hardware swap).
- Return `413` for oversize uploads with a clear message the firmware can act on.

## Dependencies
Module 04. `qrcode[pil]`, `redis`, `python-multipart`.

## How to run
```bash
# 1. as an owner, issue a token
http POST :8000/api/v1/projects/$PID/pairing-tokens face=front_diagonal "Authorization:Bearer $TOK"
# 2. pretend to be a camera
python scripts/simulate_device.py --code K7M29XQF --images ./sample_images --interval 5
```

## Testing procedure
1. Issue token → code + QR + expiry; second token for the same face → 409.
2. Claim with a valid code → device created, named `ESP_NG_00_FD`, secret returned once.
3. Claim the same code twice → 409; expired code → 400; wrong code → 400 (+ rate limit after 5).
4. Signed upload → 201, correct filename, blob present in MinIO, row in `images`.
5. Tampered body / replayed nonce / 10-min clock skew / revoked device → 401 each.
6. Duplicate upload (same sha256) → 200 `duplicate:true`, exactly one DB row.
7. Cross-project injection: device A signs an upload aimed at project B → lands in A (or 401),
   never in B.
8. 20 concurrent uploads in one day → sequence numbers `001..020`, no duplicates, no gaps.
9. Unpair → subsequent upload 401; existing images intact.
10. Naming unit tests: midnight boundaries, UTC vs local, sequence rollover.

## Expected output
`simulate_device.py` runs for a few minutes and the project folder fills with correctly named,
geotagged, stored images — with no hardware present.

## Done criteria
- [ ] Pairing token + QR + claim + unpair
- [ ] HMAC auth with replay and skew protection, all failure tests passing
- [ ] Ingest with server-side naming, idempotency, race-free sequencing
- [ ] Device health events, battery, RSSI, last-seen
- [ ] Simulator can drive the whole pipeline

## Related
[[Device-Pairing-Protocol]] · [[Naming-Conventions]] · [[ESP32-CAM-Node]] · [[Module-09-Inference-Service]]
