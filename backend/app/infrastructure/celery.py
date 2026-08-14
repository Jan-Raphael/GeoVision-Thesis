"""The configured Celery client.

Infrastructure, not a delivery mechanism: this module is a *client* to Redis in
exactly the way the SQLAlchemy engine is a client to PostgreSQL. The tasks that
run on it live in ``app.worker`` — putting them here would make infrastructure
import the application layer, which is the wrong direction and which the import
contract rejects.

Three queues, deliberately separated:

``ingest``
    Short, cheap, I/O-bound work. High concurrency is fine.
``inference``
    Model work. Concurrency **1-2**, no higher. torch is already multithreaded
    internally, so running four workers on four cores means four processes each
    spawning four threads and fighting each other for the same cores — it makes
    throughput worse, not better, and the symptom is a machine at 100 % CPU
    processing fewer images than it did with one worker.
``interactive``
    The same model work, but with somebody waiting on an HTTP response for it —
    ``POST /predict`` and the ``/model/status`` probe. Split out so a queue of
    captured images cannot delay a live request; the whole point of the demo
    endpoint is that it answers while a person is looking at it.

On Windows the prefork pool does not work; run with ``--pool=solo`` (ADR-013).
The deployed worker is a Linux container, where prefork is correct.

Run::

    celery -A app.worker.celery_app worker -Q ingest,inference -l info
    celery -A app.worker.celery_app worker -Q inference --pool=solo   # Windows
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

__all__ = ["celery_app"]

settings = get_settings()

celery_app = Celery(
    "geovision",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.inference", "app.worker.reports"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Acknowledge only after the task returns. If a worker is killed mid-image
    # the task is redelivered rather than silently lost - the image would
    # otherwise sit at `pending` forever with nothing to pick it up.
    task_acks_late=True,
    # One task at a time per worker process. With `acks_late`, prefetching would
    # let a dying worker take several images down with it.
    worker_prefetch_multiplier=1,
    task_track_started=True,
    # A single image should never take five minutes. If it does, something is
    # wrong and holding the slot makes it worse.
    task_soft_time_limit=120,
    task_time_limit=180,
    task_default_queue="default",
    task_routes={
        "inference.process_image": {"queue": "inference"},
        "progress.recompute_window": {"queue": "inference"},
        # Separate queue on purpose: an HTTP request is blocked on each of
        # these. Sharing `inference` would put the live demo behind whatever
        # backlog of captures happens to exist, and it would time out for
        # reasons unrelated to whether it works.
        "inference.predict_adhoc": {"queue": "interactive"},
        "inference.service_status": {"queue": "interactive"},
        # Slow, CPU-bound, and unrelated to scoring images.
        "reports.generate": {"queue": "reports"},
    },
    result_expires=3600,
    # Fail fast when the broker is unreachable. The producer is a web request
    # serving a battery-powered camera; waiting out a retry ladder there is
    # worse than dropping the enqueue, because the image is already durably
    # stored with `status='pending'`.
    broker_connection_retry_on_startup=False,
    broker_transport_options={"socket_timeout": 2, "socket_connect_timeout": 2},
)
