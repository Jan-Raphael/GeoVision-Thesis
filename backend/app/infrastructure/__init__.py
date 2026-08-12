"""Infrastructure layer - concrete adapters for the outside world.

SQLAlchemy models and repositories, MinIO/S3 storage, Celery tasks, the AI
adapter, PDF/CSV writers, and the WebSocket hub. This is the only layer that
knows a specific database, broker, or ML framework exists.
"""
