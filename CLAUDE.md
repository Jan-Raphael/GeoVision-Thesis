# GeoVision — instructions for AI coding sessions

## Rule 0 — read the vault first

**Before creating, editing, or generating ANY file in this repository, read the Obsidian
vault at `GeoVision-Vault/`.** Start at `GeoVision-Vault/00-START-HERE.md`.

The vault is the single source of truth for architecture, database schema, naming, API
shape, permissions, and per-module scope. Code follows the vault. Do not invent a table,
column, enum, endpoint, filename format, threshold, or folder that is not defined there.

Minimum reading before touching code:

| Before you… | Read |
|---|---|
| anything at all | `00-START-HERE.md`, `01-Architecture/Master-Architecture.md` |
| create a file or folder | `01-Architecture/Repository-Structure.md` |
| name anything | `01-Architecture/Naming-Conventions.md` |
| touch the database or a model class | `02-Domain/Domain-Model.md` |
| add or change an endpoint | `04-API/API-Contract.md` |
| touch auth or access checks | `02-Domain/Roles-and-Permissions.md` |
| touch progress, stages, or scoring | `02-Domain/Progress-Calculation.md`, `02-Domain/Construction-Stages.md` |
| touch device auth, pairing, or ingest | `05-Hardware/Device-Pairing-Protocol.md` |
| start a module | `03-Modules/Build-Order.md` + that module's note |

Also check `PENDING.md` (the ranked priority board — what to do next),
`99-Decisions/Progress-Log.md` (top row, where the project actually stands), and
`99-Decisions/ADR-Index.md` before questioning a design choice — it is probably already
argued there.

## Rule 1 — one module at a time

Build in the order given by `03-Modules/Build-Order.md`. Do not skip ahead, and do not
generate several modules in one response. Each module ships all seven artifacts:

1. folder structure · 2. explanation · 3. source code · 4. dependencies · 5. how to run ·
6. testing procedure · 7. expected output

Then stop and wait for confirmation before starting the next module.

## Rule 2 — hard constraints

- **No TensorFlow or Keras.** PyTorch only. This includes transitive dependencies.
- PostgreSQL only (SQLite only inside fast unit tests that don't use Postgres-specific types).
- Image binaries never go in the database — object storage holds them, the DB holds keys.
- No secrets committed. Everything configurable comes from env vars.
- `backend/app/domain/` imports nothing from `infrastructure/`, `api/`, or `torch`.
- `ai/` never imports from `backend/`.
- Progress logic in `ai/src/ai/progress/aggregator.py` stays pure — no I/O, no ORM, no torch.
- Type hints on every Python function; docstrings on every public one; PEP 8 via **ruff**
  (`ruff check` + `ruff format`). **Black is not used** — ruff replaces it (ADR-012).
- TypeScript strict mode on the frontend.

## Rule 2b — established toolchain (Module 01, do not re-litigate)

- **uv** manages both Python projects; `uv.lock` is committed. Run commands as
  `uv run <cmd>` from `backend/` or `ai/`.
- `ai/` is a **src-layout** package: files live at `ai/src/ai/…`, imports stay `ai.…` (ADR-011).
- Backend dependency groups: base (API, **no torch**) · `[worker]` (adds `geovision-ai`) ·
  `[dev]`. Never add torch or OpenCV to the base group.
- Architecture boundaries are enforced by `backend/.importlinter` and
  `backend/tests/unit/test_architecture.py`. Run `uv run lint-imports` before claiming done.
- Task runners: `.\dev.ps1 <task>` on Windows, `make <task>` elsewhere. Adding a task to one
  means adding it to the other.
- Celery: Linux container, or `--pool=solo` locally on Windows (ADR-013).
- Albumentations is **2.x** — its transform signatures differ from 1.x tutorials (ADR-014).

## Rule 3 — keep the vault current

When you finish work:

- update the status table in `03-Modules/Build-Order.md`
- add a row to `99-Decisions/Progress-Log.md`
- record any new design decision in `99-Decisions/ADR-Index.md`
- record any new unknown or deferred item in `99-Decisions/Open-Questions.md`

If code and vault ever disagree, fix the vault first (with an ADR), then the code.

## Project summary

GeoVision is an AI-powered construction monitoring system for an undergraduate Computer
Engineering thesis. An ESP32-CAM captures geotagged site photos on a schedule and uploads
them; the server classifies the construction stage with ResNet18, corroborates with YOLOv8,
computes a smoothed progress percentage, and presents it on a React dashboard with a public
site and an authenticated owner dashboard. Full description: `ARCHITECTURE.md`.
