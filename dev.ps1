<#
.SYNOPSIS
    GeoVision task runner for Windows (PowerShell).

.DESCRIPTION
    `make` is not installed on Windows by default, so this script mirrors the
    Makefile task-for-task. If you add a task to one, add it to the other.

.EXAMPLE
    .\dev.ps1 help
    .\dev.ps1 setup
    .\dev.ps1 up
    .\dev.ps1 check
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Task = 'help',
    # Only used by deploy-restore: .\dev.ps1 deploy-restore -Dir backups\20260829T120000Z
    [string]$Dir = ''
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
# --env-file is required, not optional: Compose resolves `.env` relative to the
# compose file's directory (docker/), so without it the repo-root .env is never
# read and every ${GV_*:?} variable fails the stack at startup.
$Compose = @('compose', '--env-file', "$Root/.env", '-f', "$Root/docker/docker-compose.dev.yml")
# Module 16's full containerised stack — a separate compose file and a
# separate `deploy-` prefix on every task, deliberately not more `up`/`down`
# names. See the Makefile's DEPLOY_COMPOSE comment for why.
$DeployCompose = @('compose', '--env-file', "$Root/.env", '-f', "$Root/docker/docker-compose.yml")

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "  OK $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  !! $msg" -ForegroundColor Yellow }

function Invoke-In($dir, $exe, $arguments) {
    Push-Location (Join-Path $Root $dir)
    try {
        & $exe @arguments
        if ($LASTEXITCODE -ne 0) { throw "$exe $($arguments -join ' ') failed with exit code $LASTEXITCODE" }
    }
    finally { Pop-Location }
}

function Test-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Warn 'Docker is not installed or not on PATH.'
        Write-Warn 'Install Docker Desktop (WSL2 backend): https://docs.docker.com/desktop/install/windows-install/'
        Write-Warn 'Postgres, Redis and MinIO are required from Module 02 onward.'
        return $false
    }
    return $true
}

