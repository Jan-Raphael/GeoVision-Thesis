"""Redis pub/sub: the fan-out between processes.

    Celery worker ──publish──> "project:{id}" ──> every API process
                                                    └─> that process's hub
                                                          └─> subscribed sockets

**This is not optional the moment there is more than one Uvicorn worker.** A
socket lives in exactly one process; an in-process registry would deliver events
only to whichever worker happened to accept that connection, and the bug is
invisible with `--workers 1` — which is how it survives to production.

The subscriber uses a **pattern** subscription (``project:*``) rather than
tracking which projects this process currently cares about. Re-subscribing on
Redis every time a browser opens or closes a project would be a second
distributed-state problem to keep correct, and the hub already drops events for
projects it holds no sockets for. One pattern, no coordination.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.application.ports.events import RealtimeEvent, channel_for

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.infrastructure.realtime.hub import ConnectionHub

__all__ = [
    "RealtimeSubscriber",
    "RedisEventPublisher",
    "get_event_publisher",
    "reset_event_publisher",
]

logger = logging.getLogger(__name__)

#: Channel pattern every API process listens on.
PROJECT_CHANNEL_PATTERN = "project:*"


class RedisEventPublisher:
    """Announces events on the project's Redis channel."""

    def __init__(self, redis_url: str) -> None:
        """Bind to Redis. The client is created lazily on first publish."""
        self._url = redis_url
        self._client: Any = None

    async def publish(self, event: RealtimeEvent) -> None:
        """Publish *event*, swallowing any failure.

        Deliberately total: the database write that produced this event has
        already committed. Turning a Redis hiccup into a failed upload would
        trade a real outcome for a cosmetic one, and the dashboard polls anyway.
        """
        try:
            client = await self._connect()
            await client.publish(channel_for(event.project_id), json.dumps(event.as_wire()))
        except Exception:
            logger.warning("could not publish %s; the dashboard will poll", event.type)

    async def _connect(self) -> Any:
        """Return the client, creating it on first use."""
        if self._client is None:
            from redis.asyncio import Redis

            self._client = Redis.from_url(
                self._url,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
        return self._client

    async def close(self) -> None:
        """Release the connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class RealtimeSubscriber:
    """Consumes Redis and hands events to this process's hub.

    Started and stopped by the FastAPI lifespan, so its life is exactly the
    application's — no orphaned task surviving a reload, and no socket receiving
    events after shutdown has begun.
    """

    def __init__(self, redis_url: str, hub: ConnectionHub) -> None:
        """Bind to Redis and the local hub."""
        self._url = redis_url
        self._hub = hub
        self._task: asyncio.Task[None] | None = None
        self._client: Any = None

    async def start(self) -> None:
        """Begin consuming in the background. Idempotent."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="realtime-subscriber")

    async def stop(self) -> None:
        """Cancel the consumer and release Redis."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _run(self) -> None:
        """Consume forever, reconnecting on failure.

        A dropped Redis connection must not silently end realtime for the whole
        process until someone restarts it — the symptom would be "the dashboard
        stopped updating" with nothing in the logs to explain it. So the loop
        reconnects with a fixed delay and says so each time.
        """
        from redis.asyncio import Redis

        while True:
            try:
                self._client = Redis.from_url(self._url, decode_responses=True)
                pubsub = self._client.pubsub()
                await pubsub.psubscribe(PROJECT_CHANNEL_PATTERN)
                logger.info("realtime subscriber listening on %s", PROJECT_CHANNEL_PATTERN)

                async for message in pubsub.listen():
                    if message.get("type") != "pmessage":
                        continue
                    await self._dispatch(message.get("data"))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("realtime subscriber lost Redis; retrying in 5s", exc_info=True)
                await asyncio.sleep(5)

    async def _dispatch(self, raw: object) -> None:
        """Turn one Redis payload into a local broadcast."""
        try:
            data = json.loads(str(raw))
            event = RealtimeEvent(
                type=data["type"],
                project_id=UUID(data["project_id"]),
                payload=data.get("payload") or {},
            )
        except Exception:
            # A malformed frame is somebody else's bug; dropping one message is
            # far better than ending the subscription for every socket.
            logger.warning("discarding an unparseable realtime message")
            return
        await self._hub.broadcast(event)


_publisher: Any = None


def get_event_publisher(settings: Settings) -> Any:
    """Return the configured publisher, building it on first use.

    Falls back to the null publisher when no broker is configured — the same
    pattern as storage (ADR-018) and the task queue, so the app runs with
    nothing installed and simply does not push.
    """
    global _publisher
    if _publisher is None:
        if settings.task_queue_backend == "celery":
            _publisher = RedisEventPublisher(settings.redis_url)
        else:
            from app.application.ports.events import NullEventPublisher

            _publisher = NullEventPublisher()
    return _publisher


def reset_event_publisher() -> None:
    """Drop the cached publisher. Tests call this after changing settings."""
    global _publisher
    _publisher = None
