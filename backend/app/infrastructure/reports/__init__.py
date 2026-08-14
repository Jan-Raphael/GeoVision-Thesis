"""Report rendering: matplotlib charts, a ReportLab PDF, and a CSV export.

Pure formatters. Each takes a fully assembled
:class:`~app.domain.reporting.ReportData` and returns bytes — none of them
queries anything, which is what guarantees a report cannot disagree with the
dashboard by fetching its own numbers.
"""

from __future__ import annotations

from app.infrastructure.reports.csv_builder import build_csv
from app.infrastructure.reports.pdf_builder import build_pdf

__all__ = ["build_csv", "build_pdf"]
