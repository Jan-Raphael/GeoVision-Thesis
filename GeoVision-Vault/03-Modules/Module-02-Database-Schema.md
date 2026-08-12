---
title: Module 02 — Database Schema & Migrations
type: module
module: 2
status: planned
updated: 2026-08-12
---

# Module 02 — Database Schema, Models & Repositories

## Scope
Every table in [[Domain-Model]], the SQLAlchemy layer, the repository interfaces, and seed
data. **No HTTP endpoints in this module.**

## Deliverables
- `domain/enums.py` — every enum from [[Domain-Model]], as `StrEnum`. Single definition site.
- `domain/entities/` — frozen dataclasses (`User`, `Project`, `Device`, `Image`,
  `Prediction`, `ProgressSnapshot`, …), pure Python, no ORM imports.
- `domain/value_objects.py` — `ProjectCode` (validates `^[A-Z]{2,5}_[0-9]{2}$`), `GeoPoint`
  (validates lat/lon ranges), `ProgressPct` (0–100, 2 dp), `Confidence` (0–1).
  Validation lives in the constructor; invalid states are unrepresentable.
- `domain/repositories/` — abstract base classes: `UserRepository`, `ProjectRepository`,
  `MemberRepository`, `DeviceRepository`, `ImageRepository`, `PredictionRepository`,
  `SnapshotRepository`, `RemarkRepository`, `ReportRepository`, `ModelRepository`.
  Methods named for intent (`list_public_feed`, `find_by_project_code`), not for SQL.
- `infrastructure/db/models.py` — SQLAlchemy 2.0 declarative models + all indexes/constraints.
- `infrastructure/db/session.py` — async engine, `async_sessionmaker`, `get_session` DI.
- `infrastructure/repositories/` — one concrete implementation per interface, plus mappers
  ORM ↔ entity.
- `alembic/versions/m02_initial_schema.py` — enums, `pgcrypto`, `citext`, tables, indexes.
- `scripts/seed_db.py` — 3 users (public/private profiles), 4 projects (public/private,
  various statuses), 2 devices, ~40 images with predictions and 30 days of snapshots.
  **The dashboard is built against this seed**, so it must look realistic.

## Critical implementation notes
- `TIMESTAMPTZ` everywhere; the app never stores naive datetimes.
- Partial unique index: one `is_active` model per `kind` in `ai_models`.
- Unique `(project_id, sha256)` on `images` for ingest idempotency.
- Unique `(project_id, face)` on `devices`; unique `(project_id, window_start)` on snapshots.
- `ON DELETE CASCADE` from `projects` to its children; `RESTRICT` on `users` (never
  hard-delete a user with projects — deactivate).
- Trigram (`pg_trgm`) indexes on `projects.name`, `projects.location_label`,
  `users.username`, `users.full_name` for the search endpoint.
- **Visibility-scoped repository methods** (`list_public_feed`, `get_public_by_code`) that
  filter in SQL — see [[Domain-Model]] §Visibility enforcement.

## Dependencies
Module 01. `asyncpg`, `sqlalchemy[asyncio]`, `alembic`.

## How to run
```bash
cd backend
alembic upgrade head
python -m scripts.seed_db
psql $DATABASE_URL -c '\dt'
```

## Testing procedure
1. `alembic upgrade head` then `alembic downgrade base` then `upgrade head` again — clean both ways.
2. Unit tests for value objects: reject `ng_00`, `NG_0`, `NG_000`, lat `95.0`, progress `101`.
3. Integration tests (real Postgres) per repository: create/read/update/list.
4. Constraint tests: duplicate `project_code` → IntegrityError; duplicate `(project_id, face)` → IntegrityError; duplicate `(project_id, sha256)` → IntegrityError.
5. Visibility test: `list_public_feed()` never returns a private project.
6. Cascade test: deleting a project removes its images, predictions, snapshots.

## Expected output
`\dt` lists all ~16 tables; seed produces a browsable dataset; every repository test passes
against real PostgreSQL.

## Done criteria
- [ ] Every table in [[Domain-Model]] exists with its indexes and constraints
- [ ] Migration is reversible
- [ ] All repositories implemented + tested
- [ ] Seed data present and realistic
- [ ] `domain/` imports nothing from `infrastructure/`, `api/`, or `torch` (enforced by an import-linter test)

## Related
[[Domain-Model]] · [[Naming-Conventions]] · [[Module-03-Auth-and-Users]]
