# GeoVision — Celery worker image (Module 16).
#
# Named `worker.Dockerfile`, not the vault's original placeholder
# `ai.Dockerfile` — it builds the *backend* app with the `[worker]` extra
# (which pulls in `geovision-ai` as a dependency), not the `ai` package on its
# own. See Progress-Log 2026-08-29.
#
# Build context is the REPO ROOT (see docker-compose.yml): `geovision-ai` is
# resolved from the sibling `ai/` directory as an editable path dependency
# (backend/pyproject.toml's [tool.uv.sources]), so both `backend/` and `ai/`
# must be visible in the same build — and since an editable install is a
# reference back to its source tree, not a copied wheel, `ai/` has to survive
# into the runtime stage too, not just the builder.
#
# CPU-only torch by default (ai/pyproject.toml pins the CPU wheel index -
# ADR-012). This is deliberate for the thesis's actual deployment targets
# (a laptop, a mini-PC, a 2 vCPU cloud VM — see Module-16-Deployment.md); a
# CUDA variant is future work, not wired here, since nothing in scope needs one.
#
# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

# libgl1/libglib2.0-0: opencv-python-headless still links against these at
# import time even without a GUI. Missing them fails with a cryptic
# "libGL.so.1: cannot open shared object file" the first time cv2 is imported,
# not at install time - easy to miss until a real image reaches the worker.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock backend/
COPY ai/ ai/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd backend && uv sync --locked --no-install-project --no-dev --extra worker

COPY backend/ backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd backend && uv sync --locked --no-dev --extra worker

FROM python:3.11-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 geovision \
    && useradd --system --uid 1000 --gid geovision --no-create-home --shell /usr/sbin/nologin geovision

WORKDIR /app
COPY --from=builder --chown=geovision:geovision /app/backend /app/backend
COPY --from=builder --chown=geovision:geovision /app/ai /app/ai

ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER geovision
WORKDIR /app/backend

# No HTTP surface to probe - `celery inspect ping` round-trips through the
# real broker connection, which is the thing actually worth checking.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["celery", "-A", "app.worker.celery_app", "inspect", "ping", "-t", "5"]

CMD ["celery", "-A", "app.worker.celery_app", "worker", \
     "-Q", "ingest,inference,interactive,reports", \
     "-l", "info"]
