---
title: Device Pairing Protocol
type: hardware
status: canonical
updated: 2026-08-14
---

# Device Pairing & Authentication Protocol

Implements spec **B.2**: a token/code/QR shown in the project folder that permanently binds
an ESP32-CAM to that project folder, unpairable by the owner.

## Threat model

- Anyone can POST to `/ingest/images` — so the endpoint must prove *which* device sent it.
- Pairing codes are short (human-typeable) — so they must be **single-use, short-lived, and
  rate-limited**.
- A stolen/decommissioned camera must be revocable without touching the other devices.
- Nobody should be able to inject fake progress into someone else's project.

## Phase 1 — Owner issues a pairing token

`POST /projects/{id}/pairing-tokens  {"face": "front_diagonal"}` (requires `device:manage`)

Server:
1. Rejects if `(project_id, face)` already has an active device (409, unless `?replace=true`).
2. Generates `display_code` — **8 chars, Crockford base32** (no I/L/O/U), e.g. `K7M2-9XQF`.
3. Stores only `token_hash = sha256(display_code)`; TTL **15 minutes**; single use.
4. Returns:

```jsonc
{
  "display_code": "K7M2-9XQF",
  "expires_at": "2026-08-12T07:15:00Z",
  "qr_png_base64": "…",
  "provisioning_payload": {
    "v": 1,
    "server": "https://api.geovision.example",
    "code": "K7M29XQF",
    "project_code": "NG_00",
    "face": "FD",
    "device_name": "ESP_NG_00_FD"
  }
}
```

The QR encodes `provisioning_payload` as compact JSON so the technician can scan it from
the phone/laptop into the ESP32 captive portal instead of typing.

The modal shows: QR · the code in large text · a countdown · Wi-Fi setup instructions · and
it **stays open, waiting on the `device.paired` WebSocket event** ([[Realtime-Events]]).

## Phase 2 — Device claims the token

Device (once, unauthenticated except by possession of the code):

```
POST /api/v1/pair/claim
{"display_code":"K7M29XQF","hardware_id":"24:0A:C4:XX:XX:XX",
 "firmware_version":"1.0.0","chip":"ESP32-CAM-AITHINKER"}
```

Server, in a single transaction:
1. `token_hash` lookup → must exist, be unexpired, unused.
2. Create the `devices` row: `device_name = ESP_<project_code>_<FACE>`, default `weight`
   from the face table, default `capture_schedule` from the project.
3. Generate `device_secret` — 32 random bytes, base64url. **Store it encrypted**, in
   `devices.secret_encrypted` (Fernet, keyed on `GV_DEVICE_SECRET_KEY`) — see
   [[ADR-Index|ADR-020]].

   > **Corrected 2026-08-14.** This step previously said "store only its hash", which is
   > not implementable: Phase 3 computes `HMAC_SHA256(device_secret, …)` server-side, and
   > a MAC key must be **recoverable**, not one-way hashed. A hash would make every
   > signed request unverifiable. Encryption at rest gives the same protection against a
   > database dump — the ciphertext is useless without the key, which lives in the
   > environment — while keeping the key usable. Pairing *codes* are still hashed
   > (step 1); they are only ever compared, never used as a key.
4. Mark the token used, bind `hardware_id`, write an `audit_log` row, emit `device.paired`.
5. Respond **once** with the plaintext secret:

```jsonc
{ "device_id":"…", "device_secret":"…", "device_name":"ESP_NG_00_FD",
  "project_code":"NG_00", "face":"front_diagonal",
  "capture_schedule":{"times":["07:00","16:00"],"tz":"Asia/Manila"},
  "server_time":"2026-08-12T07:02:11Z" }
```

The device persists this to NVS. The secret is never retrievable again — losing it means
re-pairing. Rate limit: **5 claim attempts per IP per minute**, 10 per code lifetime.

## Phase 3 — Every subsequent request is HMAC-signed

Headers on all `/ingest/*` calls:

```
X-Device-Id:  <uuid>
X-Timestamp:  1786550400            # unix seconds
X-Nonce:      <16 random hex chars>
X-Signature:  <hex HMAC-SHA256>
```

Canonical string:

```
METHOD \n PATH \n X-Timestamp \n X-Nonce \n sha256_hex(body)
```

`X-Signature = HMAC_SHA256(device_secret, canonical_string)` (mbedTLS on-device).

Server verification, in order:
1. Device exists, `status != 'revoked'`, and its secret decrypts.
2. `|now - X-Timestamp| <= 300 s` (replay window; the DS3231 keeps this achievable).
   Checked before anything expensive — a wrong clock is the most common firmware fault.
3. Nonce unseen for this device within the window (Redis `SET … NX EX`, 300 s TTL,
   keyed `nonce:{device_id}:{nonce}` so two cameras cannot collide).
4. Body hash and signature, **in a single `hmac.compare_digest`**. The body hash is part
   of the canonical string, so a tampered payload already yields a different signature;
   comparing separately would add a non-constant-time check for no extra safety.

Failures → `401` with a generic message. Never reveal which check failed: naming the
failed check tells a forger exactly what to fix. The specific reason is logged
server-side, where an operator can see it and an attacker cannot.

The TTL equals the skew window on purpose. A replay arriving after the nonce expires
necessarily carries a timestamp more than 300 s old, so step 2 rejects it — the two
checks cover each other's edges.

## Phase 4 — Ingest resolves the project

The `device_id` determines the project. **The device never names its own project** — it
cannot write into a folder it isn't paired to. The filename is assigned server-side per
[[Naming-Conventions]]; the device's `seq_hint` is advisory only.

## Unpairing

`POST /devices/{id}/unpair` (requires `device:manage`) → `status='revoked'`,
`revoked_at=now()`, `secret_encrypted` wiped, audit-logged. Subsequent uploads get `401`; the
firmware sees `401 DEVICE_REVOKED`, clears NVS, and re-enters provisioning. Historical
images and predictions from that device are **retained** (progress history must not be
rewritten by a hardware swap).

## Multiple cameras

One device per `(project, face)`. Owner pairs up to 4 (`front`, `front_diagonal`, `back`,
`back_diagonal`). Their readings are fused by weighted mean — [[Progress-Calculation]].
`ESP_NG_00_FD2`-style second cameras on one face require `?force=true` and are documented
as out of default scope.

## Why not mTLS / JWT for devices?

- **mTLS**: correct but heavy — per-device certs, a CA, rotation, and more flash/heap than
  is comfortable on an ESP32. Documented as the production hardening path.
- **JWT**: needs refresh flows and asymmetric verification on a device that sleeps for hours;
  HMAC with a replay window is simpler, smaller, and adequate. Justify this trade-off in the
  thesis security section.

## Required tests

- valid signature → 201
- tampered body → 401
- replayed nonce → 401
- clock skew > 5 min → 401
- revoked device → 401
- expired / reused / wrong pairing code → 400/409
- device A cannot upload into project B (cross-project injection) → 401/403

## Related
[[ESP32-CAM-Node]] · [[API-Contract]] · [[Module-05-Device-Pairing-and-Ingestion]] · [[Naming-Conventions]]
