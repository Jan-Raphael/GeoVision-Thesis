# GeoVision — API image (Module 16).
#
# Build context is the REPO ROOT, not backend/ — see docker-compose.yml. That's
# what lets `COPY backend/...` and `COPY ai/...` both work from one Dockerfile,
# which this image needs only for `uv.lock` to resolve consistently (it does
# NOT install ai/, see below).
#
# Base dependency group only (ADR-011): no torch, no OpenCV. The worker image
# (docker/worker.Dockerfile) is the one that installs `geovision-ai`. Splitting
# them is what keeps this image a few hundred MB instead of several GB, and what
# makes "the API process never imports torch" true by omission rather than by
# convention someone has to remember.
#
# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv

WORKDIR /app

# ai/ is never installed into this image (base group has no dependency on
# geovision-ai) but `uv sync --locked` still validates every path source the
# lockfile references, including the [worker]/[dev] extras' `../ai` this
# image never selects — so the directory has to exist during the build even
# though it never reaches the runtime stage. Found the hard way building
# Module 16: without this, sync fails with "Distribution not found at:
# file:///app/ai" despite requesting neither extra.
COPY ai/ ai/

# Dependencies first, so editing app code doesn't invalidate this layer.
COPY backend/pyproject.toml backend/uv.lock backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd backend && uv sync --locked --no-install-project --no-dev

COPY backend/ backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd backend && uv sync --locked --no-dev

FROM python:3.11-slim-bookworm AS runtime

# Non-root: a container running as root that gets compromised hands the
# attacker root inside the container for free — no reason to pay that price.
RUN groupadd --system --gid 1000 geovision \
    && useradd --system --uid 1000 --gid geovision --no-create-home --shell /usr/sbin/nologin geovision

WORKDIR /app/backend
COPY --from=builder --chown=geovision:geovision /app/backend /app/backend

ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER geovision
EXPOSE 8000

# Python, not curl: keeps the runtime image to exactly what the app needs —
# nothing extra installed just to satisfy a healthcheck.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# gunicorn supervises uvicorn workers: a worker that crashes gets replaced
# without the container restarting. `--workers 2` is a CPU-only-friendly
# default for a 2 vCPU deployment target (Module-16-Deployment.md); raise it
# on a bigger box via the compose file, not this image.
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
