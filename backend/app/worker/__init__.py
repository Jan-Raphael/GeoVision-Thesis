"""Celery entry points.

A sibling of ``app.api``, not a part of ``app.infrastructure``, and the
distinction is load-bearing. A Celery task is a **delivery mechanism** — the
exact counterpart of an HTTP route — so it belongs in the outermost ring where
it may compose use cases and repositories. Putting it in infrastructure made
``app.infrastructure`` import ``app.application``, which inverts the dependency
direction; the import contract caught it.

    celery -A app.worker.celery_app worker -Q ingest,inference -l info
"""

from __future__ import annotations

__all__: list[str] = []
