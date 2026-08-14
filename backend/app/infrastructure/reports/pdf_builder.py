"""The PDF report — the strongest artifact this system produces.

Nine sections, in the order the module note specifies. Two things about it are
not cosmetic.

**Every timestamp is rendered in the project's timezone, with the offset shown.**
A report that says "07:00" without a zone is ambiguous evidence, and this
document could plausibly inform a payment or a scheduling decision.

**The appendix disclaimer is required, not optional.** It states the model
versions behind the numbers, that the progress figure is an *estimate*, and that
the final 20 % requires physical inspection. A document that presents an AI
estimate as a measurement invites exactly the misuse the approval gate exists to
prevent.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as PdfImage,
)
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.infrastructure.reports import charts

if TYPE_CHECKING:
    from app.domain.reporting import ReportData

__all__ = ["build_pdf"]

_INK = colors.HexColor("#1f2933")
_MUTED = colors.HexColor("#6b7280")
_RULE = colors.HexColor("#d7dbe0")
_ACCENT = colors.HexColor("#1f4e79")
_WARN = colors.HexColor("#8d6e63")

#: How many captures the gallery shows. The vault asks for "the latest image per
#: device per week"; this caps it so a year-long custom period cannot produce a
#: 400-page document.
GALLERY_LIMIT = 12


def _styles() -> dict[str, ParagraphStyle]:
    """Paragraph styles, derived once per document."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "gvTitle",
            parent=base["Title"],
            fontSize=22,
            leading=26,
            textColor=_INK,
            alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "gvSubtitle",
            parent=base["Normal"],
            fontSize=11,
            leading=15,
            textColor=_MUTED,
        ),
        "h2": ParagraphStyle(
            "gvH2",
            parent=base["Heading2"],
            fontSize=13,
            leading=16,
            textColor=_ACCENT,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "gvBody",
            parent=base["Normal"],
            fontSize=9.5,
            leading=13.5,
            textColor=_INK,
        ),
        "small": ParagraphStyle(
            "gvSmall",
            parent=base["Normal"],
            fontSize=8,
            leading=11,
            textColor=_MUTED,
        ),
        "warn": ParagraphStyle(
            "gvWarn",
            parent=base["Normal"],
            fontSize=8.5,
            leading=12,
            textColor=_WARN,
        ),
    }


def _table(rows: list[list[Any]], widths: list[float], *, header: bool = True) -> Table:
    """A consistently styled table."""
    table = Table(rows, colWidths=widths, hAlign="LEFT")
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), _INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, _RULE),
        ]
    table.setStyle(TableStyle(style))
    return table


def _local(moment: datetime | None, timezone: str) -> str:
    """Render a timestamp in the project's zone, offset included."""
    if moment is None:
        return "—"
    try:
        zone = ZoneInfo(timezone)
    except Exception:
        zone = ZoneInfo("UTC")
    return moment.astimezone(zone).strftime("%d %b %Y, %H:%M (%Z, UTC%z)")


def _png(payload: bytes, width: float) -> PdfImage:
    """Scale a rendered chart to *width*, preserving its aspect ratio."""
    image = PdfImage(io.BytesIO(payload))
    ratio = image.imageHeight / image.imageWidth
    image.drawWidth = width
    image.drawHeight = width * ratio
    return image


