"""Celery-backed implementation of :class:`InferenceGateway`.

Two things here are load-bearing and easy to get wrong.

**The wait happens off the event loop.** ``AsyncResult.get()`` is a blocking
call. Awaiting it directly inside a FastAPI handler would stall the entire event
loop for the duration — meaning one person running the demo endpoint freezes
every other request in the process, including the health checks. It runs in a
worker thread instead.

**Unreachability is not an exception everywhere.** ``predict`` raises, because a
prediction with no prediction in it is not a degraded answer, it is a wrong one.
``status`` and ``queue_depth`` return ``None`` and ``{}``, because they exist to
*observe* health and an observability endpoint that fails when things are
unhealthy is worse than useless — it goes dark exactly when it is needed.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import TYPE_CHECKING, Any, cast

from app.application.ports.inference_gateway import (
    AdHocBox,
    AdHocDetection,
    AdHocPrediction,
    AdHocQuality,
    WorkerModelInfo,
    WorkerStatus,
)
from app.core.exceptions import ServiceUnavailableError

if TYPE_CHECKING:
    from app.core.config import Settings

__all__ = ["CeleryInferenceGateway", "get_inference_gateway", "reset_inference_gateway"]

logger = logging.getLogger(__name__)

#: Task names. Defined beside the caller so a rename in ``app.worker.inference``
#: that misses this file fails a test rather than a demo.
TASK_PREDICT_ADHOC = "inference.predict_adhoc"
TASK_SERVICE_STATUS = "inference.service_status"
QUEUE_INTERACTIVE = "interactive"

#: Queues whose depth ``GET /model/status`` reports.
_TRACKED_QUEUES = ("ingest", "inference", "interactive")


class CeleryInferenceGateway:
    """Reaches a worker over Redis and waits for its reply."""

    def __init__(self, settings: Settings) -> None:
        """Bind to the configured broker and timeouts."""
        self._settings = settings

    async def predict(
        self, image_bytes: bytes, *, timeout_s: float | None = None
    ) -> AdHocPrediction:
        """Run one image through the pipeline in a worker and return the result.

        Raises:
            ServiceUnavailableError: If no worker answered within the timeout.
        """
        payload = base64.b64encode(image_bytes).decode("ascii")
        timeout = timeout_s if timeout_s is not None else self._settings.predict_timeout_seconds
        try:
            result = await self._call(TASK_PREDICT_ADHOC, [payload], timeout)
        except Exception as exc:
            logger.warning("ad-hoc prediction failed: %s", exc)
            raise ServiceUnavailableError(
                "No inference worker answered. Start one with `dev.ps1 worker`.",
                details={"timeout_seconds": timeout},
            ) from exc
        return _to_prediction(result)

    async def status(self, *, timeout_s: float | None = None) -> WorkerStatus | None:
        """Ask a worker what it has loaded, or return ``None`` if none answers."""
        timeout = (
            timeout_s if timeout_s is not None else self._settings.model_status_timeout_seconds
        )
        try:
            result = await self._call(TASK_SERVICE_STATUS, [], timeout)
        except Exception as exc:
            logger.info("no worker answered the status probe: %s", exc)
            return None
        return _to_status(result)

    async def queue_depth(self) -> dict[str, int]:
        """Pending task counts per queue, read straight from the broker.

        Celery models a queue as a Redis list, so its depth is the list length.
        This counts what is *waiting*, not what is being worked on — which is the
        number that answers "is there a backlog?".
        """
        try:
            return await asyncio.to_thread(self._queue_depth_blocking)
        except Exception as exc:
            logger.info("could not read queue depth: %s", exc)
            return {}

    # -- internals ----------------------------------------------------------

    async def _call(self, name: str, args: list[Any], wait_seconds: float) -> dict[str, Any]:
        """Send *name* and wait for its reply, off the event loop.

        Deliberately not an ``asyncio.timeout`` scope: the wait happens inside a
        worker thread blocking on Redis, and cancelling the awaiting coroutine
        would abandon that thread rather than stop it. Celery's own ``timeout``
        is the only one that actually ends the wait.
        """
        return await asyncio.to_thread(self._call_blocking, name, args, wait_seconds)

    def _call_blocking(self, name: str, args: list[Any], wait_seconds: float) -> dict[str, Any]:
        """Publish the task and block on the result backend."""
        from app.infrastructure.celery import celery_app

        async_result = celery_app.send_task(
            name,
            args=args,
            queue=QUEUE_INTERACTIVE,
            retry=False,
            # Expire the task itself at the same deadline. Without this a
            # request that has already given up leaves work in the queue that a
            # worker will faithfully perform for nobody.
            expires=wait_seconds,
        )
        try:
            payload: dict[str, Any] = async_result.get(timeout=wait_seconds)
            return payload
        finally:
            # Without this the reply sits in Redis until `result_expires`. One
            # demo is nothing; a load test is a slow leak of megabyte-scale
            # payloads nobody will ever read again.
            async_result.forget()

    def _queue_depth_blocking(self) -> dict[str, int]:
        """Read each tracked queue's length from Redis.

        ``cast`` because redis-py types ``llen`` as ``Awaitable[int] | int`` —
        one annotation covering both the sync and async clients. This is the
        sync client, running in a thread, so the value is always an ``int``.
        """
        import redis

        client = redis.Redis.from_url(self._settings.redis_url, socket_connect_timeout=2)
        try:
            return {queue: cast("int", client.llen(queue)) for queue in _TRACKED_QUEUES}
        finally:
            client.close()


class NullInferenceGateway:
    """What runs when no broker is configured.

    Mirrors ``LoggingTaskQueue``: the app must start and serve on a laptop with
    nothing installed. ``/model/status`` then reports the registry alone, and
    ``/predict`` says plainly that there is no worker rather than hanging.
    """

    async def predict(
        self, image_bytes: bytes, *, timeout_s: float | None = None
    ) -> AdHocPrediction:
        """Always refuse — there is nothing to ask."""
        _ = image_bytes, timeout_s
        raise ServiceUnavailableError(
            "Ad-hoc prediction needs a Celery worker; this deployment has none configured."
        )

    async def status(self, *, timeout_s: float | None = None) -> WorkerStatus | None:
        """No worker, no live status."""
        _ = timeout_s
        return None

    async def queue_depth(self) -> dict[str, int]:
        """No broker, no queues."""
        return {}


_gateway: Any = None


def get_inference_gateway(settings: Settings) -> Any:
    """Return the configured gateway, building it on first use."""
    global _gateway
    if _gateway is None:
        _gateway = (
            CeleryInferenceGateway(settings)
            if settings.task_queue_backend == "celery"
            else NullInferenceGateway()
        )
    return _gateway


def reset_inference_gateway() -> None:
    """Drop the cached gateway. Tests call this after changing settings."""
    global _gateway
    _gateway = None


# ---------------------------------------------------------------------------
# wire -> port
# ---------------------------------------------------------------------------


def _to_prediction(payload: dict[str, Any]) -> AdHocPrediction:
    """Rebuild the port's dataclass from the worker's JSON."""
    quality = payload.get("quality") or {}
    return AdHocPrediction(
        rejected=bool(payload.get("rejected", False)),
        quality=AdHocQuality(
            passed=bool(quality.get("passed", False)),
            flags=tuple(quality.get("flags", ())),
            blur_score=float(quality.get("blur_score", 0.0)),
            brightness=float(quality.get("brightness", 0.0)),
            occlusion_ratio=float(quality.get("occlusion_ratio", 0.0)),
        ),
        stage=payload.get("stage"),
        class_index=payload.get("class_index"),
        confidence=payload.get("confidence"),
        macro_stage=payload.get("macro_stage"),
        progress_pct=payload.get("progress_pct"),
        probabilities=dict(payload.get("probabilities") or {}),
        detections=tuple(
            AdHocDetection(
                class_name=item["class_name"],
                confidence=float(item["confidence"]),
                bbox=AdHocBox(**item["bbox"]),
            )
            for item in payload.get("detections") or ()
        ),
        counts=dict(payload.get("counts") or {}),
        rejection_reason=payload.get("rejection_reason"),
        preprocessing_ms=int(payload.get("preprocessing_ms", 0)),
        inference_ms=int(payload.get("inference_ms", 0)),
        total_ms=int(payload.get("total_ms", 0)),
        model_name=str(payload.get("model_name", "")),
        model_version=str(payload.get("model_version", "")),
        model_is_stub=bool(payload.get("model_is_stub", True)),
        preprocessing_fingerprint=str(payload.get("preprocessing_fingerprint", "")),
    )


def _to_model_info(payload: dict[str, Any]) -> WorkerModelInfo:
    """Rebuild one model's provenance from the worker's JSON."""
    return WorkerModelInfo(
        name=payload["name"],
        architecture=payload["architecture"],
        version=payload["version"],
        class_names=tuple(payload.get("class_names", ())),
        input_size=int(payload.get("input_size", 0)),
        device=payload.get("device", "cpu"),
        is_stub=bool(payload.get("is_stub", False)),
        preprocessing_fingerprint=payload.get("preprocessing_fingerprint"),
    )


def _to_status(payload: dict[str, Any]) -> WorkerStatus:
    """Rebuild the worker snapshot from its JSON."""
    detector = payload.get("detector")
    return WorkerStatus(
        classifier=_to_model_info(payload["classifier"]),
        detector=_to_model_info(detector) if detector else None,
        preprocessing_fingerprint=str(payload.get("preprocessing_fingerprint", "")),
        loaded_at=str(payload.get("loaded_at", "")),
        mean_latency_ms=float(payload.get("mean_latency_ms", 0.0)),
        images_processed=int(payload.get("images_processed", 0)),
    )
