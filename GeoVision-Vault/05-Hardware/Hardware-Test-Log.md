---
title: Hardware Test Log
type: hardware
status: living
updated: 2026-08-15
---

# Hardware Test Log

Module 15's test pyramid has one tier no script can fill in: **manual, logged,
recorded in the thesis** — the 72-hour soak, offline buffering, and battery
curve. This note is where those go once there is a camera to run them on.

> **Status as of this writing:** the ESP32-CAM is ordered (P1-1); the
> construction site and written permission to photograph it are arranged,
> with the site expected ready in 3–4 weeks. Nothing below is measured yet —
> that is expected, not a gap in Module 15 itself, which is why this
> template exists ahead of the hardware rather than after it. Fill in each
> section as the corresponding test actually runs; do not estimate a number
> here that a multimeter or a clock should produce.

## Before the first test

- [ ] Record the exact board revision and confirm the pinout against
  [[ESP32-CAM-Node]] (Q2) — a silkscreen or datasheet photo is enough.
- [ ] Record firmware version under test (git commit hash).
- [ ] Confirm the mount is rigid and photograph the installation — the
  homography and ROI occlusion mask both depend on the camera never moving
  (see [[ESP32-CAM-Node]] — "fixed angle is a hard requirement").
- [ ] Confirm `GV_DEVICE_SECRET_KEY` is set and backed up before pairing a
  camera outside a dev machine (ADR-020) — losing it means every camera
  needs re-provisioning by hand, on site.

## 1. Capture and upload — functional check

| Check | Result | Notes |
|---|---|---|
| Camera boots and reaches `Capture` state | ☐ pass ☐ fail | |
| GPS acquires a fix within 60 s (warm) | ☐ pass ☐ fail | record time-to-fix |
| Image written to microSD before any network attempt | ☐ pass ☐ fail | pull SD, inspect `/queue/` |
| Upload succeeds over site Wi-Fi | ☐ pass ☐ fail | |
| Server assigns the expected filename pattern | ☐ pass ☐ fail | `<CODE>_<UTC ts>_<seq>.jpg` |
| `device.paired` / heartbeat events visible in dashboard | ☐ pass ☐ fail | |

## 2. Offline buffering (Reliability rules, [[ESP32-CAM-Node]])

Disconnect the site Wi-Fi (or block the AP) for a deliberate window, then restore it.

| Scenario | Expected | Observed |
|---|---|---|
| No Wi-Fi at capture time | Image stays on SD, retried next wake | |
| Backlog upload after Wi-Fi returns | Original `captured_at` preserved, not upload time | |
| Duplicate upload after a lost ACK | Idempotent 200, no reprocessing | |
| SD > 80% full | `/sent/` rotates oldest-first | |
| Brownout during SD write | `.tmp` file, no corrupt partial write survives | |

**Outage window tested:** ____ hours. **Images recovered on reconnect:** ____ / ____.

## 3. 72-hour soak

| Field | Value |
|---|---|
| Start (local time, date) | |
| End | |
| Capture schedule under test | e.g. `07:00, 16:00` |
| Scheduled captures | |
| Successful captures | |
| Capture success rate | ____ % |
| Missed captures, with cause (if known) | |
| Watchdog resets observed | |
| Any manual intervention required | |

## 4. Battery / power curve ([[Capture-Schedule-and-Power]])

The design budget estimates **~1.75 mAh/wake** and **~6–10 mA** deep-sleep
draw on the as-shipped board. Both are explicitly flagged in the vault as
estimates to replace with a multimeter reading — this is that reading.

| Measurement | Method | Value |
|---|---|---|
| Deep-sleep current draw | USB power meter / multimeter in series | ____ mA |
| Active current draw (capture + upload) | same, peak reading | ____ mA |
| Per-wake energy cost | computed from the above + wake duration | ____ mAh |
| Battery capacity used | power bank/cell rating | ____ mAh |
| Projected runtime at current schedule | capacity ÷ daily draw | ____ days |
| **Measured** runtime (if the soak ran to depletion) | | ____ days |

Board configuration tested (check one — see [[Capture-Schedule-and-Power]] for the trade-offs):
- [ ] As-shipped (power LED + stock AMS1117 LDO)
- [ ] Power LED desolder
- [ ] Low-Iq LDO swap
- [ ] TPL5110 timer + DS3231 alarm gating

## 5. Image quality in the field

| Check | Result |
|---|---|
| Quality gate rejection rate (blur/dark/occlusion) over the soak | ____ % of captures |
| Manually reviewed sample matches the intended construction stage | ☐ yes ☐ no, notes: |
| Weather conditions during the window | |

## 6. Known issues / follow-ups

Log anything found here, and link it forward to [[Open-Questions]] or a new
ADR if it changes a documented assumption (e.g. the pinout, the power
budget, or the recommended capture schedule).

## Related
[[ESP32-CAM-Node]] · [[Capture-Schedule-and-Power]] · [[Device-Pairing-Protocol]] ·
[[Module-13-Firmware]] · [[Module-15-Testing-and-Evaluation]] · [[Evaluation-Plan]]
