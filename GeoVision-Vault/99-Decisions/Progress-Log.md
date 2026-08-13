---
title: Progress Log
type: decisions
status: living
updated: 2026-08-12
---

# Progress Log

One line per working session. Newest at the top. This is how a fresh session (human or AI)
learns where things actually stand — [[Build-Order]] holds the status table, this holds the
narrative.

Format: `YYYY-MM-DD · Module · what shipped · what's next / blocked on`

---

| Date | Module | What shipped | Next / blocked |
|---|---|---|---|
| 2026-08-13 | 03 ✅ | **Auth, profiles, and the permission machinery.** Audited the spec first and found 4 security gaps → ADR-015 (token-type separation; a refresh token was usable as an access token), ADR-016 (per-account failed-attempt throttle alongside per-IP), plus `jti` on every token and avatar upload deferred to M04 where storage lives. Also built the pieces Modules 04-16 need: `api/deps.py` as a composition root with all 14 repository providers, `require_permission()` returning a resolved `AccessContext`, an audit logger whose action vocabulary already covers M04/M05, an injectable `Clock`, and a shared pagination schema. **327 tests green.** Three bugs the tests caught: a TYPE_CHECKING-only `User` import made FastAPI silently treat every authenticated caller as anonymous; the per-identifier rate-limit key could never work because slowapi runs its key function before the handler; and `to_public_profile()` redacted the owner's own profile. The import contract also caught `core/exceptions.py` dragging FastAPI into the application layer → ADR-017. | [[Module-04-Projects-and-Folders]]. Docker/MinIO needed for its asset upload. |
| 2026-08-13 | 02 ✅ | **Database schema complete.** Installed PostgreSQL 16 natively on `F:\PostgreSQL\16` (port 5433) rather than waiting on Docker — see [[Local-Environment-Setup]]. Shipped: 20 enums, 4 self-validating value objects, 21 entities, 14 repository Protocols + 14 SQLAlchemy implementations, 18 tables (63 indexes, 26 checks, 29 FKs), a reversible migration, and an idempotent seed (3 users, 4 projects, 2 devices, 60 images, 30 days of snapshots). **198 tests green** (154 unit + 44 integration against real PostgreSQL). Alembic autogenerate had omitted `CREATE EXTENSION` and enum `DROP TYPE`, both of which would have broken CI and any rollback; patched and verified by running upgrade→downgrade→upgrade. Test-caught bug: `Image.build_filename` used `astimezone(tz=None)` (server-local, not UTC), which would have filed every capture into the wrong aggregation window on a Manila-time host. | [[Module-03-Auth-and-Users]]. Docker still needed before Module 05 (Redis/MinIO). |
| 2026-08-13 | 01 ✅ | **Foundation & environment setup complete.** Audited the module spec first, which surfaced 4 blocking design gaps → ADR-011 (packaging topology: `ai` as a src-layout library + 3 backend dependency groups), ADR-012 (uv + committed lockfiles, ruff-only, CPU-pinned torch), ADR-013 (Celery on Windows), ADR-014 (`stringzilla<4`, albumentations 2.x). Shipped: full repo tree, git + remote, `.gitattributes` before first commit, backend Clean-Architecture skeleton with settings/logging/exception envelope, `/health` + `/health/ready`, async Alembic scaffold, 4 enforced import contracts, `ai` package skeleton (torch 2.13+cpu), Vite/React/TS-strict dashboard, dev compose stack with MinIO + Postgres extension bootstrap, CI (6 jobs), `Makefile` + `dev.ps1`, no-TensorFlow guard. **59 tests green** (46 backend / 11 ai / 2 dashboard). Two real bugs caught by the new tests: the app factory ignored injected settings, and `.env` list parsing crashed at startup. | Install **Docker Desktop** (Q9), then [[Module-02-Database-Schema]]. In parallel: answer Q1–Q5, order hardware, start dataset collection. |
| 2026-08-12 | — | Obsidian vault created: full finalized architecture, domain model, progress algorithm, API contract, pairing protocol, 16 module build-specs, ADR-001…010, evaluation and thesis mapping. Root `ARCHITECTURE.md` + `README.md` point here. | Start [[Module-01-Foundation-Setup]]. In parallel: answer Q1–Q5 in [[Open-Questions]], order hardware, begin dataset collection. |

---

## Session hygiene

At the **start** of a session: read [[00-START-HERE]] → the top row of this log → the module
note you are working on.

At the **end** of a session: add a row here, update the status table in [[Build-Order]], and
record any new decision in [[ADR-Index]] or any new unknown in [[Open-Questions]].

## Related
[[00-START-HERE]] · [[Build-Order]] · [[ADR-Index]] · [[Open-Questions]]
