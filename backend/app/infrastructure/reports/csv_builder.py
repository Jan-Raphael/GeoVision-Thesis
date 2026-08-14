r"""CSV export — the thesis appendix's data source.

Two tables in one file, separated by a blank line, each with its own header row:
the per-window snapshots specified in the module note, then the per-image rows.
One file because the contract's format enum is `pdf|csv` and a download serves
one object; a ZIP would have been a third format in all but name. Spreadsheets
import the first table directly and the second is one selection away, and
``pandas.read_csv(..., skiprows=n)`` reads either.

``\\r\\n`` line endings throughout: that is what RFC 4180 specifies and what
Excel expects, and `csv.writer` emits it only if the file is opened with
``newline=""`` — which is why this builds into a ``StringIO`` rather than
formatting rows by hand.
"""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.reporting import ReportData

__all__ = ["SNAPSHOT_HEADER", "build_csv"]

SNAPSHOT_HEADER = (
    "window_start",
    "displayed_pct",
    "raw_pct",
    "ema_pct",
    "macro_stage",
    "foundation_pct",
    "framing_pct",
    "roofing_pct",
    "finishing_pct",
    "approval_pct",
    "eligible_images",
    "devices_reporting",
    "status",
    "algorithm_version",
)

CAPTURE_HEADER = (
    "filename",
    "captured_at",
    "latitude",
    "longitude",
    "device",
    "status",
    "stage",
    "macro_stage",
    "confidence",
    "raw_progress_pct",
    "eligible",
)


def build_csv(data: ReportData) -> bytes:
    """Render both tables as UTF-8 CSV bytes.

    A period with no captures still produces both header rows. An empty file
    would be indistinguishable from a failed export, and the headers are what
    tell a reader they are looking at a real answer rather than a broken one.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")

    status = data.status.value if data.status else ""
    writer.writerow(SNAPSHOT_HEADER)
    for snapshot in data.snapshots:
        writer.writerow(
            (
                snapshot.window_start.isoformat(),
                f"{snapshot.displayed_pct.as_float():.2f}",
                f"{snapshot.raw_pct.as_float():.2f}",
                f"{snapshot.ema_pct.as_float():.2f}",
                snapshot.macro_stage.value,
                f"{snapshot.foundation_pct:.2f}",
                f"{snapshot.framing_pct:.2f}",
                f"{snapshot.roofing_pct:.2f}",
                f"{snapshot.finishing_pct:.2f}",
                f"{snapshot.approval_pct:.2f}",
                snapshot.eligible_image_count,
                snapshot.devices_reporting,
                status,
                snapshot.algorithm_version,
            )
        )

    writer.writerow(())
    writer.writerow(CAPTURE_HEADER)
    for row in data.captures:
        image = row.image
        prediction = row.prediction
        location = image.location
        writer.writerow(
            (
                image.filename,
                image.captured_at.isoformat(),
                f"{location.latitude:.6f}" if location else "",
                f"{location.longitude:.6f}" if location else "",
                row.device_name or "",
                image.status.value,
                prediction.fine_class if prediction else "",
                prediction.macro_stage.value if prediction else "",
                f"{prediction.confidence.as_float():.4f}" if prediction else "",
                f"{prediction.raw_progress_pct.as_float():.2f}" if prediction else "",
                # Blank rather than "false" when there is no prediction at all:
                # a rejected frame was never judged ineligible, it was never
                # judged, and conflating the two would understate the model.
                str(prediction.is_eligible).lower() if prediction else "",
            )
        )

    return buffer.getvalue().encode("utf-8")
