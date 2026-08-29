# GeoVision

**Smart Construction Monitoring Using AI and Geotagging**
Undergraduate Computer Engineering thesis project — hardware + software.

An ESP32-CAM mounted at a construction site captures geotagged photos on a schedule and
uploads them automatically. The server classifies the construction stage with a ResNet18
model, corroborates it with YOLOv8 object detection, computes a smoothed progress
percentage, and presents everything on a React dashboard — with a public view for visitors
and an authenticated dashboard for project owners.

---

## 📖 Start here

| I want to… | Go to |
|---|---|
| Understand the system | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Work on it (human or AI) | [`GeoVision-Vault/00-START-HERE.md`](GeoVision-Vault/00-START-HERE.md) |
| Know what to build next | [`GeoVision-Vault/03-Modules/Build-Order.md`](GeoVision-Vault/03-Modules/Build-Order.md) |
| See where things stand | [`GeoVision-Vault/99-Decisions/Progress-Log.md`](GeoVision-Vault/99-Decisions/Progress-Log.md) |

> **`GeoVision-Vault/` is the source of truth.** It is an Obsidian vault holding the
> architecture, database schema, algorithms, API contract, hardware protocols, and a build
> spec for each of the 16 modules. Read it before writing code — code follows the vault.

## Status

🟢 **12 of 16 modules shipped**, plus a full containerised deployment (16) on top of them —
foundation, database, auth, projects, device pairing & ingestion, AI preprocessing, the
inference/progress engine (now serving a real trained ResNet18, not just the stub), reports,
the public dashboard, the owner dashboard, and realtime WebSocket push are all built and
tested (800+ backend tests). YOLOv8 detection (Module 08) is blocked on bounding-box
annotation; firmware (13) and the full test/eval pass (15) are still in progress. See
[Build-Order](GeoVision-Vault/03-Modules/Build-Order.md) for the live status board. The stack
runs end to end — ingest → AI inference → progress → dashboard — against the device
simulator today, with real hardware still to come.

## Stack

PyTorch · ResNet18 · YOLOv8 · OpenCV · FastAPI · PostgreSQL · Celery/Redis · MinIO ·
React + TypeScript · ESP32-CAM · Docker

**No TensorFlow** — a hard project constraint.

## Quickstart

