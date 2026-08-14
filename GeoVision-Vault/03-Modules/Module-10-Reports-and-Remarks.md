---
title: Module 10 — Reports, Status & Remarks
type: module
module: 10
status: done
updated: 2026-08-15
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
.\dev.ps1 worker    # includes the `reports` queue
http POST :8000/api/v1/projects/$PID/reports kind=weekly report_format=pdf      "Authorization:Bearer $TOK"
```

> The Celery app is `app.worker.celery_app` (see [[Module-09-Inference-Service]]), and beat
> is not wired yet — it belongs to the deferred half below.

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
- [x] Weekly / monthly / custom PDF and CSV, generated asynchronously
- [x] Charts embedded; disclaimer present
- [x] Permission re-checked at download; signed URLs expire
- [x] Status derivation + automatic remarks running on schedule, deduplicated
- [x] Device offline sweep and notifications working

## Delivered — the reports half (2026-08-14)

**The module was split at its own seam.** Its title names two things: report *generation*, and
the scheduled jobs that keep status and remarks fresh. They share nothing but a module number
— one renders documents on demand, the other is a beat schedule — so the first half shipped
alone rather than half-shipping both.

| | |
|---|---|
| `app/domain/services/reporting.py` | `ReportPeriod`, `resolve_period` — what "weekly" means |
| `app/domain/reporting.py` | `ReportData`, `CaptureRow` — the assembled bundle (ADR-030) |
| `app/infrastructure/reports/charts.py` | progress curve, stage bars, capture histogram (Agg) |
| `app/infrastructure/reports/pdf_builder.py` | the 9-section ReportLab document |
| `app/infrastructure/reports/csv_builder.py` | both tables, RFC 4180 |
| `app/worker/reports.py` | `reports.generate`, on its own `reports` queue |
| `app/api/v1/routers/reports.py` | request · list · status · download |

**803 tests.** A real 5-page, 114 KB PDF renders in a unit test — including an assertion that
the required disclaimer text is present, checked with ReportLab's page compression disabled
because a naive byte search on a compressed stream finds nothing and would have passed
vacuously.

Three choices worth defending:

- **Periods are always complete, and always in the project's timezone.** A weekly report run
  on a Wednesday covers the previous Monday–Sunday, not the three days so far; a partial
  period makes the curve appear to flatten for no reason. The zone matters because a Manila
  day starts at 16:00 UTC the day before — a naive UTC range silently reports the wrong days.
- **The CSV is one file with two tables**, blank-line separated, each with its own header. The
  format enum is `pdf|csv` and a download serves one object; a ZIP would have been a third
  format in all but name.
- **An empty period still produces a valid report** saying so. "No captures in three weeks" is
  one of the more useful things a report can say, and it is exactly when an owner wants a
  document to show somebody.

## Delivered — the maintenance half (2026-08-15)

`app/worker/maintenance.py`, on Celery **beat**, all four jobs idempotent and safe to run
twice — a beat schedule redelivers after a restart, and a maintenance job that double-posts is
worse than one that occasionally skips.

| Task | Cadence | What it does |
|---|---|---|
| `projects.refresh_status` | 6 h | recompute derived status, **write only when it moves** |
| `remarks.emit_system` | 6 h | write due remarks, deduplicated over 72 h |
| `devices.sweep_offline` | 30 min | mark silent cameras offline; alert a wholly dark site |
| `reports.cleanup_expired` | daily | delete report files past `GV_REPORT_RETENTION_DAYS` (90) |

`app/domain/services/remarks.py` holds the message table from
[[Project-Status-Rules]] as a **pure function** of a project's signals — 15 unit tests pin the
wording and every threshold, with no database. Deduplication is deliberately *not* in there:
the rules say what is true now, and the job decides whether it has already been said. Mixing
them would make a rule untestable without a database, and 72 hours is a delivery concern
rather than a fact about the project.

Four behaviours worth stating:

- **Status is written only when it changes.** The column exists to keep project *lists*
  cheap; rewriting every row every six hours would churn the table and its indexes for no
  reader's benefit. A test asserts `updated_at` is untouched for a healthy project.
- **Archived and approved projects are never nagged.** Both were settled deliberately;
  telling their owner they are behind schedule is noise about a decision already made.
- **One live camera keeps a site reporting.** The offline *device* threshold is 6 h; the
  *whole-site* alert is 48 h and fires only when every paired camera is silent. Waking an
  owner because one camera missed a capture teaches them to ignore the alerts that matter.
- **Report cleanup deletes the file first.** If object storage is unreachable the row is left
  alone so the next run retries — deleting it would orphan the blob permanently, because
  nothing else records that key.

Run it with `.\dev.ps1 beat` alongside `.\dev.ps1 worker`; beat only publishes.

## Related
[[Project-Status-Rules]] · [[Progress-Calculation]] · [[API-Contract]] · [[Module-12-Owner-Dashboard]]
