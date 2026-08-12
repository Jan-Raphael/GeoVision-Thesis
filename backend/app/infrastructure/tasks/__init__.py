"""Celery application and task definitions (Modules 09-10).

Queues: `ingest` (fast), `inference` (CPU/GPU bound, low concurrency),
`reports` (slow). On Windows the worker needs `--pool=solo`; in production it
runs in a Linux container with the default prefork pool. See ADR-013.
"""
