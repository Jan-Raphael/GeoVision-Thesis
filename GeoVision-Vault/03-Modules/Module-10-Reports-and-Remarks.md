---
title: Module 10 — Reports, Status & Remarks
type: module
module: 10
status: planned
updated: 2026-08-12
---

# Module 10 — Reports (PDF/CSV), Status Derivation & Automatic Remarks

## Scope
Spec **B.4** (the Report button in the project folder) plus the scheduled jobs that keep
`status` and system remarks accurate ([[Project-Status-Rules]]).

## Deliverables
- `application/use_cases/reports/` — `RequestReport`, `GetReportStatus`, `DownloadReport`,
  `ListReports`.
- `infrastructure/reports/pdf_builder.py` — ReportLab document builder.
- `infrastructure/reports/csv_builder.py` — flat export.
- `infrastructure/reports/charts.py` — matplotlib figures (progress curve, stage bars,
  capture histogram) rendered to PNG and embedded in the PDF.
- `infrastructure/tasks/reports.py` — Celery task `reports.generate` (queue `reports`).
- `infrastructure/tasks/maintenance.py` — beat schedule:
  `projects.refresh_status` (every 6 h), `devices.sweep_offline` (every 30 min),
  `remarks.emit_system` (every 6 h), `reports.cleanup_expired` (daily).
- `api/v1/routers/reports.py`.

## PDF report contents
1. **Cover** — project name, code, location, GPS, owner + collaborators, period, generated-at.
2. **Executive summary** — current progress %, macro stage, status, deadline, days remaining,
   on-track/behind verdict.
3. **Stage breakdown** — the five bars with percentages and completion dates.
4. **Progress curve** — displayed vs expected (linear-to-deadline) over the period.
5. **Capture summary** — images captured, rejected, per-device counts, uptime, battery trend.
6. **Image gallery** — the latest image per device per week, each with its GPS and timestamp.
7. **Detection summary** — average object counts per week (activity proxy).
8. **Remarks log** — every remark in the period with type, severity, author, date.
9. **Appendix** — model versions, `algorithm_version`, and a note that AI progress is an
   estimate requiring physical verification.

That last line is a **required disclaimer**: this document could plausibly inform a payment
or scheduling decision, so every report states its estimated nature, the model version behind
it, and that the final 20 % requires human inspection.

## CSV export
```csv
window_start,displayed_pct,raw_pct,macro_stage,foundation_pct,framing_pct,roofing_pct,
finishing_pct,approval_pct,eligible_images,devices_reporting,status,algorithm_version
```
Plus a second CSV of per-image rows (`filename, captured_at, lat, lon, device, stage,
confidence, eligible`) so the data is usable in Excel for the thesis appendix.

## Critical implementation notes
- Generation is **async**: `POST` → `202 {report_id, status:"queued"}`; the UI polls or waits
  for the `report.ready` WebSocket event.
- Weekly period = the last complete Mon–Sun in the project timezone; monthly = the last
  complete calendar month; custom = caller-supplied, capped at 366 days.
- Downloads use short-lived signed URLs; a report of a private project is only downloadable
  by members with `report:generate` (re-check permission at download time, not just at request).
- Reports are immutable once `ready`; regenerating creates a new row (an audit trail of what
  was reported when).
- Empty period → still produce a valid report saying "no captures in this period" rather than
  failing.
- Charts must be generated headless: `matplotlib.use("Agg")` before any pyplot import.
- All timestamps in the report are rendered in the **project's** timezone, with the offset
  shown — a report that says "07:00" without a zone is ambiguous evidence.

## Dependencies
Module 09. `reportlab`, `matplotlib`, `pandas` (optional).

## How to run
```bash
celery -A app.infrastructure.tasks.celery_app worker -Q reports -l info
celery -A app.infrastructure.tasks.celery_app beat -l info
http POST :8000/api/v1/projects/$PID/reports kind=weekly format=pdf "Authorization:Bearer $TOK"
```

## Testing procedure
1. Request weekly PDF → 202, then `ready`, then a downloadable non-empty PDF.
2. Request CSV → correct header, one row per snapshot in range.
3. Empty period → valid "no data" report, status `ready`, not `failed`.
4. Non-member download attempt → 403/404.
5. Expired signed URL → denied.
6. `derive_status` integration: age the last capture past 14 days → `inactive` + remark.
7. Past deadline while incomplete → `delayed` + critical remark.
8. Offline sweep: no heartbeat for 6 h → device `offline`; > 48 h → project remark + notification.
9. Remark dedup: run the emitter twice in an hour → one remark, not two.
10. Timezone: a project in `Asia/Manila` reports 07:00 local, not 23:00 UTC.

## Expected output
A polished multi-page PDF with charts and a geotagged image gallery, downloadable from the
project folder — one of the strongest demo artifacts in the defense.

## Done criteria
- [ ] Weekly / monthly / custom PDF and CSV, generated asynchronously
- [ ] Charts embedded; disclaimer present
- [ ] Permission re-checked at download; signed URLs expire
- [ ] Status derivation + automatic remarks running on schedule, deduplicated
- [ ] Device offline sweep and notifications working

## Related
[[Project-Status-Rules]] · [[Progress-Calculation]] · [[API-Contract]] · [[Module-12-Owner-Dashboard]]
