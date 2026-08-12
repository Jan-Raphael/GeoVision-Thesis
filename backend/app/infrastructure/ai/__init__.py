"""Adapter onto the `ai` package (Module 09).

The single point where the backend touches torch. Keeping it here is what lets
the `no-torch-in-api` import contract hold: only the Celery worker imports this.
"""
