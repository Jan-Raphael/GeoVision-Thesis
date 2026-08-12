---
title: Project Status Rules
type: domain
status: canonical
updated: 2026-08-12
---

# Project Status & Remarks — derivation rules

`projects.status` is **derived**, never hand-set (except `archived`). Recomputed by the
Celery beat job `projects.refresh_status` every 6 hours and after every progress update.
Pure function in `domain/services/status.py`.

## Precedence (first match wins)

```python
def derive_status(p: ProjectSignals, now: datetime) -> ProjectStatus:
    if p.archived_at:                       return ARCHIVED
    if p.approval_state == APPROVED:        return COMPLETED
    if p.days_since_last_capture > 14:      return INACTIVE
    if p.is_behind_schedule:                return DELAYED
    return ACTIVE
```

| Status | Condition | UI badge |
|---|---|---|
| `completed` | owner approved the final 20 % | green |
| `inactive` | no image in **> 14 days** | grey |
| `delayed` | behind schedule (below) | amber |
| `active` | none of the above | blue |
| `archived` | owner archived | muted |

### `is_behind_schedule`

```
expected_pct(now) = clamp( (now - start_date) / (deadline_date - start_date) * 80, 0, 80 )
is_behind_schedule = displayed_pct < expected_pct - DELAY_TOLERANCE_PP     # 10 pp
                     or (now > deadline_date and approval_state != 'approved')
```

Linear planned curve unless the owner uploads a planned schedule (future enhancement, see
[[Open-Questions]]). `DELAY_TOLERANCE_PP = 10.0`.

## Device online/offline (separate from project status)

`devices.status` — the spec's "offline" is a **device** property surfaced on the project's
Devices panel, not the project status itself:

| Value | Condition |
|---|---|
| `online` | heartbeat or upload within **6 h** |
| `offline` | last seen > 6 h but ≤ 30 d |
| `revoked` | unpaired by owner |
| `paired` | paired, never yet seen |
| `unpaired` | token issued, not claimed |

A project whose only device is `offline` for > 48 h gets an automatic remark and a
`device_offline` notification — this is the visible "offline" state the spec asks for.

## Automatic system remarks

Written by the worker, `remark_type='system'`, `author_id = NULL`:

| Trigger | Type | Severity | Message |
|---|---|---|---|
| no capture > 14 d | `inactivity` | warning | "No new captures in {n} days. Check the camera and its power source." |
| behind schedule > 10 pp | `delay` | warning | "Progress is {n} pp behind the expected schedule for the set deadline." |
| past deadline, not approved | `delay` | critical | "Deadline of {date} has passed and the project is not yet marked complete." |
| sustained regression (3 windows) | `regression` | warning | "Progress regression detected — possible rework, demolition, or camera obstruction." |
| all device offline > 48 h | `system` | warning | "All paired cameras have been offline for {n} hours." |
| reached 80 % | `system` | info | "All exterior stages complete. Manual inspection required to finalize the project." |
| ≥ 3 consecutive rejected captures | `system` | info | "Recent captures were rejected for image quality (blur/darkness/obstruction)." |

**Weather remarks** (`remark_type='weather'`) are **manual** in v1 — the owner writes
"Typhoon expected, delay is justified", optionally with `effective_from/to`. While a weather
remark is in effect, the `delay` status still shows but the UI displays the justification
beside it. Automatic weather ingestion via a public API is a documented future enhancement
([[Open-Questions]]), not v1 scope.

Deduplication: a system remark of the same `(project_id, remark_type)` is not re-emitted
within 72 h.

## Related
[[Progress-Calculation]] · [[Domain-Model]] · [[Module-10-Reports-and-Remarks]]
