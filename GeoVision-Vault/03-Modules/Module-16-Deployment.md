---
title: Module 16 — Deployment & Documentation
type: module
module: 16
status: planned
updated: 2026-08-12
---

# Module 16 — Dockerization, Deployment & Handover

## Scope
One-command bring-up, deployment notes, operational runbook, and the defense demo script.

## Deliverables
- `docker/backend.Dockerfile` — multi-stage, non-root user, healthcheck, gunicorn+uvicorn workers.
- `docker/ai.Dockerfile` — torch (CPU wheel by default; a CUDA variant behind a build arg),
  bakes in `models/`.
- `docker/dashboard.Dockerfile` — Vite build → nginx static serve with SPA fallback.
- `docker/docker-compose.yml` — `postgres`, `redis`, `minio`, `backend`, `worker`, `beat`,
  `dashboard`, `nginx`; healthchecks, depends_on conditions, named volumes, restart policies.
- `docker/nginx.conf` — reverse proxy, TLS termination, **WebSocket upgrade headers**,
  client_max_body_size for uploads, gzip.
- `.env.example` — every variable documented with a safe default or a clear placeholder.
- `Makefile` — `make up`, `make down`, `make migrate`, `make seed`, `make test`, `make logs`,
  `make backup`, `make demo`.
- `documentation/DEPLOYMENT.md` — first-boot, migrations, seeding, model placement, TLS,
  backups, restore, upgrade, rollback.
- `documentation/RUNBOOK.md` — what to do when: the worker queue backs up, a device stops
  reporting, disk fills, a model needs replacing, the DB needs restoring.
- `documentation/DEMO.md` — the **defense script**, minute by minute.
- Root `README.md` — what GeoVision is, architecture diagram, quickstart, pointer to this vault.

## Compose topology
```
nginx :443 ──┬── dashboard (static)
             └── backend :8000 ──┬── postgres :5432   (volume: pgdata)
                                 ├── redis :6379
                                 └── minio :9000      (volume: minio)
worker  ── redis, postgres, minio, /models
beat    ── redis
```

## Critical implementation notes
- **Nginx must pass `Upgrade`/`Connection` headers** or WebSocket silently fails behind the
  proxy while working fine in dev — a classic late-stage surprise. Test through nginx.
- `client_max_body_size` ≥ 10 MB, and keep it consistent with the backend's upload limit;
  a mismatch produces a confusing 413 from the wrong layer.
- Migrations run as an explicit step (`make migrate`), **not** automatically on container
  start — an auto-migrating container that crash-loops can half-apply a schema.
- Models are mounted as a volume or baked in deliberately; document which, because "it works
  on my machine" is usually a missing `best.pt`.
- Non-root containers, pinned base image digests, no secrets in the image.
- `make backup`: `pg_dump` + MinIO bucket sync, timestamped. Test the **restore** at least
  once — an untested backup is not a backup.
- Provide a **CPU-only** default path. The examiner's machine may have no GPU, and the demo
  must run there.
- Include an offline-demo fallback (seeded DB + recorded captures) in case the venue Wi-Fi
  fails. Assume it will.

## Deployment targets
| Target | Use |
|---|---|
| Local Docker | development, defense demo |
| LAN server / mini-PC | live pilot with real cameras |
| Cloud VM (2 vCPU / 4 GB) | public dashboard access; CPU inference is sufficient |
| Cloudflare Tunnel / ngrok | give the field ESP32 a public HTTPS endpoint without a static IP |

## How to run
```bash
cp .env.example .env      # fill in secrets
make up && make migrate && make seed
open https://localhost
```

## Testing procedure
1. Fresh clone on a clean machine → `make up` → everything healthy within 2 minutes.
2. Migrations and seed succeed; the dashboard loads through nginx over TLS.
3. WebSocket works **through nginx** (not just direct to uvicorn).
4. `simulate_device.py` against the deployed URL → full pipeline runs.
5. Upload a 9 MB image → clean 413 with a clear message; 4 MB → accepted.
6. Restart every container → data survives (volumes correct).
7. `make backup` then restore into a clean stack → data intact.
8. CPU-only mode → inference works, latency recorded.
9. Real ESP32 against the deployed endpoint over the internet.
10. Rehearse `DEMO.md` end to end, timed.

## Defense demo script (`DEMO.md` outline, ~8 minutes)
1. Homepage as a visitor — public projects with GPS and last-capture timestamps.
2. Open a project — progress, timeline, stage bars, geotagged images. (30 s)
3. Log in → profile → create a new project live. (60 s)
4. Pair a camera — QR + code on screen; **power on the real ESP32**. (90 s)
5. The camera captures and uploads; the image appears **without a refresh**; progress moves. (90 s)
6. Show the AI detail: predicted stage, confidence, YOLO overlay, preprocessing before/after. (60 s)
7. Generate and open a PDF report. (45 s)
8. Show a project at 80 % → approve it → 100 % complete, with the accountability rationale. (45 s)
9. Close on the evaluation figures: confusion matrix, comparison table, smoothing plot. (60 s)

## Done criteria
- [ ] One-command bring-up on a clean machine
- [ ] WebSocket verified through the proxy
- [ ] Backup and **restore** both tested
- [ ] CPU-only path verified
- [ ] DEPLOYMENT, RUNBOOK, DEMO, and README written
- [ ] Demo rehearsed with real hardware, plus an offline fallback prepared

## Related
[[Tech-Stack]] · [[Module-15-Testing-and-Evaluation]] · [[Thesis-Mapping]] · [[Master-Architecture]]
