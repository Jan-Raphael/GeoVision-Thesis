# GeoVision — Finalized Architecture

**GeoVision: Smart Construction Monitoring Using AI and Geotagging**
Undergraduate Computer Engineering thesis · hardware + software system · v1.0 · 2026-08-12

> ## 📖 The authoritative architecture lives in the Obsidian vault
> **[`GeoVision-Vault/00-START-HERE.md`](GeoVision-Vault/00-START-HERE.md)**
>
> This file is the executive summary. Every detail — schema, algorithms, API, protocols,
> per-module build specs — lives in the vault, cross-linked so it can be navigated in
> Obsidian's graph view. **Read the vault before writing any code.**

---

## What GeoVision does

An ESP32-CAM node mounted at a fixed angle on a construction site wakes on a schedule,
captures a photo, geotags it (GPS + RTC timestamp), buffers it to microSD, and uploads it to
the GeoVision server over Wi-Fi. The server authenticates the device, resolves which **project
folder** it is paired to, names and stores the image, then runs the AI pipeline: OpenCV
preprocessing → **ResNet18** stage classification → mapping to macro construction stages →
temporally smoothed progress percentage → **YOLOv8** object detection for corroboration.
Results land in PostgreSQL and are pushed live to a React dashboard over WebSocket.

The dashboard has a **public** face (anyone can browse public projects, their progress,
timeline, GPS location, and public owner profiles) and an **authenticated** face (owners
create project folders, pair cameras, collaborate, and export PDF/CSV reports).

## System at a glance

```
ESP32-CAM (capture · GPS · RTC · microSD)
      │  HTTPS multipart, HMAC-signed
      ▼
FastAPI ingest ──► Redis/Celery ──► AI worker
      │                                 │  OpenCV → ResNet18 → YOLOv8 → progress engine
      │                                 ▼
      │                            PostgreSQL + MinIO
      ▼
React dashboard  ◄── WebSocket push (public site + owner dashboard)
```

## The six decisions that define this design

| | Decision | Where |
|---|---|---|
| 1 | **Two-layer stages.** ResNet18 predicts 10 fine-grained classes; a deterministic table folds them into 4 macro stages + a manual approval stage. Both the original 10-class spec and the 4×20 % dashboard spec are satisfied. | [Construction Stages](GeoVision-Vault/02-Domain/Construction-Stages.md) · ADR-001 |
| 2 | **The AI cannot mark a project complete.** The machine ceiling is 80 %; the final 20 % requires a named human inspecting the site and signing off. Accountability stays with a person. | [Progress Calculation](GeoVision-Vault/02-Domain/Progress-Calculation.md) · ADR-007 |
| 3 | **Progress is aggregated, not per-image.** Median per camera per day → weighted multi-camera mean → EMA → monotonic ratchet. One occluded frame cannot move the headline number. | [Progress Calculation](GeoVision-Vault/02-Domain/Progress-Calculation.md) · ADR-004 |
| 4 | **HTTP uploads, WebSocket push.** The camera POSTs images (robust on a sleeping, low-heap device); the server pushes updates to the browser (so the owner never refreshes). Both halves of the professor's requirement, with the transport chosen for reasons. | [Realtime Events](GeoVision-Vault/04-API/Realtime-Events.md) · ADR-003 |
| 5 | **Devices authenticate by HMAC.** Pairing issues a QR + single-use code; the device gets a secret it signs every request with. It cannot upload into a project it isn't paired to. | [Device Pairing Protocol](GeoVision-Vault/05-Hardware/Device-Pairing-Protocol.md) · ADR-006 |
| 6 | **Split the dataset by site, not at random.** Fixed cameras produce near-identical frames; a random split leaks buildings across train/test and inflates accuracy. | [Dataset Spec](GeoVision-Vault/06-Dataset/Dataset-Spec.md) · ADR-009 |

Full reasoning, alternatives, and costs for each: [ADR Index](GeoVision-Vault/99-Decisions/ADR-Index.md).

## Construction stages

| Macro stage | Range | Fine classes (model output) |
|---|---|---|
| Foundation | 0–20 % | Site Clearing · Excavation · Footings · Foundation |
| Framing | 20–40 % | Columns · Slab · Walls |
| Roofing | 40–60 % | Roof |
| Finishing | 60–80 % | Finishing |
| **Approval / Checking** | 80–100 % | *(human inspection — not predicted)* |

## Tech stack

