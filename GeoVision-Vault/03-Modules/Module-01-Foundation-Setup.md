---
title: Module 01 — Foundation & Environment Setup
type: module
module: 1
status: done
started: 2026-08-13
finished: 2026-08-13
updated: 2026-08-13
---

# Module 01 — Project Architecture & Environment Setup

> **Status: ✅ done.** This note was revised after an audit and the implementation.
> It now describes what exists, not what was planned. Decisions taken here are recorded as
> ADR-011 … ADR-014 in [[ADR-Index]].

## Scope
Skeleton and toolchain only — no business logic. Everything after this depends on these
choices being right, which is why the note was audited before a line was written.

---

## What shipped

### Root
| File | Purpose |
|---|---|
| `.gitattributes` | `* text=auto eol=lf`. **Written before `git init`** so no CRLF ever enters history — Windows dev, Linux containers. |
| `.gitignore` | Uses negation patterns so `models/`, `outputs/`, `dataset/` are ignored by content but survive in the tree, while `dataset/metadata/*.csv` stays tracked. |
| `.dockerignore` | Keeps `dataset/`, `models/`, `outputs/`, `node_modules/` out of the build context (GB → MB). |
| `.python-version` `.nvmrc` | Python 3.11, Node 22. |
| `.env.example` | Every setting documented; `.env` git-ignored. |
| `.pre-commit-config.yaml` | ruff, ruff-format, mypy, import-linter, the no-TensorFlow guard, `detect-private-key`, `check-added-large-files`. |
| `.github/workflows/ci.yml` | Six jobs: `constraints`, `lint`, `test-backend` (postgres+redis services), `test-ai`, `frontend`, `compose`. |
| `Makefile` + `dev.ps1` | Same task names on both. `make` is absent on Windows, so `dev.ps1` is the primary local runner. |
| `scripts/check_no_tensorflow.py` | Scans declared deps, **resolved lockfiles**, and the live environment. |
| `scripts/generate_secrets.py` | Creates/patches `.env` with real secrets, idempotently. |

### `ai/` — src-layout package (ADR-011)
```
ai/pyproject.toml          geovision-ai, CPU-pinned torch
ai/src/ai/{preprocessing,data,models,training,progress,inference,evaluation,configs}/
ai/tests/test_package.py   11 tests
```
Each subpackage `__init__.py` documents what will live there and which module builds it, so a
future session gets oriented from the code as well as the vault.

### `backend/` — Clean Architecture skeleton
```
backend/pyproject.toml     3 dependency groups: base / [worker] / [dev]
backend/.importlinter      4 contracts, all enforced
backend/alembic/           async env.py, no revisions yet
backend/app/
  core/       config.py · logging.py · exceptions.py
  domain/     entities · repositories · services      (empty, documented)
  application/use_cases/                              (empty, documented)
  infrastructure/  db · repositories · storage · ai · tasks · reports · realtime · health.py
  api/v1/routers/health.py
  main.py     application factory
backend/tests/  46 tests
```

### `dashboard/` — Vite + React + TypeScript strict
Trimmed per the audit: no shadcn/ui until Module 11. Ships Vite 6, React 18, TanStack Query,
React Router, Tailwind, ESLint (`strictTypeChecked`), Prettier, Vitest 3 + RTL.
`tsconfig.app.json` enables `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes` on top
of `strict`. The dev server proxies `/api` and `/health` to :8000, so the browser sees
same-origin requests exactly as it will behind nginx in Module 16.

### `docker/`
`docker-compose.dev.yml` — postgres 16 (host port **5433**), redis 7, minio, plus a
**`minio-init`** one-shot container that creates the bucket (without it, the first upload in
Module 05 fails with `NoSuchBucket`). `docker/postgres/init/` creates `pgcrypto`, `citext`,
`pg_trgm`, `btree_gin` and the `geovision_test` database. `TZ`/`PGTZ` pinned to UTC.

---

## Key decisions locked here

| Decision | Rationale | ADR |
|---|---|---|
| Python 3.11 · Node 22 | torch/ultralytics support, `StrEnum` | — |
| `ai` as a src-layout package; backend depends on it via a path dependency | makes "API never imports torch" structural | ADR-011 |
| uv + committed `uv.lock`; ruff only (no black); torch from the CPU index | reproducibility, one formatter, laptop-sized installs | ADR-012 |
| Celery in a Linux container; `--pool=solo` locally | prefork does not work on Windows | ADR-013 |
| `stringzilla<4`, albumentations 2.x | no MSVC toolchain needed on Windows | ADR-014 |
| App-factory pattern **with `dependency_overrides`** | see "bugs found" below | — |
| Postgres on host port 5433 | avoids the common Windows 5432 clash | — |
| Secrets fail fast when deployed, ephemeral locally | a loud crash beats a silent insecure default | — |

