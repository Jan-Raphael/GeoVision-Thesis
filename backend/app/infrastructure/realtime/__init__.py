"""Realtime delivery: a per-process socket hub behind a Redis fan-out.

Split in three because the pieces run in different places. Producers (Celery
workers, request handlers) hold no sockets and only publish; every API process
subscribes and owns a hub of the connections it accepted.
"""

from __future__ import annotations

from app.infrastructure.realtime.bus import (
    RealtimeSubscriber,
    RedisEventPublisher,
    get_event_publisher,
    reset_event_publisher,
)
from app.infrastructure.realtime.hub import ConnectionHub, get_hub, reset_hub

__all__ = [
    "ConnectionHub",
    "RealtimeSubscriber",
    "RedisEventPublisher",
    "get_event_publisher",
    "get_hub",
    "reset_event_publisher",
    "reset_hub",
]
