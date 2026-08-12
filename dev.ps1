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
    [string]$Task = 'help'
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Compose = @('compose', '-f', "$Root/docker/docker-compose.dev.yml")

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
            @('up', 'Start postgres, redis, minio'),
            @('down', 'Stop the dev stack (keeps volumes)'),
            @('logs', 'Tail dev stack logs'),
            @('ps', 'Show dev stack status'),
            @('migrate', 'Apply Alembic migrations'),
            @('seed', 'Load development seed data'),
            @('api', 'Run the FastAPI dev server'),
            @('dashboard', 'Run the Vite dev server'),
            @('worker', 'Run the Celery worker (solo pool on Windows)'),
            @('lint', 'ruff check (backend + ai)'),
            @('fmt', 'ruff format (backend + ai)'),
            @('typecheck', 'mypy + tsc'),
            @('arch', 'Enforce Clean Architecture import boundaries'),
            @('guard', 'Assert the no-TensorFlow constraint'),
            @('test', 'Run every test suite'),
            @('test-unit', 'Backend unit tests only'),
            @('cov', 'Backend tests with HTML coverage'),
            @('check', 'Everything CI runs, locally'),
            @('clean', 'Remove caches and build artifacts'),
            @('nuke', 'Stop stack AND DELETE ALL DEV DATA')
        ) | ForEach-Object { '  {0,-12} {1}' -f $_[0], $_[1] }
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
        Invoke-In 'backend' 'uv' @('run', 'celery', '-A', 'app.infrastructure.tasks.celery_app',
            'worker', '-Q', 'ingest,inference,reports', '-l', 'info', '--pool=solo')
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

    'cov' {
        Invoke-In 'backend' 'uv' @('run', 'pytest', '--cov=app', '--cov-report=html', '--cov-report=term-missing')
        Write-Ok 'Report: backend/htmlcov/index.html'
    }

    'check' {
        & python "$Root/scripts/check_no_tensorflow.py"
        Invoke-In 'backend' 'uv' @('run', 'ruff', 'check', '.')
        Invoke-In 'ai' 'uv' @('run', 'ruff', 'check', '.')
        Invoke-In 'backend' 'uv' @('run', 'mypy', 'app')
        Invoke-In 'backend' 'uv' @('run', 'lint-imports')
        Invoke-In 'backend' 'uv' @('run', 'pytest')
        Invoke-In 'ai' 'uv' @('run', 'pytest')
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

    default {
        Write-Host "Unknown task '$Task'. Run '.\dev.ps1 help' for the list." -ForegroundColor Red
        exit 1
    }
}