**AI** PyTorch · torchvision (ResNet18, MobileNetV3) · Ultralytics YOLOv8 · OpenCV ·
Albumentations · CVAT — **no TensorFlow, anywhere**
**Backend** FastAPI · SQLAlchemy 2 (async) · Alembic · PostgreSQL 16 · Celery + Redis ·
MinIO/S3 · JWT + Argon2 · ReportLab
**Frontend** React 18 + TypeScript · Vite · TanStack Query · Tailwind + shadcn/ui ·
Recharts · MapLibre GL
**Firmware** ESP32-CAM (AI-Thinker) · PlatformIO · NEO-6M GPS · DS3231 RTC · microSD · deep sleep
**Infra** Docker Compose · Nginx · GitHub Actions

Details and version targets: [Tech Stack](GeoVision-Vault/01-Architecture/Tech-Stack.md).

## Repository layout

```
GeoVision-Project/
├── GeoVision-Vault/   documentation & source of truth  ← read first
├── ai/                preprocessing, training, inference, progress engine, evaluation
├── backend/           FastAPI (domain / application / infrastructure / api)
├── dashboard/         React public site + owner dashboard
├── firmware/          ESP32-CAM node
├── dataset/           raw · processed · augmented · labels · metadata
├── models/            trained checkpoints
├── outputs/           runs, evaluation figures, reports
├── scripts/           dataset prep, seeding, device simulator
├── tests/             integration & e2e
├── docker/            Dockerfiles + compose
├── documentation/     exported diagrams, OpenAPI, runbook
└── thesis/            manuscript, figures, defense materials
```

Full tree and placement rules: [Repository Structure](GeoVision-Vault/01-Architecture/Repository-Structure.md).

## Build order — one module at a time

| # | Module | | # | Module |
|---|---|---|---|---|
| 01 | Foundation & Environment Setup | | 09 | Inference Service & Progress Engine |
| 02 | Database Schema & Migrations | | 10 | Reports, Status & Remarks |
| 03 | Auth & Users | | 11 | Public Dashboard |
| 04 | Projects & Folders | | 12 | Owner Dashboard |
| 05 | Device Pairing & Ingestion | | 13 | ESP32-CAM Firmware |
| 06 | AI Preprocessing (OpenCV) | | 14 | Realtime (WebSocket) |
| 07 | Classifier Training | | 15 | Testing & Evaluation |
| 08 | YOLOv8 Detection | | 16 | Deployment & Documentation |

Each module ships all seven artifacts — folder structure, explanation, source code,
dependencies, how to run, testing procedure, expected output — and the next module does not
start until the current one's tests pass.
Sequence, dependency graph, and status board: [Build Order](GeoVision-Vault/03-Modules/Build-Order.md).

## Three things that are on the critical path today

1. **Dataset collection** — start now, not at Module 07. A model cannot be trained the week
   before the defense. ([Dataset Spec](GeoVision-Vault/06-Dataset/Dataset-Spec.md))
2. **Hardware ordering** — shipping lead time is the one delay no amount of coding fixes.
   ([ESP32-CAM Node](GeoVision-Vault/05-Hardware/ESP32-CAM-Node.md))
3. **Site access permission** — real captures over real calendar weeks are what make this a
   thesis rather than a demo. ([Open Questions](GeoVision-Vault/99-Decisions/Open-Questions.md))

Everything from Module 05 onward is testable **without hardware** via
`scripts/simulate_device.py`, so software work is never blocked on parts arriving.

## Key documents

| Topic | Note |
|---|---|
| Full architecture | [Master Architecture](GeoVision-Vault/01-Architecture/Master-Architecture.md) |
| Database & entities | [Domain Model](GeoVision-Vault/02-Domain/Domain-Model.md) |
| Progress algorithm | [Progress Calculation](GeoVision-Vault/02-Domain/Progress-Calculation.md) |
| Permissions | [Roles and Permissions](GeoVision-Vault/02-Domain/Roles-and-Permissions.md) |
| Every endpoint | [API Contract](GeoVision-Vault/04-API/API-Contract.md) |
| Naming rules | [Naming Conventions](GeoVision-Vault/01-Architecture/Naming-Conventions.md) |
| Hardware & pairing | [ESP32-CAM Node](GeoVision-Vault/05-Hardware/ESP32-CAM-Node.md) · [Device Pairing Protocol](GeoVision-Vault/05-Hardware/Device-Pairing-Protocol.md) |
| Thesis measurements | [Evaluation Plan](GeoVision-Vault/07-Thesis/Evaluation-Plan.md) · [Thesis Mapping](GeoVision-Vault/07-Thesis/Thesis-Mapping.md) |
| Decisions & scope | [ADR Index](GeoVision-Vault/99-Decisions/ADR-Index.md) · [Open Questions](GeoVision-Vault/99-Decisions/Open-Questions.md) |
