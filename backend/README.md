# `backend/` — GeoVision API

FastAPI service following Clean Architecture. Layer rules are enforced by
`.importlinter` and by `tests/unit/test_architecture.py`, not by convention.

```
app/
├── core/            settings · logging · exceptions   (any layer may import)
├── domain/          entities · enums · repo interfaces · pure rules
├── application/     use cases (one class each)
├── infrastructure/  sqlalchemy · storage · celery · ai adapter · realtime
└── api/             routers · schemas · dependencies
```

**Dependencies point inward only.** `domain/` imports no framework, no ORM,
no torch.

## Install

```bash
cd backend
uv sync --extra dev              # API + tooling (no torch)
uv sync --extra dev --extra worker   # + geovision-ai for the Celery worker
```

The split is deliberate (ADR-011): the API process never imports torch, which
keeps its image ~200 MB rather than ~2.5 GB.

## Run

```bash
uv run uvicorn app.main:app --reload     # http://localhost:8000
uv run pytest                            # tests
uv run pytest -m "not integration"       # unit only, no services needed
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run lint-imports                      # architecture boundaries
uv run alembic upgrade head              # migrations (Module 02+)
```

### Celery on Windows

The default prefork pool does not work on Windows. Locally use
`--pool=solo` (`.\dev.ps1 worker` does this for you); in production the worker
runs in a Linux container with the default pool. See ADR-013.

## Endpoints today

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness — no dependencies touched |
| GET | `/health/ready` | readiness — probes postgres, redis, object storage |
| GET | `/docs` | Swagger UI (disabled in staging/production) |

Full contract: `GeoVision-Vault/04-API/API-Contract.md`.
