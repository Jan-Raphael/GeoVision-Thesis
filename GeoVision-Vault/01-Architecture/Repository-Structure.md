---
title: Repository Structure
type: architecture
status: canonical
updated: 2026-08-14
---

# Repository Structure

Canonical tree. **Do not create top-level folders that are not listed here** without an ADR.

> **Updated 2026-08-13 (Module 01).** `ai/` uses a **src-layout** — the package lives at
> `ai/src/ai/`, so the import path stays `ai.progress.aggregator` while the working directory
> can never shadow the installed package. See ADR-011 in [[ADR-Index]].

```
GeoVision-Project/
│
├── GeoVision-Vault/                 # Obsidian vault — SOURCE OF TRUTH (read first)
│
├── ai/                              # distribution: geovision-ai
│   ├── pyproject.toml
│   ├── tests/
│   └── src/ai/                      # ← the importable package
│   ├── configs/                     # yaml: training, model, preprocessing, classes
│   ├── data/
│   │   ├── datamodule.py            # dataset + dataloader builders
│   │   ├── transforms.py            # Albumentations train/val/test pipelines
│   │   └── splitter.py              # 70/15/15 stratified split
│   ├── preprocessing/
│   │   ├── pipeline.py              # PreprocessingPipeline + config fingerprint (ADR-025)
│   │   ├── types.py                 # step Protocol, CalibrationContext
│   │   ├── errors.py                # PreprocessingError / DecodeError / ConfigError
│   │   ├── perspective.py           # homography rectification
│   │   ├── normalize.py             # CLAHE / white balance
│   │   ├── denoise.py               # bilateral filter
│   │   ├── resize.py                # letterbox to 224 / 640
│   │   ├── quality.py               # blur, darkness, occlusion rejection
│   │   ├── calibration.py           # 4 clicked corners -> devices.homography
│   │   └── demo.py                  # before/after strip (thesis Fig. 6) + benchmark
│   ├── models/
│   │   ├── base.py                  # StageClassifier / ObjectDetector protocols
│   │   ├── resnet18.py              # transfer-learning head
│   │   ├── mobilenetv3.py           # comparison backbone
│   │   └── yolov8.py                # ultralytics wrapper
│   ├── training/
│   │   ├── train_classifier.py      # CLI entrypoint
│   │   ├── trainer.py               # loop, AMP, scheduler, early stopping
│   │   ├── callbacks.py             # checkpointing, early stop, csv logger
│   │   └── train_detector.py        # YOLOv8 training entrypoint
│   ├── evaluation/
│   │   ├── metrics.py               # accuracy, P/R/F1, confusion matrix
│   │   ├── benchmark.py             # inference time, params, GPU mem
│   │   └── report.py                # writes outputs/ artifacts
│   ├── progress/
│   │   ├── mapping.py               # fine class → macro stage → %
│   │   ├── estimator.py             # per-image raw progress
│   │   └── aggregator.py            # multi-camera + EMA + ratchet  ← pure, unit-tested
│   └── inference/
│       ├── service.py               # InferenceService (load once, predict many)
│       └── schemas.py               # dataclasses shared with backend
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/                    # settings, logging, exceptions, security
│   │   ├── domain/
│   │   │   ├── entities/            # User, Project, Device, Image, Prediction...
│   │   │   ├── enums.py             # ALL enums live here (single definition)
│   │   │   ├── value_objects.py     # ProjectCode, GeoPoint, ProgressPercent
│   │   │   ├── repositories/        # abstract interfaces
│   │   │   └── services/            # pure domain rules (status, visibility)
│   │   ├── application/
│   │   │   └── use_cases/           # one class per use case
│   │   ├── infrastructure/
│   │   │   ├── db/                  # session, base, sqlalchemy models
│   │   │   ├── repositories/        # concrete repo implementations
│   │   │   ├── storage/             # MinIO/S3 adapter
│   │   │   ├── ai/                  # adapter calling ai.inference
│   │   │   ├── tasks/               # celery app + tasks
│   │   │   ├── reports/             # pdf (reportlab) + csv writers
│   │   │   └── realtime/            # websocket hub / redis pubsub
│   │   └── api/
│   │       ├── deps.py              # DI providers, auth guards
│   │       ├── v1/routers/          # auth, users, projects, devices, images,
│   │       │                        # ingest, predictions, progress, reports,
│   │       │                        # search, public, models, ws
│   │       └── schemas/             # pydantic request/response models
│   ├── alembic/                     # async env.py + script.py.mako + versions/
│   ├── tests/{unit,integration}/
│   ├── .importlinter                # architecture boundary contracts (enforced)
│   └── pyproject.toml               # 3 dep groups: base / [worker] / [dev]
│
├── dashboard/
│   ├── src/{app,features,components,lib,styles}/
│   ├── public/
│   ├── index.html
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── package.json
│
├── firmware/
│   └── esp32cam-node/
│       ├── platformio.ini
│       ├── src/main.cpp
│       ├── src/{camera,gps,storage,uploader,pairing,power,config}.{h,cpp}
│       └── data/                    # provisioning defaults
│
├── dataset/
│   ├── raw/                         # untouched captures, per project code
│   ├── processed/{train,validation,test}/<class>/
│   ├── augmented/
│   ├── labels/                      # CVAT exports: classification.csv + YOLO txt
│   └── metadata/                    # metadata.csv, progress_reference.csv
│
├── models/
│   ├── classifier/{resnet18,mobilenetv3}/<version>/best.pt
│   └── detector/yolov8n/<version>/best.pt
│
├── outputs/
│   ├── runs/<run_id>/               # curves, checkpoints, config snapshot
│   ├── evaluation/                  # confusion matrices, metric tables
│   ├── benchmarks/
│   └── reports/                     # generated PDF/CSV (dev only)
│
├── scripts/
│   ├── prepare_dataset.py
│   ├── split_dataset.py
│   ├── seed_db.py
│   ├── generate_progress_reference.py
│   └── simulate_device.py           # fake ESP32 for testing ingest without hardware
│
├── tests/                           # cross-cutting integration + e2e
│
├── docker/
│   ├── docker-compose.dev.yml       # infra only: postgres, redis, minio, minio-init
│   ├── postgres/init/               # extensions + test database, run on first boot
│   ├── backend.Dockerfile           # Module 16
│   ├── ai.Dockerfile                # Module 16
│   ├── dashboard.Dockerfile         # Module 16
│   └── docker-compose.yml           # Module 16 — full stack incl. nginx
│
├── documentation/                   # exported diagrams, openapi.json, ERD
├── thesis/                          # chapters, figures, defense deck
├── .github/workflows/ci.yml
├── .gitattributes                   # eol=lf — must exist BEFORE the first commit
├── .gitignore
├── .dockerignore
├── .python-version  .nvmrc
├── .env.example
├── .pre-commit-config.yaml
├── Makefile                         # task runner (Linux/macOS/WSL/CI)
├── dev.ps1                          # same task names on Windows
├── ARCHITECTURE.md
├── CLAUDE.md                        # AI-session rules — read the vault first
└── README.md
```

## Rules

- `ai/` must be importable **standalone** (`python -m ai.training.train_classifier`) with no
  backend import. The backend depends on `ai`, never the reverse.
- `backend/app/domain/` must import nothing from `infrastructure/`, `api/`, or `torch`.
  This is enforced by `backend/.importlinter` and by `tests/unit/test_architecture.py` — not
  by convention.
- A task added to `Makefile` must be added to `dev.ps1` too, and vice versa.
- Unit tests live next to the code they test (`ai/tests/`, `backend/tests/unit/`).
  `tests/` at the root is only for cross-service integration/e2e.
- `models/`, `dataset/raw/`, `outputs/` are **git-ignored** (except `.gitkeep` and the CSVs
  in `dataset/metadata/`, which are tracked).

## Related
[[Master-Architecture]] · [[Tech-Stack]] · [[Build-Order]]