def build_pdf(data: ReportData) -> bytes:
    """Render the report. Returns PDF bytes."""
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"GeoVision report — {data.project.name}",
        author="GeoVision",
    )
    width = document.width
    style = _styles()
    story: list[Any] = []
    project = data.project
    zone = project.timezone
    location = project.location

    # 1 — Cover -------------------------------------------------------------
    story += [
        Paragraph("Construction Progress Report", style["title"]),
        Paragraph(f"{project.name} · {project.code.value}", style["subtitle"]),
        Spacer(1, 8),
        _table(
            [
                ["Period", data.period.label],
                ["Location", project.location_label],
                [
                    "Coordinates",
                    f"{location.latitude:.6f}, {location.longitude:.6f}" if location else "—",
                ],
                ["Owner", data.owner.full_name if data.owner else "—"],
                ["Deadline", f"{project.deadline_date:%d %b %Y}"],
                ["Generated", _local(data.generated_at, zone)],
            ],
            [32 * mm, width - 32 * mm],
            header=False,
        ),
    ]

    # 2 — Executive summary -------------------------------------------------
    days_left = (project.deadline_date - data.period.end).days
    drift = data.displayed_pct - data.expected_pct
    verdict = "on track" if drift >= -10.0 else "behind schedule"
    story += [
        Paragraph("1. Executive summary", style["h2"]),
        _table(
            [
                ["Estimated progress", f"{data.displayed_pct:.1f}%"],
                ["Expected by this date", f"{data.expected_pct:.1f}% (linear to deadline)"],
                ["Variance", f"{drift:+.1f} percentage points — {verdict}"],
                ["Macro stage", (project.macro_stage.value if project.macro_stage else "—")],
                ["Status", f"{data.status.value if data.status else '—'} — {data.status_reason}"],
                [
                    "Days to deadline",
                    f"{days_left}" if days_left >= 0 else f"{abs(days_left)} days past",
                ],
            ],
            [42 * mm, width - 42 * mm],
            header=False,
        ),
    ]
    if not data.has_data:
        story += [
            Spacer(1, 6),
            Paragraph(
                "<b>No captures were recorded in this period.</b> The figures above are "
                "carried forward from the last period that had data. A silent camera is "
                "itself a finding — check the Devices section below.",
                style["warn"],
            ),
        ]

    # 3 — Stage breakdown ---------------------------------------------------
    story += [
        Paragraph("2. Stage breakdown", style["h2"]),
        _png(charts.stage_bars(data), width),
        Paragraph(
            "The Approval stage is awarded by a person after physical inspection, never "
            "by the model.",
            style["small"],
        ),
    ]

    # 4 — Progress curve ----------------------------------------------------
    story += [
        Paragraph("3. Progress over the period", style["h2"]),
        _png(charts.progress_curve(data), width),
    ]

    story.append(PageBreak())

    # 5 — Capture summary ---------------------------------------------------
    accepted = len(data.captures) - data.rejected_count
    story += [
        Paragraph("4. Capture summary", style["h2"]),
        _table(
            [
                ["Captures received", str(len(data.captures))],
                ["Accepted", str(accepted)],
                ["Rejected by the quality gate", str(data.rejected_count)],
                ["Used for progress (confidence gate passed)", str(len(data.eligible_captures))],
                ["Cameras reporting", str(len(data.captures_per_device))],
            ],
            [72 * mm, width - 72 * mm],
            header=False,
        ),
        Spacer(1, 6),
        _png(charts.capture_histogram(data), width),
    ]

    if data.devices:
        story += [
            Spacer(1, 6),
            _table(
                [["Camera", "Face", "Status", "Last seen", "Battery"]]
                + [
                    [
                        device.device_name,
                        device.face.value,
                        device.status.value,
                        _local(device.last_seen_at, zone),
                        f"{device.last_battery_mv} mV" if device.last_battery_mv else "—",
                    ]
                    for device in data.devices
                ],
                [38 * mm, 24 * mm, 20 * mm, width - 116 * mm, 22 * mm],
            ),
        ]

    # 6 — Image gallery -----------------------------------------------------
    story += [Paragraph("5. Captures", style["h2"])]
    gallery = list(data.captures[:GALLERY_LIMIT])
    if gallery:
        story.append(
            _table(
                [["Filename", "Captured", "Camera", "Stage", "Confidence", "GPS"]]
                + [
                    [
                        row.image.filename,
                        _local(row.image.captured_at, zone),
                        row.device_name or "—",
                        row.prediction.fine_class
                        if row.prediction
                        else f"({row.image.status.value})",
                        f"{row.prediction.confidence.as_float():.0%}" if row.prediction else "—",
                        f"{row.image.location.latitude:.5f}, {row.image.location.longitude:.5f}"
                        if row.image.location
                        else "—",
                    ]
                    for row in gallery
                ],
                [40 * mm, 34 * mm, 26 * mm, 22 * mm, 18 * mm, width - 140 * mm],
            )
        )
        if len(data.captures) > GALLERY_LIMIT:
            story.append(
                Paragraph(
                    f"Showing {GALLERY_LIMIT} of {len(data.captures)} captures. "
                    "The CSV export contains every row.",
                    style["small"],
                )
            )
    else:
        story.append(Paragraph("No captures in this period.", style["body"]))

    # 7 — Detection summary -------------------------------------------------
    story += [Paragraph("6. Objects detected", style["h2"])]
    if data.detection_counts:
        ordered = sorted(data.detection_counts.items(), key=lambda item: -item[1])
        story += [
            _table(
                [["Object", "Count"]] + [[name, str(count)] for name, count in ordered],
                [60 * mm, width - 60 * mm],
            ),
            Paragraph(
                "Object counts corroborate the stage classification and act as an activity "
                "proxy; they do not themselves set the progress figure.",
                style["small"],
            ),
        ]
    else:
        story.append(Paragraph("No objects were detected in this period.", style["body"]))

    # 8 — Remarks -----------------------------------------------------------
    story += [Paragraph("7. Remarks", style["h2"])]
    if data.remarks:
        story.append(
            _table(
                [["Date", "Type", "Severity", "Remark"]]
                + [
                    [
                        _local(remark.created_at, zone),
                        remark.remark_type.value,
                        remark.severity.value,
                        Paragraph(remark.message, style["small"]),
                    ]
                    for remark in data.remarks
                ],
                [34 * mm, 22 * mm, 20 * mm, width - 76 * mm],
            )
        )
    else:
        story.append(Paragraph("No remarks were recorded in this period.", style["body"]))

    # 9 — Appendix and the required disclaimer ------------------------------
    story += [
        Paragraph("8. Appendix — method and limitations", style["h2"]),
        _table(
            [
                [
                    "Algorithm version",
                    data.snapshots[-1].algorithm_version if data.snapshots else "progress-v1",
                ],
                ["Reporting timezone", zone],
                ["Period", f"{data.period.label} ({data.period.days} days)"],
            ],
            [42 * mm, width - 42 * mm],
            header=False,
        ),
        Spacer(1, 8),
        KeepTogether(
            Paragraph(
                "<b>How to read this document.</b> The progress percentage is an "
                "<b>estimate produced by a computer-vision model</b> from exterior "
                "photographs. It is not a survey, a certification, or a measurement, and it "
                "should not be the sole basis for a payment, contractual, or scheduling "
                "decision. Interior work is invisible to the system, so a building may be "
                "considerably further along than the exterior suggests. The model's own "
                "output is capped at 80 %; the final 20 % is awarded only after a physical "
                "inspection recorded against a named person. Figures are derived from the "
                "stored progress snapshots listed in the CSV export and are reproducible "
                "from them.",
                style["warn"],
            )
        ),
    ]

    document.build(story, onFirstPage=_furniture(data), onLaterPages=_furniture(data))
    return buffer.getvalue()


def _furniture(data: ReportData) -> Any:
    """Page footer: project code, period, page number, and the estimate notice."""

    def draw(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_MUTED)
        canvas.drawString(
            18 * mm,
            10 * mm,
            f"{data.project.code.value} · {data.period.label} · AI estimate, not a survey",
        )
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {document.page}")
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(18 * mm, 13 * mm, A4[0] - 18 * mm, 13 * mm)
        canvas.restoreState()

    return draw
