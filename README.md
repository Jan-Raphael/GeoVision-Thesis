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

🟢 **Module 01 (Foundation & Environment Setup) complete** — 59 tests green, 4 architecture
contracts enforced, CI configured. [Module 02 (Database Schema)](GeoVision-Vault/03-Modules/Module-02-Database-Schema.md)
is next; it needs Docker Desktop installed first.

## Stack

PyTorch · ResNet18 · YOLOv8 · OpenCV · FastAPI · PostgreSQL · Celery/Redis · MinIO ·
React + TypeScript · ESP32-CAM · Docker

**No TensorFlow** — a hard project constraint.

## Quickstart

Prerequisites: Python 3.11, Node 20+, [uv](https://docs.astral.sh/uv/), Docker Desktop.

```powershell
# Windows
pip install uv
python scripts/generate_secrets.py   # creates .env with real secrets
.\dev.ps1 setup                      # backend + ai + dashboard + git hooks
.\dev.ps1 up                         # postgres, redis, minio
.\dev.ps1 api                        # http://localhost:8000/docs
.\dev.ps1 dashboard                  # http://localhost:5173
.\dev.ps1 check                      # everything CI runs
```

```bash
# Linux / macOS / WSL — identical task names
make setup && make up && make api
```

Run `.\dev.ps1 help` (or `make help`) for the full task list.

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