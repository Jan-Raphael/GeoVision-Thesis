"""Outbound port for server-to-browser events.

The thing that makes this port necessary is *where* events originate. A capture
is scored by a **Celery worker**, which holds no WebSocket and never will — the
socket lives in an API process, quite possibly on another machine. So a producer
cannot deliver an event; it can only announce one, and something else fans it
out (``Realtime-Events.md`` §Fan-out architecture).

Declaring that here keeps every producer — ingest, the inference worker, the
maintenance jobs — free of Redis. They emit a value object; how it reaches a
browser is infrastructure's problem.

**Publishing must never fail a caller.** An image was stored, a prediction was
written, a report was rendered: those succeeded. A browser not learning about it
a second earlier is a degraded notification, not a failed operation, and the
dashboard polls as a fallback precisely so that correctness never depends on
this path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

__all__ = [
    "EventPublisher",
    "EventType",
    "NullEventPublisher",
    "RealtimeEvent",
    "RecordingEventPublisher",
    "channel_for",
]


class EventType:
    """The event vocabulary from ``Realtime-Events.md``.

    Constants rather than an enum: these strings cross a Redis channel and a
    WebSocket to a TypeScript client, so they are wire values first and Python
    values second. A typo here should be greppable against ``dashboard/src/lib/ws.ts``.
    """

    CONNECTION_READY: Final = "connection.ready"
    IMAGE_RECEIVED: Final = "image.received"
    IMAGE_PROCESSING: Final = "image.processing"
    IMAGE_REJECTED: Final = "image.rejected"
    PREDICTION_COMPLETED: Final = "prediction.completed"
    PROGRESS_UPDATED: Final = "project.progress.updated"
    STATUS_CHANGED: Final = "project.status.changed"
    APPROVAL_REQUIRED: Final = "project.approval.required"
    PROJECT_APPROVED: Final = "project.approved"
    DEVICE_STATUS_CHANGED: Final = "device.status.changed"
    DEVICE_PAIRED: Final = "device.paired"
    REMARK_CREATED: Final = "remark.created"
    REPORT_READY: Final = "report.ready"
    NOTIFICATION_CREATED: Final = "notification.created"


def channel_for(project_id: UUID | str) -> str:
    """The Redis channel carrying one project's events."""
    return f"project:{project_id}"


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    """One server-to-browser message.

    Scoped to a project because that is also the unit of authorization: a socket
    is subscribed per project, so an event that carries its project id can be
    routed without the fan-out layer having to understand what it means.
    """

    type: str
    project_id: UUID
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_wire(self) -> dict[str, Any]:
        """The envelope exactly as ``Realtime-Events.md`` specifies it."""
        return {
            "type": self.type,
            "project_id": str(self.project_id),
            "ts": self.ts.isoformat().replace("+00:00", "Z"),
            "payload": self.payload,
        }


class EventPublisher(Protocol):
    """Somewhere to announce an event."""

    async def publish(self, event: RealtimeEvent) -> None:
        """Announce *event* to every API process.

        Must not raise. See the module docstring: the work that produced the
        event has already succeeded, and failing it now would trade a real
        outcome for a cosmetic one.
        """
        ...


class NullEventPublisher:
    """Drops events. What runs when no broker is configured.

    Same reasoning as ``LoggingTaskQueue``: the app has to start and serve on a
    laptop with nothing installed, and the dashboard's 60-second poll keeps it
    correct without a single socket.
    """

    async def publish(self, event: RealtimeEvent) -> None:
        """Discard the event."""
        _ = event


@dataclass
class RecordingEventPublisher:
    """Captures events so tests can assert what would have been pushed."""

    events: list[RealtimeEvent] = field(default_factory=list)

    async def publish(self, event: RealtimeEvent) -> None:
        """Record the event."""
        self.events.append(event)

    def types(self) -> list[str]:
        """Event types in emission order."""
        return [event.type for event in self.events]

    def clear(self) -> None:
        """Forget everything recorded."""
        self.events.clear()
