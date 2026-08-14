"""Outbound port for background work.

Ingest ends by handing an image off for inference. That consumer is Module 09,
so Module 05 needs somewhere to hand it *to* without depending on Celery — and
without pretending the handoff does not exist, which would leave a hole to
remember later.

Two implementations today, a third in Module 09:

``LoggingTaskQueue``
    Records the enqueue and returns. What runs until the worker exists: images
    land with ``status='pending'``, which is exactly the state a worker will
    pick them up from.
``RecordingTaskQueue``
    Captures calls so tests can assert the handoff happened.
``CeleryTaskQueue`` *(Module 09)*
    The real broker.

The port is deliberately narrow: a task name and a JSON-serialisable payload.
Anything richer would leak Celery's shape into callers that must not know about
it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = ["EnqueuedTask", "LoggingTaskQueue", "RecordingTaskQueue", "TaskQueue"]


@dataclass(frozen=True, slots=True)
class EnqueuedTask:
    """A unit of deferred work."""

    name: str
    payload: dict[str, Any]
    queue: str = "default"


class TaskQueue(Protocol):
    """Somewhere to put work that happens later."""

    async def enqueue(self, name: str, payload: dict[str, Any], *, queue: str = "default") -> None:
        """Schedule *name* with *payload*.

        Must not raise for transient broker problems in a way that fails the
        caller's request: an image that was stored successfully should not be
        rejected because the queue hiccupped. Implementations log and move on;
        the row's ``pending`` status is the durable record that work is owed.
        """
        ...


class LoggingTaskQueue:
    """Records the enqueue and does nothing else.

    The default until Module 09 provides a worker. This is not a silent no-op:
    the log line is the audit trail that a handoff was attempted, and the
    ``images.status='pending'`` row is the durable backlog a worker will drain
    when it arrives.
    """

    def __init__(self) -> None:
        """Bind a logger."""
        import logging

        self._logger = logging.getLogger("app.tasks")

    async def enqueue(self, name: str, payload: dict[str, Any], *, queue: str = "default") -> None:
        """Log the task that would have been dispatched."""
        self._logger.info(
            "task_enqueued name=%s queue=%s payload=%s (no worker yet - Module 09)",
            name,
            queue,
            payload,
        )


@dataclass
class RecordingTaskQueue:
    """Captures enqueued tasks so tests can assert on the handoff."""

    tasks: list[EnqueuedTask] = field(default_factory=list)

    async def enqueue(self, name: str, payload: dict[str, Any], *, queue: str = "default") -> None:
        """Record the task."""
        self.tasks.append(EnqueuedTask(name=name, payload=payload, queue=queue))

    def names(self) -> list[str]:
        """Task names in the order they were enqueued."""
        return [task.name for task in self.tasks]

    def clear(self) -> None:
        """Forget everything recorded."""
        self.tasks.clear()


#: Task names, defined here so producer (Module 05) and consumer (Module 09)
#: cannot drift apart over a typo.
TASK_PROCESS_IMAGE = "inference.process_image"
QUEUE_INFERENCE = "inference"
