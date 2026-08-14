# GeoVision — task runner (Linux / macOS / WSL / CI)
#
# Windows users: `make` is not installed by default. Use the PowerShell
# equivalent instead, which supports the same task names:
#     .\dev.ps1 <task>
# Both files must be kept in step; if you add a task here, add it there too.

.DEFAULT_GOAL := help
.PHONY: help setup env up down logs ps migrate seed dev worker beat api dashboard \
        lint fmt typecheck arch test test-unit test-integration test-ai e2e cov \
        check guard clean nuke

# --env-file is required, not optional: Compose resolves `.env` relative to the
# directory of the compose file (docker/), so without this it never finds the
# repo-root .env and every ${GV_*:?} variable fails the stack at startup.
# Note we do NOT pass --project-directory, because the relative bind mount
# ./postgres/init must keep resolving against docker/.
COMPOSE := docker compose --env-file .env -f docker/docker-compose.dev.yml

## ---------------------------------------------------------------------------
## Help
## ---------------------------------------------------------------------------
help: ## Show available tasks
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

## ---------------------------------------------------------------------------
## Setup
## ---------------------------------------------------------------------------
env: ## Create .env from the template and generate secrets
	python scripts/generate_secrets.py

setup: env ## Install every dependency (backend, ai, dashboard) and git hooks
	cd backend   && uv sync --extra dev
	cd ai        && uv sync --extra dev
	cd dashboard && npm install
	cd backend   && uv run pre-commit install --config ../.pre-commit-config.yaml
	@echo "Setup complete. Next: make up && make migrate"

## ---------------------------------------------------------------------------
## Infrastructure
## ---------------------------------------------------------------------------
up: ## Start postgres, redis, minio
	$(COMPOSE) up -d
	@echo "Waiting for services to report healthy..."
	@$(COMPOSE) ps

down: ## Stop the dev stack (keeps volumes)
	$(COMPOSE) down

logs: ## Tail dev stack logs
	$(COMPOSE) logs -f

ps: ## Show dev stack status
	$(COMPOSE) ps

## ---------------------------------------------------------------------------
## Database (Module 02 onward)
## ---------------------------------------------------------------------------
migrate: ## Apply all Alembic migrations
	cd backend && uv run alembic upgrade head

seed: ## Load development seed data
	cd backend && uv run python -m scripts.seed_db

## ---------------------------------------------------------------------------
## Run
## ---------------------------------------------------------------------------
api: ## Run the FastAPI dev server
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dashboard: ## Run the Vite dev server
	cd dashboard && npm run dev

worker: ## Run the Celery worker (Module 09+)
	cd backend && uv run celery -A app.worker.celery_app worker \
		-Q ingest,inference,interactive,reports -l info

beat: ## Run the Celery beat scheduler (status refresh, remarks, sweep, cleanup)
	cd backend && uv run celery -A app.worker.celery_app beat -l info

## ---------------------------------------------------------------------------
## Quality
## ---------------------------------------------------------------------------
lint: ## ruff check (backend + ai)
	cd backend && uv run ruff check .
	cd ai      && uv run ruff check .

fmt: ## ruff format (backend + ai)
	cd backend && uv run ruff format .
	cd ai      && uv run ruff format .

typecheck: ## mypy on the backend + tsc on the dashboard
	cd backend   && uv run mypy app
	cd dashboard && npm run typecheck

arch: ## Enforce Clean Architecture import boundaries
	cd backend && uv run lint-imports

guard: ## Assert the no-TensorFlow constraint holds
	python scripts/check_no_tensorflow.py

## ---------------------------------------------------------------------------
## Tests
## ---------------------------------------------------------------------------
test: ## Run every test suite
	cd backend && uv run pytest
	cd ai      && uv run pytest

test-unit: ## Backend unit tests only (no services required)
	cd backend && uv run pytest -m "not integration"

test-integration: ## Backend integration tests (needs `make up`)
	cd backend && uv run pytest -m integration

e2e: ## Module 09 end-to-end against live services (API + worker must be up)
	cd backend && uv run python -m scripts.e2e_module09

test-ai: ## AI package tests
	cd ai && uv run pytest

cov: ## Backend tests with an HTML coverage report
	cd backend && uv run pytest --cov=app --cov-report=html --cov-report=term-missing
	@echo "Report: backend/htmlcov/index.html"

check: guard lint typecheck arch test ## Everything CI runs, locally

## ---------------------------------------------------------------------------
## Cleanup
## ---------------------------------------------------------------------------
clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/htmlcov backend/.coverage backend/coverage.xml dashboard/dist

nuke: down ## Stop the stack AND DELETE ALL DEV DATA (destructive)
	$(COMPOSE) down -v
	@echo "All dev volumes removed. Re-run: make up && make migrate && make seed"