---

## Bugs this module's own tests caught

Worth recording — both would have been expensive later, and both argue for the testing
approach rather than just the code.

1. **The app factory was only half real.** Routes used `Depends(get_settings)`, which returns
   the *cached process-wide* settings, so `create_app(custom_settings)` configured the app
   while its endpoints ignored the override. Every test would have silently depended on
   whatever `.env` existed on the machine. Fixed with an explicit
   `app.dependency_overrides[get_settings]`, plus `tests/unit/test_app_factory.py` asserting
   the override is registered and that two apps do not share settings.
2. **`GV_CORS_ORIGINS=a,b` crashed at startup while all unit tests passed.**
   pydantic-settings JSON-decodes complex types *inside* the dotenv source, before any
   validator runs. Every config test constructed `Settings(**kwargs)` directly and therefore
   never exercised that path. Fixed with `Annotated[list[str], NoDecode]` and explicit JSON
   handling in the validator; `tests/unit/test_config_dotenv.py` now loads from real `.env`
   files, including asserting that the committed `.env.example` itself parses.

   *Generalisable lesson: configuration tested only through its Python constructor is not
   tested the way it is actually used.*

---

## Dependencies
None. This is the root of the build order.

## How to run

```powershell
# Windows
pip install uv
python scripts/generate_secrets.py
.\dev.ps1 setup          # backend + ai + dashboard + git hooks
.\dev.ps1 up             # postgres, redis, minio  (needs Docker Desktop)
.\dev.ps1 api            # http://localhost:8000
.\dev.ps1 dashboard      # http://localhost:5173
.\dev.ps1 check          # everything CI runs
```
```bash
# Linux / macOS / WSL — identical task names
make setup && make up && make api
```

## Testing procedure

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | Liveness | `GET localhost:8000/health` | `200` `{"status":"ok","version":"0.1.0"}` |
| 2 | Readiness | `GET localhost:8000/health/ready` | `200` when the stack is up; `503` + per-service detail when it is not |
| 3 | Swagger | `localhost:8000/docs` | renders (hidden in staging/production) |
| 4 | Error envelope | `GET localhost:8000/nope` | `404` `{"error":{"code":"NOT_FOUND","request_id":…}}` |
| 5 | Dashboard | `localhost:5173` | shell renders and displays live backend status |
| 6 | Backend suite | `uv run pytest` | **46 passed** |
| 7 | AI suite | `uv run pytest` in `ai/` | **11 passed** |
| 8 | Dashboard suite | `npm run test` | **2 passed** |
| 9 | Lint + types | `ruff check` · `ruff format --check` · `mypy app` · `tsc` · `eslint` | clean |
| 10 | Architecture | `uv run lint-imports` | **4 contracts kept, 0 broken** |
| 11 | Constraint | `python scripts/check_no_tensorflow.py` | `PASSED: project is TensorFlow-free` |
| 12 | Frontend build | `npm run build` | succeeds |

## Expected output

```
backend:   46 passed
ai:        11 passed   (torch 2.13.0+cpu)
dashboard:  2 passed, build ok, tsc clean, eslint clean
lint-imports: Contracts: 4 kept, 0 broken.
check_no_tensorflow: PASSED
GET /health -> {"status":"ok","app":"GeoVision","version":"0.1.0","environment":"local"}
```

## Done criteria

- [x] Tree matches [[Repository-Structure]]
- [x] `/health` returns 200; `/health/ready` reports per-dependency status
- [x] Compose stack defined, with bucket + extension bootstrap
- [x] Lint, format, and type checks clean across backend, ai, dashboard
- [x] **Architecture boundaries enforced** by import-linter *and* by unit tests
- [x] No TensorFlow — checked in declared deps, lockfiles, and the live environment
- [x] `.env` git-ignored; `.env.example` committed **and proven loadable by a test**
- [x] Lockfiles committed for reproducibility
- [x] CI workflow covering constraints, lint, both Python suites, frontend, compose validity

## Known gaps handed to later modules

- **Docker Desktop is not installed on the dev machine.** Module 01 verifies fully without it
  (`/health/ready` correctly reports `503`), but Module 02 needs a real PostgreSQL. Tracked as
  Q9 in [[Open-Questions]].
- `firmware/esp32cam-node/platformio.ini` deliberately deferred to [[Module-13-Firmware]] —
  its contents depend on the board revision and pinout, still open as Q2.
- shadcn/ui deferred to [[Module-11-Public-Dashboard]].

## Related
[[Repository-Structure]] · [[Tech-Stack]] · [[ADR-Index]] · [[Module-02-Database-Schema]]
