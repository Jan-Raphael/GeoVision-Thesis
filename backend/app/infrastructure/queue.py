"""The real broker behind :class:`~app.application.ports.task_queue.TaskQueue`.

Lives in infrastructure because it imports Celery, which the application layer
must not know about. The API selects it through :func:`get_task_queue`; nothing
above this file has any idea whether work is going to Redis or to a log line.

**Enqueue failures are logged, never raised.** An image that was stored
successfully must not be rejected because the broker hiccupped. The row's
``status='pending'`` is the durable record that work is owed, and a sweep can
pick it up later — whereas a 500 returned to a camera on a roof costs the
photograph itself.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.config import Settings

__all__ = ["CeleryTaskQueue", "get_task_queue", "reset_task_queue"]

logger = logging.getLogger(__name__)


class CeleryTaskQueue:
    """Sends work to Celery over Redis."""

    async def enqueue(self, name: str, payload: dict[str, Any], *, queue: str = "default") -> None:
        """Publish *name* with *payload*.

        Args are passed positionally in a stable order because Celery serialises
        them by position; the task signatures in
        ``app.worker.inference`` define that order.
        """
        try:
            from app.infrastructure.celery import celery_app

            # `retry=False` and a short connection timeout are the important
            # part. Celery's default is to retry the broker connection with
            # backoff for up to a hundred seconds, which would hang an ESP32's
            # upload request for that long every time Redis was down - turning a
            # broker outage into an ingest outage. The image is already stored
            # and already `pending`; a worker sweeps it up later.
            celery_app.send_task(name, kwargs=payload, queue=queue, retry=False)
            logger.debug("task_enqueued name=%s queue=%s", name, queue)
        except Exception:
            # Deliberately broad: a broker outage must not fail the upload that
            # triggered it. `pending` remains the durable backlog.
            logger.warning("could not enqueue %s; image remains pending", name, exc_info=True)


_queue: Any = None


def get_task_queue(settings: Settings) -> Any:
    """Return the configured queue, building it on first use.

    Falls back to the logging stub when no broker is configured, so the API runs
    on a laptop with nothing installed — the same pattern as storage (ADR-018)
    and the nonce cache (ADR-021).
    """
    global _queue
    if _queue is None:
        if settings.task_queue_backend == "celery":
            _queue = CeleryTaskQueue()
        else:
            from app.application.ports.task_queue import LoggingTaskQueue

            _queue = LoggingTaskQueue()
    return _queue


def reset_task_queue() -> None:
    """Drop the cached queue. Tests call this after changing settings."""
    global _queue
    _queue = None
