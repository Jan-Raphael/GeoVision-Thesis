---
title: Realtime Events (WebSocket)
type: api
status: canonical
updated: 2026-08-12
---

# Realtime — WebSocket ⚖

## Why WebSocket is used *here* and not for the upload (ADR-003)

The professor's requirement: *"the owner shouldn't have to refresh every time just to
upload the images."* Two separate problems are hiding in that sentence:

1. **The device must upload without human action.** Solved by the ESP32 firmware itself —
   scheduled wake, capture, auto-upload, retry from microSD. No refresh, no button.
   Transport: **HTTPS multipart POST**, because on an ESP32 with ~200 KB usable heap, a
   deep-sleep duty cycle, and lossy site Wi-Fi, a plain stateless POST is dramatically more
   robust than holding a WebSocket: it gets a definitive per-image ACK, works through
   proxies/captive portals, retries trivially, and doesn't burn power keeping a socket open.
2. **The dashboard must update without the owner pressing F5.** *This* is what WebSocket is
   for: server → browser push.

Both halves are delivered. This distinction is worth stating explicitly in the defense —
it shows the transport choice was reasoned, not accidental.

An **optional** device control channel over WebSocket is specified below for future
remote-trigger ("capture now") support; it is not required for v1.

---

## Endpoint

```
WSS /api/v1/ws?token=<access_jwt>
```

JWT in the query string (browsers cannot set headers on `WebSocket`); the token is
short-lived and the connection is upgraded only after validation. On connect the server
sends `connection.ready` with the list of project IDs the user may subscribe to.

### Client → server

```jsonc
{"type": "subscribe",   "payload": {"project_ids": ["<uuid>", "..."]}}
{"type": "unsubscribe", "payload": {"project_ids": ["<uuid>"]}}
{"type": "ping"}
```

Subscription is **authorized per project** against `project_members`; a subscribe to a
project the user cannot view is silently dropped (and audit-logged).

### Server → client

Envelope:

```jsonc
{
  "type": "project.progress.updated",
  "project_id": "…",
  "ts": "2026-08-12T07:00:12Z",
  "payload": { }
}
```

| Event | Payload | Fires when |
|---|---|---|
| `connection.ready` | `{user_id, subscribable_project_ids}` | on connect |
| `image.received` | `{image_id, filename, thumb_url, captured_at, device_name, lat, lon}` | ingest accepted (before AI) |
| `image.processing` | `{image_id, step}` | preprocessing / classifying / detecting |
| `prediction.completed` | `{image_id, stage, confidence, macro_stage, raw_progress_pct, low_confidence, detections_summary}` | inference done |
| `image.rejected` | `{image_id, reason}` | quality gate rejected |
| `project.progress.updated` | `{displayed_pct, macro_stage, stages{…}, window_start}` | after aggregation |
| `project.status.changed` | `{old, new}` | status derivation changed |
| `project.approval.required` | `{progress_pct}` | reached 80 % |
| `project.approved` | `{approved_by, approved_at, progress_pct: 100}` | owner signed off |
| `device.status.changed` | `{device_id, device_name, status, last_seen_at, battery_mv}` | heartbeat/offline sweep |
| `device.paired` | `{device_id, device_name, face}` | pairing claimed — **the pairing modal closes on this** |
| `remark.created` | `{remark_id, type, severity, message}` | system or user remark |
| `report.ready` | `{report_id, kind, format, download_url}` | report job finished |
| `notification.created` | `{notification_id, type, title, body}` | any notification |

## Fan-out architecture

Multiple Uvicorn workers each hold their own sockets, so events go through **Redis pub/sub**:

```
Celery worker ──publish──> redis channel "project:{id}" ──> every API process
                                                              └─> local connection hub
                                                                    └─> subscribed sockets
```

`infrastructure/realtime/hub.py` owns `connections: dict[project_id, set[WebSocket]]` and a
background Redis subscriber task started in the FastAPI lifespan.

## Client behaviour (`dashboard/src/lib/ws.ts`)

- Reconnect with exponential backoff (1 s → 30 s) + jitter; re-subscribe on reconnect.
- Heartbeat `ping` every 25 s; server replies `pong`; drop and reconnect after 2 misses.
- On every event, patch the TanStack Query cache (`setQueryData`) — never trigger a full
  refetch storm.
- **Fallback:** if the socket is down, TanStack Query polls `/projects/{id}` every 60 s.
  The dashboard must remain correct with WebSocket entirely disabled — WS is an
  optimization, never the only path to truth.

## Optional device control channel (post-v1)

```
WSS /api/v1/ws/device   (HMAC handshake frame instead of JWT)
```
Server → device: `capture.now`, `config.updated`, `ota.available`.
Only meaningful for a mains-powered node — a deep-sleeping battery node is unreachable
between wakes by design. Documented in [[Open-Questions]].

## Related
[[API-Contract]] · [[ESP32-CAM-Node]] · [[Module-14-Realtime]] · [[ADR-Index]]