Prerequisites: Python 3.11, Node 20+, [uv](https://docs.astral.sh/uv/), Docker Desktop.

```powershell
# Windows — one-time setup, then one command to start everything
pip install uv
python scripts/generate_secrets.py   # creates .env with real secrets
.\dev.ps1 setup                      # backend + ai + dashboard + git hooks
.\dev.ps1 dev                        # infra + migrate, then api/worker/dashboard in new windows
```

```bash
# Linux / macOS / WSL — identical task names
make setup && make dev
```

`dev` starts Postgres/Redis/MinIO, applies migrations, then runs the API, Celery worker, and
dashboard together — each in its own window on Windows (`Ctrl+C` any one to stop it), or all
three in the current terminal on Linux/macOS/WSL (`Ctrl+C` once stops all three). API docs at
`http://localhost:8000/docs`, dashboard at `http://localhost:5173`.

Run `.\dev.ps1 help` (or `make help`) for the full task list. The rest of this section walks
through the individual steps `dev` runs for you — useful when you want just one piece running,
or something needs debugging in isolation; full troubleshooting lives in
[Local-Environment-Setup.md](GeoVision-Vault/01-Architecture/Local-Environment-Setup.md).

---

## Running the whole system

GeoVision has four moving parts: **infrastructure** (Postgres/Redis/MinIO, via Docker), the
**backend API**, the **Celery worker** (runs the AI pipeline), and the **dashboard**.
`.\dev.ps1 dev` (or `make dev`) starts all four in one shot, as shown in Quickstart above — use
it day to day. The rest of this section breaks that down into individual steps: reach for these
when you want just one piece running, something needs debugging in isolation, or you're setting
up for the first time and want to see each stage succeed on its own before combining them.

### 0. Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.11 | `python --version` |
| [uv](https://docs.astral.sh/uv/) | latest | `uv --version` (`pip install uv` if missing) |
| Node.js | ≥ 20 | `node --version` |
| Docker Desktop | latest, WSL2 backend | `docker --version` |

First time on this machine? Follow
[Local-Environment-Setup.md](GeoVision-Vault/01-Architecture/Local-Environment-Setup.md) once —
it walks through WSL2 + Docker Desktop installation and resource limits in detail. Everything
below assumes that's done.

### 1. Configure secrets

```powershell
python scripts/generate_secrets.py
```

Creates `.env` at the repo root (git-ignored) with real random secrets filled in — JWT signing
key, Postgres password, MinIO credentials. Compose and the backend both read this file; nothing
starts without it (`GV_*` variables fail loudly rather than falling back to an insecure default).

### 2. Install dependencies

```powershell
.\dev.ps1 setup
```

Installs backend deps (`uv sync --extra dev` in `backend/`), AI package deps (`uv sync --extra
dev` in `ai/`), dashboard deps (`npm install` in `dashboard/`), and the pre-commit git hooks.
Each project keeps its own virtual environment / `node_modules` — there's nothing to activate
manually; `dev.ps1` / `make` always run through `uv run` or `npm run`.

### 3. Start infrastructure (Docker)

```powershell
.\dev.ps1 up
```

By default this starts **Redis** (`localhost:6379`) and **MinIO** (`localhost:9000`, console at
`localhost:9001`) plus a one-shot `minio-init` container that creates the storage bucket —
seeing it as `Exited (0)` in `docker compose ps` is correct, not a failure.

**PostgreSQL is behind a Docker Compose profile**, not started by `up` alone:

- If you already have a native/local PostgreSQL 16 running on port 5433 (the setup this repo
  was developed against), use that — nothing more to do, just make sure it's running.
- Otherwise, start the containerized one too:
  ```powershell
  docker compose --env-file .env -f docker/docker-compose.dev.yml --profile db up -d
  ```

Never run both against the same port — see the [profile note in
docker-compose.dev.yml](docker/docker-compose.dev.yml) for why that's actively dangerous rather
than merely redundant.

Check everything's healthy: `.\dev.ps1 ps`.

### 4. Apply migrations and (optionally) seed data

```powershell
.\dev.ps1 migrate      # Alembic — creates all tables
.\dev.ps1 seed         # optional — sample users/projects/devices for local UI testing
```

### 5. Start the backend API

```powershell
.\dev.ps1 api
```

FastAPI with hot reload at **http://localhost:8000** — interactive docs at
`/docs`, health check at `/health/ready`. A `"status": "ready"` response with all three checks
(`postgres`, `redis`, `object_storage`) `"ok"` means the whole backend half of the stack is
correctly wired.

### 6. Start the Celery worker

```powershell
.\dev.ps1 worker
```

Runs the AI pipeline (OpenCV preprocessing → ResNet18 → YOLOv8 → progress aggregation) and
report generation, consuming the `ingest`, `inference`, `interactive`, and `reports` queues. The
API accepts uploads without this running, but nothing gets processed — no predictions, no
progress updates — until a worker is up. On Windows this runs with `--pool=solo` (Celery's
default prefork pool needs `fork()`, which Windows doesn't have); in Docker/production it uses
the normal pool. Optionally, in a fourth terminal, run the scheduler that drives periodic jobs
(status refresh, offline-device sweep, remark cleanup):

```powershell
.\dev.ps1 beat
```

### 7. Start the dashboard

```powershell
.\dev.ps1 dashboard
```

Vite dev server at **http://localhost:5173** — the public site (homepage feed, project pages,
search) and, once logged in, the owner dashboard (create project, pair a camera, devices,
reports). It talks to the API at `localhost:8000` and opens a WebSocket for live updates; CORS
for `localhost:5173` is already set in `.env.example`.

### 8. See it move, without hardware

No ESP32-CAM yet? `scripts/simulate_device.py` replays a folder of images as a fake device —
correct HMAC signing, synthetic GPS, optional failure injection — so you can watch an upload
flow through ingest → worker → progress → dashboard end to end. Pair a device in the dashboard
first (Project Folder → Devices → Pair Camera) to get a device secret, then:

```powershell
cd backend
uv run python -m scripts.simulate_device --code K7M2-9XQF --images ../dataset/raw --count 5
# --help lists everything, including failure injection (--bad-signature, --replay,
# --clock-skew, --tamper) for exercising the ingest auth checks.
```

### Daily workflow, once everything's set up

| Task | Command |
|---|---|
| Start infra | `.\dev.ps1 up` |
| Stop infra (keeps data) | `.\dev.ps1 down` |
| Infra status / logs | `.\dev.ps1 ps` / `.\dev.ps1 logs` |
| Run the API | `.\dev.ps1 api` |
| Run the worker | `.\dev.ps1 worker` |
| Run the beat scheduler | `.\dev.ps1 beat` |
| Run the dashboard | `.\dev.ps1 dashboard` |
| New/changed migrations | `.\dev.ps1 migrate` |
| Everything CI runs (lint, types, arch, tests) | `.\dev.ps1 check` |
| **Everything at once** (infra + migrate + api + worker + dashboard) | `.\dev.ps1 dev` |
| **Wipe all local data** (asks to confirm) | `.\dev.ps1 nuke` |

Linux/macOS/WSL: same task names via `make <task>` instead of `.\dev.ps1 <task>`.

## Deployment

Everything above is the day-to-day dev workflow (hot reload, services in Docker, app code on
the host). For the **fully containerised** stack — nginx + backend + worker + beat +
dashboard, all in Docker, TLS included — see [documentation/DEPLOYMENT.md](documentation/DEPLOYMENT.md).
Short version:

```bash
python scripts/generate_secrets.py
make deploy-up && make deploy-migrate && make deploy-seed
open https://localhost
```

Runs entirely on your own machine at zero cost (self-signed TLS by default); a public
address for a real field camera is a separate, later, still-free step via Cloudflare
Tunnel — see DEPLOYMENT.md. Also: [documentation/RUNBOOK.md](documentation/RUNBOOK.md)
(what to do when something breaks) and [documentation/DEMO.md](documentation/DEMO.md) (the
defense script, minute by minute).

## Layout

```
ai/          preprocessing · training · inference · progress engine · evaluation
backend/     FastAPI (domain / application / infrastructure / api)
dashboard/   React public site + owner dashboard
firmware/    ESP32-CAM node
dataset/     raw · processed · labels · metadata
scripts/     dataset prep · seeding · device simulator
docker/      Dockerfiles + compose
thesis/      manuscript, figures, defense materials
```