switch ($Task.ToLower()) {

    'help' {
        Write-Host ''
        Write-Host 'GeoVision tasks' -ForegroundColor White
        Write-Host ''
        @(
            @('env', 'Create .env and generate secrets'),
            @('setup', 'Install backend + ai + dashboard deps and git hooks'),
            @('dev', 'Start infra + migrate, then api/worker/dashboard in new windows'),
            @('up', 'Start postgres, redis, minio'),
            @('down', 'Stop the dev stack (keeps volumes)'),
            @('logs', 'Tail dev stack logs'),
            @('ps', 'Show dev stack status'),
            @('migrate', 'Apply Alembic migrations'),
            @('seed', 'Load development seed data'),
            @('api', 'Run the FastAPI dev server'),
            @('dashboard', 'Run the Vite dev server'),
            @('worker', 'Run the Celery worker (solo pool on Windows)'),
            @('beat', 'Run the Celery beat scheduler (Module 10 jobs)'),
            @('lint', 'ruff check (backend + ai)'),
            @('fmt', 'ruff format (backend + ai)'),
            @('typecheck', 'mypy + tsc'),
            @('arch', 'Enforce Clean Architecture import boundaries'),
            @('guard', 'Assert the no-TensorFlow constraint'),
            @('test', 'Run every test suite'),
            @('test-unit', 'Backend unit tests only'),
            @('e2e', 'Module 09 end-to-end (API + worker must be up)'),
            @('e2e-ui', 'Playwright visitor + owner journeys (full stack must be up + seeded)'),
            @('load-ingest', 'k6 load test: HMAC-signed ingest (needs a paired device)'),
            @('load-read', 'k6 load test: anonymous feed/project reads'),
            @('cov', 'Backend tests with HTML coverage'),
            @('evaluate', 'Run every AI evaluation artifact currently possible (gv-evaluate)'),
            @('openapi', 'Export documentation/openapi.json from the live FastAPI schema'),
            @('erd', 'Export documentation/erd.mmd from the live SQLAlchemy metadata'),
            @('docs', 'openapi + erd together'),
            @('check', 'Everything CI runs, locally'),
            @('clean', 'Remove caches and build artifacts'),
            @('nuke', 'Stop stack AND DELETE ALL DEV DATA'),
            @('deploy-tls', 'Generate a free self-signed TLS cert for local/demo use'),
            @('deploy-build', 'Build the backend/worker/dashboard images'),
            @('deploy-up', 'Bring up the full containerised stack (build if needed)'),
            @('deploy-down', 'Stop the deployed stack (keeps volumes)'),
            @('deploy-ps', 'Show deployed stack status'),
            @('deploy-logs', 'Tail deployed stack logs'),
            @('deploy-migrate', 'Apply Alembic migrations inside the deployed backend image'),
            @('deploy-seed', 'Load seed data inside the deployed backend image'),
            @('deploy-backup', 'Dump postgres + mirror minio to .\backups\<timestamp>\'),
            @('deploy-restore', 'Restore a backup (pass -Dir <path>)'),
            @('deploy-demo', 'Health-check the deployed stack and print the demo URLs')
        ) | ForEach-Object { '  {0,-14} {1}' -f $_[0], $_[1] }
        Write-Host ''
    }

    'env' {
        Write-Step 'Generating .env'
        & python "$Root/scripts/generate_secrets.py"
    }

    'setup' {
        Write-Step 'Generating .env'
        & python "$Root/scripts/generate_secrets.py"
        Write-Step 'Installing backend dependencies'
        Invoke-In 'backend' 'uv' @('sync', '--extra', 'dev')
        Write-Step 'Installing ai dependencies'
        Invoke-In 'ai' 'uv' @('sync', '--extra', 'dev')
        Write-Step 'Installing dashboard dependencies'
        Invoke-In 'dashboard' 'npm' @('install')
        Write-Step 'Installing git hooks'
        Invoke-In 'backend' 'uv' @('run', 'pre-commit', 'install', '--config', '../.pre-commit-config.yaml')
        Write-Ok 'Setup complete. Next: .\dev.ps1 up'
    }

    'up' {
        if (-not (Test-Docker)) { exit 1 }
        Write-Step 'Starting postgres, redis, minio'
        & docker @Compose up -d
        & docker @Compose ps
    }

    'down' { if (Test-Docker) { & docker @Compose down } }
    'logs' { if (Test-Docker) { & docker @Compose logs -f } }
    'ps' { if (Test-Docker) { & docker @Compose ps } }

    'migrate' {
        Write-Step 'Applying migrations'
        Invoke-In 'backend' 'uv' @('run', 'alembic', 'upgrade', 'head')
    }

    'dev' {
        # Convenience wrapper: bring up infra + migrate in this window, then open
        # api/worker/dashboard each in their own window so their logs stay legible.
        # Equivalent to running `up`, `migrate`, `api`, `worker`, `dashboard` by hand.
        if (-not (Test-Docker)) { exit 1 }
        Write-Step 'Starting postgres, redis, minio'
        & docker @Compose up -d
        & docker @Compose ps
        Write-Step 'Applying migrations'
        Invoke-In 'backend' 'uv' @('run', 'alembic', 'upgrade', 'head')
        Write-Step 'Opening api, worker, dashboard in new windows'
        Start-Process powershell -ArgumentList '-NoExit', '-Command', "cd '$Root'; .\dev.ps1 api"
        Start-Process powershell -ArgumentList '-NoExit', '-Command', "cd '$Root'; .\dev.ps1 worker"
        Start-Process powershell -ArgumentList '-NoExit', '-Command', "cd '$Root'; .\dev.ps1 dashboard"
        Write-Ok 'Started. API http://localhost:8000/docs -- Dashboard http://localhost:5173'
        Write-Warn 'If you use a native (non-Docker) PostgreSQL, make sure it is already running --'
        Write-Warn 'this task does not start it (see README / Local-Environment-Setup.md).'
    }

    'seed' {
        Write-Step 'Seeding database'
        Invoke-In 'backend' 'uv' @('run', 'python', '-m', 'scripts.seed_db')
    }

    'api' {
        Write-Step 'Starting API on http://localhost:8000'
        Invoke-In 'backend' 'uv' @('run', 'uvicorn', 'app.main:app', '--reload', '--port', '8000')
    }

    'dashboard' {
        Write-Step 'Starting Vite on http://localhost:5173'
        Invoke-In 'dashboard' 'npm' @('run', 'dev')
    }

    'worker' {
        # The Celery prefork pool does not work on Windows; --pool=solo is the
        # supported local option. In production the worker runs in a Linux
        # container with the default pool. See ADR-013.
        Write-Step 'Starting Celery worker (solo pool - Windows)'
        Invoke-In 'backend' 'uv' @('run', 'celery', '-A', 'app.worker.celery_app',
            'worker', '-Q', 'ingest,inference,interactive,reports', '-l', 'info', '--pool=solo')
    }

    'beat' {
        # The scheduler only publishes; a worker must be running to do the work.
        Write-Step 'Starting Celery beat (status refresh, remarks, offline sweep, cleanup)'
        Invoke-In 'backend' 'uv' @('run', 'celery', '-A', 'app.worker.celery_app', 'beat', '-l', 'info')
    }

    'lint' {
        Invoke-In 'backend' 'uv' @('run', 'ruff', 'check', '.')
        Invoke-In 'ai' 'uv' @('run', 'ruff', 'check', '.')
        Write-Ok 'lint clean'
    }

    'fmt' {
        Invoke-In 'backend' 'uv' @('run', 'ruff', 'format', '.')
        Invoke-In 'ai' 'uv' @('run', 'ruff', 'format', '.')
        Write-Ok 'formatted'
    }

    'typecheck' {
        Invoke-In 'backend' 'uv' @('run', 'mypy', 'app')
        if (Test-Path (Join-Path $Root 'dashboard/node_modules')) {
            Invoke-In 'dashboard' 'npm' @('run', 'typecheck')
        }
        else { Write-Warn 'dashboard/node_modules missing - run .\dev.ps1 setup' }
        Write-Ok 'types clean'
    }

    'arch' {
        Invoke-In 'backend' 'uv' @('run', 'lint-imports')
        Write-Ok 'architecture boundaries respected'
    }

    'guard' { & python "$Root/scripts/check_no_tensorflow.py" }

    'test' {
        Invoke-In 'backend' 'uv' @('run', 'pytest')
        Invoke-In 'ai' 'uv' @('run', 'pytest')
    }

    'test-unit' { Invoke-In 'backend' 'uv' @('run', 'pytest', '-m', 'not integration') }
    'test-integration' { Invoke-In 'backend' 'uv' @('run', 'pytest', '-m', 'integration') }
    'test-ai' { Invoke-In 'ai' 'uv' @('run', 'pytest') }
    'e2e' {
        # Needs the API and a worker already running - it drives real HTTP
        # against live services rather than an in-process app.
        Write-Step 'Module 09 end-to-end (API + worker must be up)'
        Invoke-In 'backend' 'uv' @('run', 'python', '-m', 'scripts.e2e_module09')
    }

    'e2e-ui' {
        # Needs the full stack up (.\dev.ps1 dev) AND a freshly seeded
        # database (.\dev.ps1 seed) - the journeys below assert against the
        # exact seeded users/projects in scripts/seed_db.py.
        #
        # PLAYWRIGHT_BROWSERS_PATH keeps the downloaded browser inside the
        # repo (.cache/ms-playwright) rather than %LOCALAPPDATA% - every tool
        # this project needs lives on whichever drive the repo was cloned to.
        $env:PLAYWRIGHT_BROWSERS_PATH = "$Root/.cache/ms-playwright"
        Write-Step 'Playwright: visitor + owner journeys'
        if (-not (Test-Path (Join-Path $Root 'tests/e2e/node_modules'))) {
            Invoke-In 'tests/e2e' 'npm' @('install')
        }
        if (-not (Test-Path $env:PLAYWRIGHT_BROWSERS_PATH)) {
            Write-Step 'Downloading the Playwright browser (first run only)'
            Invoke-In 'tests/e2e' 'npx' @('playwright', 'install', 'chromium')
        }
        Invoke-In 'tests/e2e' 'npx' @('playwright', 'test')
    }

    'load-ingest' {
        # Needs a paired device - set GV_DEVICE_ID / GV_DEVICE_SECRET first
        # (see the docstring in tests/load/ingest.js for how to get them).
        # Custom --vus/--duration/-e flags: invoke .tools/k6/k6.exe directly.
        if (-not (Test-Path "$Root/.tools/k6/k6.exe")) {
            Write-Warn '.tools/k6/k6.exe not found - see Local-Environment-Setup.md to install it.'
            exit 1
        }
        Write-Step 'k6: ingest load test (5 VUs, 30s)'
        & "$Root/.tools/k6/k6.exe" run "$Root/tests/load/ingest.js" --vus 5 --duration 30s
    }

    'load-read' {
        # Custom --vus/--duration flags: invoke .tools/k6/k6.exe directly.
        if (-not (Test-Path "$Root/.tools/k6/k6.exe")) {
            Write-Warn '.tools/k6/k6.exe not found - see Local-Environment-Setup.md to install it.'
            exit 1
        }
        Write-Step 'k6: anonymous read-path load test (20 VUs, 30s)'
        & "$Root/.tools/k6/k6.exe" run "$Root/tests/load/api-read.js" --vus 20 --duration 30s
    }

    'cov' {
        Invoke-In 'backend' 'uv' @('run', 'pytest', '--cov=app', '--cov-report=html', '--cov-report=term-missing')
        Write-Ok 'Report: backend/htmlcov/index.html'
    }

    'evaluate' {
        Write-Step 'Running every AI evaluation artifact currently possible'
        Invoke-In 'ai' 'uv' @('run', 'gv-evaluate')
    }

    'openapi' {
        Invoke-In 'backend' 'uv' @('run', 'python', '-m', 'scripts.export_openapi')
    }

    'erd' {
        Invoke-In 'backend' 'uv' @('run', 'python', '-m', 'scripts.export_erd')
    }

    'docs' {
        Invoke-In 'backend' 'uv' @('run', 'python', '-m', 'scripts.export_openapi')
        Invoke-In 'backend' 'uv' @('run', 'python', '-m', 'scripts.export_erd')
    }

    'check' {
        & python "$Root/scripts/check_no_tensorflow.py"
        Invoke-In 'backend' 'uv' @('run', 'ruff', 'check', '.')
        Invoke-In 'ai' 'uv' @('run', 'ruff', 'check', '.')
        Invoke-In 'backend' 'uv' @('run', 'mypy', 'app')
        Invoke-In 'backend' 'uv' @('run', 'lint-imports')
        # --cov is what actually enforces the fail_under thresholds in
        # backend/pyproject.toml and ai/pyproject.toml - a plain `pytest`
        # with no --cov flag collects no coverage and enforces nothing, so
        # `check` would otherwise silently pass a build CI would fail.
        Invoke-In 'backend' 'uv' @('run', 'pytest', '--cov=app', '--cov-report=term-missing')
        Invoke-In 'ai' 'uv' @('run', 'pytest', '--cov=ai', '--cov-report=term-missing')
        Write-Ok 'all checks passed'
    }

    'clean' {
        Write-Step 'Removing caches'
        foreach ($pattern in @('__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache')) {
            Get-ChildItem -Path $Root -Filter $pattern -Recurse -Directory -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notmatch '\\(node_modules|\.venv|\.git)\\' } |
            ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
        }
        foreach ($p in @('backend/htmlcov', 'backend/.coverage', 'backend/coverage.xml', 'dashboard/dist')) {
            $full = Join-Path $Root $p
            if (Test-Path $full) { Remove-Item $full -Recurse -Force }
        }
        Write-Ok 'clean'
    }

    'nuke' {
        if (-not (Test-Docker)) { exit 1 }
        Write-Warn 'This deletes ALL local dev data (postgres + minio volumes).'
        $confirm = Read-Host 'Type DELETE to confirm'
        if ($confirm -ceq 'DELETE') {
            & docker @Compose down -v
            Write-Ok 'Volumes removed. Next: .\dev.ps1 up; .\dev.ps1 migrate'
        }
        else { Write-Host 'Aborted.' }
    }

    'deploy-tls' {
        New-Item -ItemType Directory -Force -Path "$Root/docker/certs" | Out-Null
        & openssl req -x509 -nodes -days 825 -newkey rsa:2048 `
            -keyout "$Root/docker/certs/privkey.pem" -out "$Root/docker/certs/fullchain.pem" `
            -subj "/CN=localhost" `
            -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
        Write-Ok 'Wrote docker/certs/{fullchain,privkey}.pem -- gitignored, self-signed, browsers will warn once.'
    }

    'deploy-build' { if (Test-Docker) { & docker @DeployCompose build } }

    'deploy-up' {
        if (-not (Test-Docker)) { exit 1 }
        if (-not (Test-Path "$Root/docker/certs/fullchain.pem")) { & $PSCommandPath deploy-tls }
        & docker @DeployCompose up -d --build
        Write-Step 'Waiting for services to report healthy...'
        & docker @DeployCompose ps
    }

    'deploy-down' { if (Test-Docker) { & docker @DeployCompose down } }
    'deploy-ps' { if (Test-Docker) { & docker @DeployCompose ps } }
    'deploy-logs' { if (Test-Docker) { & docker @DeployCompose logs -f } }

    'deploy-migrate' {
        # No `uv run` prefix -- the runtime image ships only the built .venv,
        # not the uv tool itself (uv is only ever needed to BUILD the image).
        Write-Step 'Applying migrations inside the deployed backend image'
        & docker @DeployCompose run --rm --no-deps backend alembic upgrade head
    }

    'deploy-seed' {
        Write-Step 'Seeding the deployed database'
        & docker @DeployCompose run --rm --no-deps backend python -m scripts.seed_db
    }

    'deploy-backup' { & python "$Root/scripts/backup.py" }

    'deploy-restore' {
        if (-not $Dir) {
            Write-Host 'Usage: .\dev.ps1 deploy-restore -Dir backups\20260829T120000Z' -ForegroundColor Red
            exit 1
        }
        & python "$Root/scripts/restore.py" $Dir
    }

    'deploy-demo' {
        Write-Step 'Checking every service is healthy...'
        & docker @DeployCompose ps
        Write-Host ''
        Write-Ok 'Dashboard:  https://localhost'
        Write-Ok 'Health:     https://localhost/health/ready'
        Write-Host ''
        Write-Host 'Walk through documentation/DEMO.md next.'
    }

    default {
        Write-Host "Unknown task '$Task'. Run '.\dev.ps1 help' for the list." -ForegroundColor Red
        exit 1
    }
}
