"""The worker entry point.

    celery -A app.worker.celery_app worker -Q ingest,inference -l info
    celery -A app.worker.celery_app worker -Q inference --pool=solo   # Windows (ADR-013)

The broker client itself lives in :mod:`app.infrastructure.celery`; this module
adds the worker-process lifecycle and imports the task modules so Celery
registers them.
"""

from __future__ import annotations

import logging
from typing import Any

from celery.signals import worker_process_init

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.celery import celery_app

# Imported for its registration side effect: a task Celery has never imported is
# a task it will refuse to run, with an unhelpful "unregistered task" error.
from app.worker import inference as _inference  # noqa: F401
from app.worker import reports as _reports  # noqa: F401

__all__ = ["celery_app"]

logger = logging.getLogger(__name__)


@worker_process_init.connect
def _init_worker(**_: Any) -> None:
    """Load the models once, when the process starts.

    ``worker_process_init`` rather than module import: with the prefork pool the
    module is imported by the parent and each child is forked, so a model loaded
    at import time would be shared through copy-on-write in ways that are subtly
    unsafe with CUDA and wasteful without it. Loading per child is the documented
    pattern.

    Failure is logged and swallowed. A worker that cannot load a model should
    still start and fail *individual tasks* with a retry, rather than crash-loop
    — a crash loop produces no logs anyone can read and no queue anyone can
    inspect.
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    try:
        from app.infrastructure.ai.adapter import get_inference_service

        get_inference_service(settings)
    except Exception:
        logger.exception("could not load inference models at worker start")
