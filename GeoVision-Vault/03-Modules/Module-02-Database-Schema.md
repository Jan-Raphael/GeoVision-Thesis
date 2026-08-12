---
title: Module 02 — Database Schema & Migrations
type: module
module: 2
status: done
started: 2026-08-13
finished: 2026-08-13
updated: 2026-08-13
---

# Module 02 — Database Schema, Models & Repositories

> **Status: ✅ done.** Revised after implementation to describe what exists.
> Built against a **native PostgreSQL 16 install on `F:\PostgreSQL\16`, port 5433**
> — Docker Desktop was deferred (see [[Local-Environment-Setup]] and Q9 in [[Open-Questions]]).

## Scope
Every table in [[Domain-Model]], the SQLAlchemy layer, repository interfaces and
implementations, and seed data. **No HTTP endpoints** — those start in Module 03.

---

## What shipped

### Domain layer (pure Python — no ORM, no framework, no torch)
| File | Contents |
|---|---|
| `domain/enums.py` | **20 enums**, the single definition site. `CameraFace` and `MacroStage` carry derived behaviour (`.code`, `.default_weight`, `.floor_pct`) so the mapping rules live with the values. |
| `domain/value_objects.py` | `ProjectCode`, `GeoPoint`, `ProgressPct`, `Confidence` — self-validating, so **an invalid instance cannot exist**. |
| `domain/entities/` | 21 frozen dataclasses across `user · project · device · image · system`. |
| `domain/repositories/` | 14 repository **Protocols** — structural typing, so a test fake needs no inheritance. |

Two design points worth defending at the panel:

- **`ProgressPct` and `Confidence` are separate types.** One is 0–100, the other 0–1. Mixing
  them would silently corrupt every progress number in the system; separate types turn that
  mistake into a `TypeError`. `ProgressPct` is `Decimal`-backed because progress values are
  summed, averaged, and compared against thresholds, and `0.1 + 0.2 != 0.3` is not a property
  you want in a figure a user reads as authoritative.
- **`User.to_public_profile()` does the redaction structurally.** A private account returns a
  `PublicProfile` whose other fields are `None` by construction, so a newly added field cannot
  leak by somebody forgetting to filter it.

### Infrastructure
| File | Contents |
|---|---|
| `infrastructure/db/base.py` | Declarative base + **constraint naming convention** (without it Alembic cannot reliably drop what PostgreSQL auto-named, and `downgrade()` breaks months later). |
| `infrastructure/db/models.py` | **18 tables**, native PG enums, 63 indexes, 26 check constraints, 29 foreign keys. |
| `infrastructure/db/session.py` | Async engine + request-scoped session; commit on success, rollback on exception. |
| `infrastructure/repositories/` | 14 implementations + `mappers.py` (ORM ↔ entity) + `_result.py` typing helpers. |
| `alembic/versions/…_m02_initial_schema.py` | The initial schema, **hand-patched** — see below. |
| `scripts/seed_db.py` | Idempotent seed: 3 users, 4 projects, 2 devices, 60 images with predictions, 30 days of snapshots. |

### Constraints that encode the thesis's safety property

```sql
CHECK (progress_pct <= 80 OR approval_state = 'approved')
```

The AI cannot push a project past 80 % — the last 20 % requires a human inspection (ADR-007).
It is asserted in the entity, in the use case, **and in the schema**, so no future code path
can bypass it.

---

## Two things Alembic got wrong (and how they were fixed)

Autogenerate produced 1,139 lines and got the tables right, but silently omitted two things
that would have failed later, in CI, in a confusing way:

1. **No `CREATE EXTENSION`.** The Docker init scripts create `pgcrypto`/`citext`/`pg_trgm`/
   `btree_gin`, but **CI uses a bare postgres service container and a native Windows install
   has no init hooks at all**. Without the extensions, `gen_random_uuid()` does not exist and
   every table creation fails. The migration now creates them itself.
2. **No `DROP TYPE` on downgrade.** Native enum types outlive their tables, so
   `downgrade` → `upgrade` failed with *"type already exists"*. The migration now drops all 19
   explicitly. Extensions are deliberately **not** dropped — they may be shared with other
   schemas in the same database.

Verified by actually running `upgrade → downgrade → upgrade` against PostgreSQL, not by
reading the file.

---

## Dependencies
Module 01, plus a running PostgreSQL 16 ([[Local-Environment-Setup]]).

## How to run

```powershell
uv run alembic upgrade head          # apply the schema
uv run python -m scripts.seed_db     # load development data
uv run pytest                        # 198 tests
uv run pytest -m "not integration"   # 154 unit tests, no database needed
```

## Testing procedure & results

| # | Check | Result |
|---|---|---|
| 1 | `upgrade` → `downgrade base` → `upgrade` | ✅ clean round trip |
| 2 | Value-object validation (codes, coordinates, ranges) | ✅ 60 unit tests |
| 3 | Entity invariants + stage breakdown | ✅ 94 unit tests |
| 4 | Repository CRUD against real PostgreSQL | ✅ |
| 5 | Unique constraints (code, username, `(project,face)`, `(project,sha256)`) | ✅ |
| 6 | **Public feed never returns a private project** | ✅ |
| 7 | **`get_public_by_code` returns `None` for private** (⇒ 404, not 403) | ✅ |
| 8 | **Private profile lookup returns nothing but the username** | ✅ |
| 9 | Cascade delete removes devices + images | ✅ |
| 10 | User with projects **cannot** be hard-deleted (`RESTRICT`) | ✅ |
| 11 | Machine-ceiling check constraint rejects 95 % without approval | ✅ |
| 12 | Only one active model per kind (partial unique index) | ✅ |
| 13 | Race-free daily sequence allocation (advisory lock) | ✅ |
| 14 | `domain/` imports nothing from `infrastructure/`/`api/`/torch | ✅ 4 contracts kept |

## Expected output

```
198 passed          (154 unit + 44 integration)
ruff · mypy · lint-imports  clean
tables: 18 · enum types: 19 · indexes: 63 · checks: 26 · foreign keys: 29
```

---

## Bugs the tests caught

**`Image.build_filename` stamped the wrong time.** The first implementation used
`captured_at.astimezone(tz=None)`, which converts to the **server's local zone** while the
filename still ends in `Z`. On a Manila-time host every capture would have been named eight
hours late — and since `captured_at` drives the aggregation window
([[Progress-Calculation]]), captures would have been filed into the wrong day. Fixed to
convert explicitly to UTC, with a regression test using a `+08:00` timestamp.

This is a good example of why the filename builder is a **pure function in the domain layer**:
it was testable without a database, a device, or an image.

Also caught: two async plugins (`pytest-asyncio` auto mode plus `anyio` marks) double-driving
the same tests, and a session-scoped engine used from per-test event loops
(*"another operation is in progress"*). Both fixed in `pyproject.toml` /
`tests/integration/conftest.py`.

## Done criteria

- [x] All 18 tables with indexes and constraints
- [x] Migration reversible, **verified by running it**
- [x] 14 repositories implemented + tested against real PostgreSQL
- [x] Seed data realistic enough to build Modules 11–12 against
- [x] `domain/` purity enforced by import-linter **and** unit tests
- [x] Visibility rules proven in SQL, not just in the UI

## Related
[[Domain-Model]] · [[Naming-Conventions]] · [[Local-Environment-Setup]] · [[Module-03-Auth-and-Users]]
