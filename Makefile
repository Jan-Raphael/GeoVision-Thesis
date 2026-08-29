# GeoVision — task runner (Linux / macOS / WSL / CI)
#
# Windows users: `make` is not installed by default. Use the PowerShell
# equivalent instead, which supports the same task names:
#     .\dev.ps1 <task>
# Both files must be kept in step; if you add a task here, add it there too.

.DEFAULT_GOAL := help
.PHONY: help setup env up down logs ps migrate seed dev worker beat api dashboard \
        lint fmt typecheck arch test test-unit test-integration test-ai e2e e2e-ui cov \
        load-ingest load-read evaluate openapi erd docs check guard clean nuke \
        deploy-build deploy-up deploy-down deploy-ps deploy-logs deploy-migrate \
        deploy-seed deploy-backup deploy-restore deploy-tls deploy-demo

# --env-file is required, not optional: Compose resolves `.env` relative to the
# directory of the compose file (docker/), so without this it never finds the
# repo-root .env and every ${GV_*:?} variable fails the stack at startup.
# Note we do NOT pass --project-directory, because the relative bind mount
# ./postgres/init must keep resolving against docker/.
COMPOSE := docker compose --env-file .env -f docker/docker-compose.dev.yml

# Module 16's full containerised stack (nginx + backend + worker + beat +
# dashboard, on top of postgres/redis/minio) — a SEPARATE compose file and a
# separate `deploy-` prefix on every task, not more `up`/`down`/`migrate`
# names. The two stacks answer different questions ("is my code running with
# hot reload" vs "does the packaged system boot on a clean machine") and
# giving them the same task names would make every `make up` ambiguous about
# which one it started. See Progress-Log, 2026-08-29.
DEPLOY_COMPOSE := docker compose --env-file .env -f docker/docker-compose.yml

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
dev: up migrate ## Start infra + migrate, then run api + worker + dashboard together (Ctrl+C stops all)
	@echo "Starting api, worker, dashboard -- Ctrl+C stops all three"
	@echo "If you use a native (non-Docker) PostgreSQL, make sure it is already running."
	@trap 'kill 0' EXIT INT TERM; \
	( cd backend   && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 ) & \
	( cd backend   && uv run celery -A app.worker.celery_app worker -Q ingest,inference,interactive,reports -l info ) & \
	( cd dashboard && npm run dev ) & \
	wait

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

e2e-ui: ## Playwright visitor + owner journeys (full stack must be up + seeded)
	cd tests/e2e && [ -d node_modules ] || npm install
	# Kept inside the repo (.cache/ms-playwright), not the user's home
	# directory - every tool this project needs lives on whichever drive
	# the repo was cloned to.
	PLAYWRIGHT_BROWSERS_PATH=$(CURDIR)/.cache/ms-playwright \
		bash -c '[ -d "$$PLAYWRIGHT_BROWSERS_PATH" ] || (cd tests/e2e && npx playwright install chromium)'
	cd tests/e2e && PLAYWRIGHT_BROWSERS_PATH=$(CURDIR)/.cache/ms-playwright npx playwright test

# k6 on Linux/macOS/WSL is a normal system package (apt/brew install k6) -
# unlike the Windows path, there is no C:\-vs-F:\ reason to vendor a binary
# here, so this expects `k6` on PATH.
load-ingest: ## k6 load test: HMAC-signed ingest (needs a paired device - see tests/load/ingest.js)
	k6 run tests/load/ingest.js --vus 5 --duration 30s

load-read: ## k6 load test: anonymous feed/project reads
	k6 run tests/load/api-read.js --vus 20 --duration 30s

test-ai: ## AI package tests
	cd ai && uv run pytest

cov: ## Backend tests with an HTML coverage report
	cd backend && uv run pytest --cov=app --cov-report=html --cov-report=term-missing
	@echo "Report: backend/htmlcov/index.html"

## ---------------------------------------------------------------------------
## AI evaluation & documentation exports
## ---------------------------------------------------------------------------
evaluate: ## Run every AI evaluation artifact currently possible (gv-evaluate)
	cd ai && uv run gv-evaluate

openapi: ## Export documentation/openapi.json from the live FastAPI schema
	cd backend && uv run python -m scripts.export_openapi

erd: ## Export documentation/erd.mmd from the live SQLAlchemy metadata
	cd backend && uv run python -m scripts.export_erd

docs: openapi erd ## openapi + erd together

check: guard lint typecheck arch ## Everything CI runs, locally
	# --cov is what actually enforces the fail_under thresholds in
	# backend/pyproject.toml and ai/pyproject.toml; a plain `pytest` with no
	# --cov flag collects no coverage and enforces nothing.
	cd backend && uv run pytest --cov=app --cov-report=term-missing
	cd ai      && uv run pytest --cov=ai --cov-report=term-missing

## ---------------------------------------------------------------------------
## Deployment (Module 16) -- the full containerised stack, not dev
## ---------------------------------------------------------------------------
deploy-tls: ## Generate a free self-signed TLS cert for local/demo use (see DEPLOYMENT.md for a real domain)
	mkdir -p docker/certs
	openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
		-keyout docker/certs/privkey.pem -out docker/certs/fullchain.pem \
		-subj "/CN=localhost" \
		-addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
	@echo "Wrote docker/certs/{fullchain,privkey}.pem -- gitignored, self-signed, browsers will warn once."

deploy-build: ## Build the backend/worker/dashboard images
	$(DEPLOY_COMPOSE) build

deploy-up: ## Bring up the full containerised stack (build if needed)
	@test -f docker/certs/fullchain.pem || $(MAKE) deploy-tls
	$(DEPLOY_COMPOSE) up -d --build
	@echo "Waiting for services to report healthy..."
	$(DEPLOY_COMPOSE) ps

deploy-down: ## Stop the deployed stack (keeps volumes)
	$(DEPLOY_COMPOSE) down

deploy-ps: ## Show deployed stack status
	$(DEPLOY_COMPOSE) ps

deploy-logs: ## Tail deployed stack logs
	$(DEPLOY_COMPOSE) logs -f

deploy-migrate: ## Apply Alembic migrations inside the deployed backend image
	# No `uv run` prefix: the runtime image ships only the built .venv, not the
	# uv tool itself (found running this for real — uv is only ever needed to
	# BUILD the image). alembic/python are already on PATH from the venv.
	$(DEPLOY_COMPOSE) run --rm --no-deps backend alembic upgrade head

deploy-seed: ## Load seed data inside the deployed backend image
	$(DEPLOY_COMPOSE) run --rm --no-deps backend python -m scripts.seed_db

deploy-backup: ## Dump postgres + mirror the minio bucket to ./backups/<timestamp>/
	python scripts/backup.py

deploy-restore: ## Restore a backup: make deploy-restore DIR=backups/20260829T120000Z
	python scripts/restore.py $(DIR)

deploy-demo: ## Health-check the deployed stack and print the defense-demo URLs
	@echo "Checking every service is healthy..."
	$(DEPLOY_COMPOSE) ps
	@echo ""
	@echo "Dashboard:  https://localhost"
	@echo "API docs:   disabled in staging/production by design (see Settings.docs_url)"
	@echo "Health:     https://localhost/health/ready"
	@echo ""
	@echo "Walk through documentation/DEMO.md next."

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
