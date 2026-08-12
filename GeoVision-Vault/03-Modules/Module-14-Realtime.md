---
title: Module 14 — Realtime (WebSocket)
type: module
module: 14
status: planned
updated: 2026-08-12
---

# Module 14 — Realtime Updates

## Scope
Server → browser push so the dashboard updates without a refresh. Protocol spec in
[[Realtime-Events]] (including the ADR on why uploads are HTTP, not WebSocket).

## Deliverables
- `infrastructure/realtime/hub.py` — `ConnectionHub`: `connect`, `disconnect`,
  `subscribe(project_ids)`, `broadcast(project_id, event)`; holds
  `dict[project_id, set[WebSocket]]`.
- `infrastructure/realtime/publisher.py` — `publish(project_id, event)` → Redis
  `PUBLISH project:{id}`. Callable from **Celery workers**, which have no socket access.
- `infrastructure/realtime/subscriber.py` — a lifespan-managed background task per API
  process that consumes Redis and fans out to local sockets.
- `api/v1/routers/ws.py` — the `/ws` endpoint: JWT-from-query auth, subscription
  authorization against `project_members`, ping/pong, clean disconnect.
- `dashboard/src/lib/ws.ts` — reconnecting client (exponential backoff + jitter),
  re-subscribe on reconnect, heartbeat, typed event union.
- `dashboard/src/features/realtime/useRealtime.ts` — hook that patches the TanStack Query
  cache per event type.
- Toasts for `project.approval.required`, `report.ready`, `device.paired`,
  `device.status.changed`.

## Cache-patching map (client)
| Event | Cache effect |
|---|---|
| `image.received` | prepend to `['project', id, 'images']`, show "processing" badge |
| `prediction.completed` | patch that image's entry with stage + confidence |
| `project.progress.updated` | patch `['project', id]` progress + stages; append to timeline |
| `project.status.changed` | patch status badge |
| `device.paired` | invalidate devices; **close the pairing modal** |
| `device.status.changed` | patch that device row |
| `report.ready` | invalidate reports + toast with a download link |
| `remark.created` | prepend to remarks |
| `notification.created` | bump the bell counter |

## Critical implementation notes
- **Redis pub/sub is mandatory** the moment there is more than one Uvicorn worker — an
  in-process registry silently delivers events to only the worker that happens to hold the
  socket. Build it with Redis from the start.
- Authorize **every** subscription server-side. A user must not be able to subscribe to a
  project they cannot view; drop silently and audit-log the attempt.
- Never send private data over a socket that the REST layer wouldn't return to that user.
- The dashboard **must work with WebSocket disabled** — TanStack Query polls at 60 s as a
  fallback. WS is an optimization; correctness never depends on it. Test with the socket
  blocked.
- Clean up on disconnect (including abrupt closes) or the hub leaks sockets and memory.
- Cap events: coalesce `project.progress.updated` to at most one per project per 2 s.
- Tokens expire mid-connection: on `401`-equivalent closure, the client refreshes the access
  token and reconnects rather than dying silently.

## Dependencies
Modules 09, 12. `redis` (asyncio client).

## How to run
```bash
uvicorn app.main:app --reload --workers 1     # workers >1 requires the Redis path — test both
celery -A app.infrastructure.tasks.celery_app worker -Q ingest,inference -l info
cd dashboard && npm run dev
python scripts/simulate_device.py --code ... --interval 10
```

## Testing procedure
1. Open a project folder, run the simulator → the image, prediction, and progress appear
   **without a refresh**.
2. Two browsers on the same project → both update.
3. **Two Uvicorn workers** → both connected clients still receive events (proves the Redis
   fan-out; this is the test that catches the classic bug).
4. Subscribe to a project the user cannot view → no events delivered, audit row written.
5. Kill the network → the client backs off, reconnects, re-subscribes, and catches up via
   refetch.
6. Disable WebSocket entirely → the UI still updates within 60 s via polling.
7. Pairing modal closes on `device.paired`.
8. Load test: 50 concurrent sockets, 100 events → no leaked connections after all close.
9. Expired access token mid-connection → transparent refresh + reconnect.

## Expected output
The project folder becomes a live view: a capture arriving in the field shows up on screen
within seconds, progress animates upward, and the pairing modal confirms itself. This is the
demo moment of the defense.

## Done criteria
- [ ] WS endpoint with authenticated, authorized subscriptions
- [ ] Redis fan-out verified with multiple workers
- [ ] All events from [[Realtime-Events]] emitted and consumed
- [ ] Reconnection, heartbeat, and token-refresh handled
- [ ] Polling fallback proven to keep the UI correct without WS

## Related
[[Realtime-Events]] · [[Module-09-Inference-Service]] · [[Module-12-Owner-Dashboard]]
