"""What a report is made of: an aggregate of stored entities, and nothing else.

Assembled once by the worker, then handed to the PDF and CSV builders. It lives
in the **domain** rather than the application layer for a structural reason: the
renderers are infrastructure (they import ReportLab and matplotlib), and
infrastructure may not import the application layer. Putting the contract here —
where both sides may read it — is what lets the builders be pure formatters that
query nothing.

That purity is the point. A report cannot quietly disagree with the dashboard by
fetching its own numbers, so the thesis appendix, the PDF, and the screen all
show the same stored snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from app.domain.entities import (
        Device,
        Image,
        Prediction,
        ProgressSnapshot,
        Project,
        Remark,
        User,
    )
    from app.domain.enums import ProjectStatus
    from app.domain.services.reporting import ReportPeriod

__all__ = ["CaptureRow", "ReportData"]


@dataclass(frozen=True, slots=True)
class CaptureRow:
    """One capture and whatever the model made of it."""

    image: Image
    prediction: Prediction | None
    device_name: str | None

    @property
    def was_rejected(self) -> bool:
        """Whether the quality gate discarded this frame."""
        from app.domain.enums import ImageStatus

        return self.image.status is ImageStatus.REJECTED


@dataclass(frozen=True, slots=True)
class ReportData:
    """Everything one report renders.

    Attributes:
        status_reason: The one-line explanation shown beside the status badge,
            reused verbatim so the report and the dashboard never offer two
            different accounts of the same project.
        expected_pct: Where a linear schedule says the project should be by
            ``period.end``. Plotted against the actual curve — the gap between
            the two lines is the entire point of the progress chart.
    """

    project: Project
    owner: User | None
    period: ReportPeriod
    generated_at: datetime
    snapshots: tuple[ProgressSnapshot, ...] = ()
    captures: tuple[CaptureRow, ...] = ()
    devices: tuple[Device, ...] = ()
    remarks: tuple[Remark, ...] = ()
    status: ProjectStatus | None = None
    status_reason: str = ""
    expected_pct: float = 0.0
    detection_counts: dict[str, int] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        """Whether anything was captured in the period.

        An empty period still produces a **valid** report saying so. Failing
        instead would be worse: "no captures for three weeks" is one of the more
        important things a report can tell an owner, and it is precisely the
        situation where they most want a document to show somebody.
        """
        return bool(self.captures)

    @property
    def eligible_captures(self) -> tuple[CaptureRow, ...]:
        """Captures whose prediction cleared the confidence gate."""
        return tuple(
            row
            for row in self.captures
            if row.prediction is not None and row.prediction.is_eligible
        )

    @property
    def rejected_count(self) -> int:
        """How many frames the quality gate discarded."""
        return sum(1 for row in self.captures if row.was_rejected)

    @property
    def displayed_pct(self) -> float:
        """The project's progress at the end of the period."""
        if self.snapshots:
            return self.snapshots[-1].displayed_pct.as_float()
        return self.project.progress_pct.as_float()

    @property
    def captures_per_device(self) -> dict[str, int]:
        """How many frames each camera contributed."""
        tally: dict[str, int] = {}
        for row in self.captures:
            name = row.device_name or "unknown"
            tally[name] = tally.get(name, 0) + 1
        return tally
