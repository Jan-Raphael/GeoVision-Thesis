---
title: Tech Stack
type: architecture
status: canonical
updated: 2026-08-12
---

# Tech Stack & Hard Constraints

## 🚫 Hard constraints (non-negotiable)

- **TensorFlow / Keras is FORBIDDEN.** Anywhere. Including transitive dependencies pulled in
  "just for a metric". If a library requires TF, find another library.
- Deep learning is **PyTorch only**.
- Database is **PostgreSQL** only (no SQLite in production paths; SQLite may be used *only*
  inside fast unit tests that do not exercise Postgres-specific types).
- Image binaries never stored in the database.
- No secret (device secret, JWT secret, DB password) committed to git.

## AI / CV

| Purpose | Choice | Version target |
|---|---|---|
| DL framework | PyTorch + torchvision | 2.x — **CPU wheels by default**, see below |
| Classifier | ResNet18 (ImageNet pretrained, transfer learning) | torchvision weights |
| Comparison backbone | MobileNetV3-Small/Large | torchvision weights |
| Detector | YOLOv8n / YOLOv8s (`ultralytics`) | 8.x — optional extra `[detect]` |
| Classic CV | OpenCV (`opencv-python-headless` on server) | 4.x |
| Augmentation | Albumentations | **2.x** (API differs from 1.x — ADR-014) |
| Metrics | scikit-learn, torchmetrics | — |
| Annotation | **CVAT** (classification tags + YOLO bboxes) | self-hosted or cloud |
| Experiment logging | CSV + matplotlib into `outputs/` (MLflow optional, not required) | — |

Training features required: early stopping, `ReduceLROnPlateau` (or cosine) scheduler,
`torch.cuda.amp` mixed precision when GPU present, **CPU fallback**, checkpointing
(`best.pt` by val-F1 + `last.pt`), deterministic seeding, class-weighted loss for imbalance.

> **Torch installs CPU-only by default** (`[tool.uv.sources]` pins the PyTorch CPU index).
> The CUDA build is ~2.5 GB and useless without an NVIDIA GPU. To train on a local GPU,
> comment out that block in `ai/pyproject.toml` and re-run `uv sync` — no code changes are
> needed, since every entrypoint selects the device at runtime. See ADR-012.

## Backend

| Purpose | Choice |
|---|---|
| API | FastAPI + Uvicorn (Gunicorn workers in prod) |
| Validation | Pydantic v2 + pydantic-settings |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| DB | PostgreSQL 16 (+ optional PostGIS; plain lat/lon columns are sufficient) |
| Queue | Celery + Redis |
| Object storage | MinIO (dev/Docker), S3-compatible in prod, via `boto3` |
| Auth | JWT (`python-jose`), Argon2 (`argon2-cffi`) |
| Realtime | FastAPI WebSocket + Redis pub/sub fan-out |
| PDF | ReportLab (+ matplotlib for embedded charts) |
| CSV | stdlib `csv` / pandas |
| QR codes | `qrcode[pil]` |
| Package manager | **uv**, with `uv.lock` committed (ADR-012) |
| Lint/format | **ruff** (`check` + `format`) + mypy. **Not black** — ruff replaces it |
| Architecture enforcement | `import-linter` (4 contracts in `backend/.importlinter`) |
| Tests | pytest, pytest-asyncio, httpx, factory-boy, freezegun |

## Frontend

| Purpose | Choice |
|---|---|
| Framework | React 18 + TypeScript (strict) |
| Build | Vite |
| Server state | TanStack Query v5 |
| Client state | Zustand |
| Routing | React Router v6 |
| Styling | Tailwind CSS + shadcn/ui |
| Charts | Recharts |
| Maps | MapLibre GL JS (OSM tiles) — external "open in maps" links to Google/OSM |
| Forms | React Hook Form + Zod |
| Realtime | native WebSocket wrapped in a reconnecting client |
| Tests | **Vitest 3** + React Testing Library, Playwright for e2e |

> Vitest **3**, not 2: Vitest 2 bundles Vite 5 while the project uses Vite 6, and the
> duplicated type trees break `tsc -b`. Import `defineConfig` from `vitest/config`, not
> `vite`, or the `test` block fails type checking.

## Firmware (ESP32-CAM)

| Purpose | Choice |
|---|---|
| Board | AI-Thinker ESP32-CAM (OV2640) |
| Toolchain | PlatformIO, Arduino-ESP32 core |
| GPS | NEO-6M / NEO-M8N over UART (TinyGPS++) |
| RTC | DS3231 (I²C) — wake alarm + trusted timestamp |
| Storage | microSD (SD_MMC 1-bit mode) |
| Power | Li-ion / power bank + deep sleep |
| HTTP | `HTTPClient` multipart POST over TLS |
| Crypto | mbedTLS HMAC-SHA256 (built in) |
| Config | NVS (Preferences) for Wi-Fi creds + device secret + project binding |

## Infrastructure

Docker + docker-compose (`postgres`, `redis`, `minio`, `backend`, `worker`, `dashboard`,
optional `nginx`). Git with conventional commits. GitHub Actions CI: constraints → lint →
backend tests → ai tests → frontend build → compose validation.

## Development platform notes (Windows)

The dev machine runs Windows 10, which imposes three constraints worth knowing before they
cost you a day:

| Constraint | Consequence |
|---|---|
| Celery's prefork pool needs `fork()` | run the worker **in Docker**; `--pool=solo` locally only (ADR-013) |
| CRLF line endings | `.gitattributes` with `eol=lf` must exist **before the first commit**, or scripts break inside Linux containers |
| No `make` by default | use `dev.ps1`, which mirrors every Makefile task |
| A local PostgreSQL often occupies 5432 | the dev stack maps host **5433** instead |
| Some C-extension wheels are missing | e.g. `stringzilla<4` is pinned to avoid needing MSVC Build Tools (ADR-014) |

Docker Desktop (WSL2 backend) is required from Module 02 onward.

## Related
[[Master-Architecture]] · [[Module-01-Foundation-Setup]] · [[Module-16-Deployment]]
