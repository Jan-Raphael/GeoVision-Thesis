"""Request and response models for report generation and download."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ReportFormat, ReportKind, ReportStatus

__all__ = [
    "ReportDownloadResponse",
    "ReportListResponse",
    "ReportResponse",
    "RequestReportRequest",
]


class RequestReportRequest(BaseModel):
    """The Report button's payload (spec B.4)."""

    model_config = ConfigDict(extra="forbid")

    kind: ReportKind = ReportKind.WEEKLY
    report_format: ReportFormat = Field(
        default=ReportFormat.PDF,
        description="`pdf` for the presentation document, `csv` for the raw rows.",
    )
    period_start: date | None = Field(
        default=None, description="Required for `custom`; ignored otherwise."
    )
    period_end: date | None = Field(
        default=None, description="Required for `custom`; ignored otherwise."
    )

    @model_validator(mode="after")
    def _custom_needs_both_dates(self) -> RequestReportRequest:
        """Reject a half-specified custom period here, not in the worker.

        Weekly and monthly periods are derived from the project's calendar, so
        supplying dates for them would be silently ignored — better to say so.
        """
        if self.kind is ReportKind.CUSTOM and (
            self.period_start is None or self.period_end is None
        ):
            msg = "a custom report requires both period_start and period_end"
            raise ValueError(msg)
        if self.kind is not ReportKind.CUSTOM and (self.period_start or self.period_end):
            msg = f"period_start/period_end apply only to 'custom' reports, not '{self.kind.value}'"
            raise ValueError(msg)
        return self


class ReportResponse(BaseModel):
    """One report job."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    requested_by: UUID
    kind: ReportKind
    report_format: ReportFormat
    period_start: date
    period_end: date
    status: ReportStatus
    error: str | None = Field(
        default=None, description="Why generation failed. Null unless status is `failed`."
    )
    requested_at: datetime | None = None
    completed_at: datetime | None = None
    is_downloadable: bool = False


class ReportListResponse(BaseModel):
    """A project's recent reports."""

    reports: list[ReportResponse] = Field(default_factory=list)


class ReportDownloadResponse(BaseModel):
    """A short-lived link to a rendered report."""

    url: Annotated[str, Field(description="Signed URL, valid for 15 minutes.")]
    filename: str
    report_format: ReportFormat
    expires_in_seconds: int = 900
