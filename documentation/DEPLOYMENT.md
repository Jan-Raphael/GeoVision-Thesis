# Deployment

Module 16's one-command, fully-containerised bring-up: nginx + backend + Celery worker +
beat + dashboard, fronting postgres/redis/minio. This is **not** the day-to-day dev
workflow — for that, see [README.md](../README.md)'s Quickstart, which runs the API,
worker, and dashboard directly on the host with hot reload. This document covers running
the *packaged* system: on your own machine for the defense demo, on a mini-PC for a real
site pilot, or on a cloud VM.

Everything here runs at **zero cost** if you stay on your own hardware — Docker,
self-signed TLS, and Cloudflare Tunnel (for the one piece that genuinely needs a public
address, the ESP32's uploads) are all free. Renting a cloud VM is optional, not required.

## First boot

```bash
cp .env.example .env                  # if you don't already have one
python scripts/generate_secrets.py    # fills in real random secrets
make deploy-up                        # builds images, starts everything, generates a TLS cert
make deploy-migrate                   # creates the schema (not automatic — see "Why no
                                       # auto-migration" below)
make deploy-seed                      # optional — sample projects/users for a demo
```

Windows: same tasks, `.\dev.ps1 deploy-up`, `.\dev.ps1 deploy-migrate`, `.\dev.ps1 deploy-seed`.

Open **https://localhost** — your browser will warn about the self-signed certificate
(expected, see below). Accept it once.

`make deploy-ps` shows every container's health; `make deploy-logs` tails all of them
together. A fresh clone with Docker already installed should reach "everything healthy"
within about two minutes.

## What's actually running

| Container | Image | Needs torch? |
|---|---|---|
| `nginx` | `nginx:1.27-alpine` | no — reverse proxy + TLS termination only |
| `dashboard` | built from `docker/dashboard.Dockerfile` | no — static files, its own internal nginx |
| `backend` | built from `docker/backend.Dockerfile` | **no** (ADR-011) — FastAPI + gunicorn |
| `worker` | built from `docker/worker.Dockerfile` | **yes** — the actual AI pipeline |
| `beat` | same image as `backend` | no — only ever publishes scheduled tasks, never executes one |
| `postgres`, `redis`, `minio` | official images | no |

`backend` and `worker` are deliberately different images (ADR-011: "the API process never
imports torch"). `beat` reuses the `backend` image rather than getting a third — verified
while building this: `app/worker/celery_app.py` imports every task module eagerly to
register them, but each one only imports `ai`/torch *inside* its task functions, never at
module load, so beat (which only schedules, never executes) never touches torch either.

## TLS: self-signed by default, free either way

`make deploy-tls` (also run automatically by `make deploy-up` the first time) generates a
self-signed certificate into `docker/certs/` — gitignored, regenerate any time. This is
what makes `https://localhost` work today, at zero cost, with one browser warning to
click through.

**When the ESP32 needs to reach the server from a real construction site**, it needs a
real public address — that's a separate, later decision from what's described here, and
it does **not** require buying anything:

- **Cloudflare Tunnel** (the vault's own answer to this, Q4) — free, gives you a real
  HTTPS hostname pointed at whatever machine is running `docker compose`, no port
  forwarding, no static IP, no cert management (Cloudflare terminates TLS for you, so
  `docker/nginx.conf` would drop back to plain HTTP behind the tunnel).
- A cloud VM is the only piece on the [deployment targets table](../GeoVision-Vault/03-Modules/Module-16-Deployment.md#deployment-targets)
  that costs money, and it is optional — everything in this document already runs
  without one.

## Model placement

The worker container mounts `../backend/models` (relative to `docker/`) into
`/app/backend/models`, **read-only** — not baked into the image. Module 07's checkpoint
is too large (134 MB) and changes independently of the code, so a volume means swapping
in a newly-trained checkpoint is a file copy, not an image rebuild.

```
backend/models/classifier/resnet18/v1/best.pt
```

`GV_MODEL_DIR=./models` and `GV_CLASSIFIER_WEIGHTS=classifier/resnet18/v1/best.pt` in
`.env` resolve identically whether the worker runs natively (`uv run` from `backend/`) or
in this container (`WORKDIR /app/backend`) — same relative path, same cwd convention,
no special-casing needed between the two. If `GV_CLASSIFIER_WEIGHTS` is empty, the worker
serves the deterministic stub instead of failing to start (see
[ai/inference/service.py](../ai/src/ai/inference/service.py)'s `build_service`).

No detector weights exist yet (Module 08 is blocked on annotation) — the worker runs with
no detector at all, deliberately, rather than a stub one. See Progress-Log, 2026-08-29,
for why a stub detector would be worse than none here.

## Why no auto-migration

Migrations run as an explicit step (`make deploy-migrate`), never automatically on
container start. An auto-migrating container that crash-loops (bad env var, unreachable
DB) can half-apply a schema on every restart attempt — worse than a container that simply
fails to come up and says why.

## Backup and restore

```bash
make deploy-backup                              # -> ./backups/<UTC timestamp>/
make deploy-restore DIR=backups/20260829T120000Z
```

`deploy-backup` dumps postgres (`pg_dump`, straight through `docker compose exec`) and
mirrors the minio bucket into the same timestamped directory. `deploy-restore` reverses
both — it is destructive (drops and recreates the public schema before loading the dump)
and asks for confirmation unless you pass `--yes` to `scripts/restore.py` directly.

**Test the restore at least once before you need it for real** — an untested backup is
not a backup. A reasonable rehearsal: `deploy-backup`, `deploy-restore` into the same
stack, confirm the dashboard still shows the same projects.

## Upgrade / rollback

```bash
git pull
make deploy-up          # rebuilds any image whose source changed
make deploy-migrate      # applies any new migration
```

Rollback is the same in reverse: `git checkout <previous-tag>`, `make deploy-up`. A
migration that isn't purely additive needs its own `alembic downgrade` step **before**
checking out older code — the same rule that applies to every other Alembic project.

## CPU-only path

Everything above already runs CPU-only — `ai/pyproject.toml` pins the CPU torch wheel by
default (ADR-012), and the worker image installs no CUDA runtime. This is deliberate: the
examiner's machine may have no GPU, and the demo has to run there. A CUDA build is future
work, not wired into `docker/worker.Dockerfile` today, since nothing in scope currently
needs one.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `docker compose ... run --rm ...` for migrate/seed hangs | `postgres`/`redis` not yet healthy — run `make deploy-ps` first |
| Dashboard loads but every API call fails | Check `docker compose ... logs nginx` — usually a missing/misnamed cert in `docker/certs/` |
| WebSocket never connects (no live updates) | Confirm you're going through nginx (`https://localhost`), not `:8000` directly — only nginx sets the `Upgrade`/`Connection` headers |
| Worker container unhealthy, stays "starting" past a minute | First real inference load is slow (cold checkpoint load, ~25-30s) — `start_period: 60s` already accounts for this; if it's still unhealthy after that, check `docker compose logs worker` for a missing `backend/models/...` file |
| `413 Request Entity Too Large` | `client_max_body_size` in `docker/nginx.conf` and `GV_MAX_ASSET_UPLOAD_BYTES` in `.env` must stay in step |

## Related

[[Module-16-Deployment]] in the vault · [RUNBOOK.md](RUNBOOK.md) · [DEMO.md](DEMO.md)
