---
title: Capture Schedule and Power
type: hardware
status: canonical
updated: 2026-08-12
---

# Capture Schedule & Power Budget

## Owner-configured schedule

Set in the Project Folder → Devices panel. Stored on `devices.capture_schedule`, pulled by
the device on every heartbeat via `GET /ingest/config`.

```jsonc
{
  "times": ["07:00", "16:00"],       // local wall-clock, project timezone
  "tz": "Asia/Manila",
  "jitter_s": 120,                   // randomize ±2 min so 50 devices don't all POST at 07:00:00
  "retry_window": "12:00",           // extra wake purely to drain the upload backlog
  "enabled": true
}
```

**Recommended default: 2 captures/day at 07:00 and 16:00.** Rationale:
- Daylight at both ends of the working day, before and after the day's work.
- Avoids solar noon (harsh shadows, blown highlights on concrete).
- Two samples/day gives the daily median something to reject against without meaningfully
  costing battery.

Constraints enforced by the API: 1–6 captures/day, minimum 60 min apart, `times` must be
valid `HH:MM`.

## Power budget (10 000 mAh power bank @ 5 V, ~85 % regulator efficiency)

| Phase | Current | Duration | mAh/wake |
|---|---|---|---|
| Boot + peripheral init | ~80 mA | 3 s | 0.07 |
| Camera warm-up + capture | ~180 mA | 4 s | 0.20 |
| GPS fix (warm) | ~45 mA | 30 s | 0.38 |
| SD write | ~100 mA | 1 s | 0.03 |
| Wi-Fi connect + upload (500 KB) | ~220 mA | 15 s | 0.92 |
| Heartbeat + config | ~180 mA | 3 s | 0.15 |
| **Per wake** | | ~56 s | **≈ 1.75 mAh** |
| Deep sleep | ~6–10 mA (board-dependent) | remainder | ~0.2 Ah/day |

> The AI-Thinker board's deep-sleep draw is dominated by the **onboard AMS1117 LDO and the
> power LED**, not the ESP32 (which sleeps at ~10 µA). Expect ~6–10 mA as shipped.
> **Mitigations, in order of payoff:** desolder the power LED, bypass/replace the AMS1117
> with a low-Iq regulator, or gate the whole board with a TPL5110 timer + the DS3231 alarm.

| Configuration | Daily draw | Runtime on 10 000 mAh |
|---|---|---|
| As-shipped board, 2 captures/day | ~0.25 Ah | **~5–6 weeks** |
| LED removed + low-Iq LDO | ~0.02 Ah | months (solar unnecessary) |
| 4 captures/day, as-shipped | ~0.26 Ah | ~5 weeks |

The ≥ 14-day NFR in [[Master-Architecture]] is met with comfortable margin even without
board modification. **Measure the real deep-sleep current with a multimeter/USB meter and
put that number in the thesis** — measured beats estimated at defense.

## Battery reporting

Divider on an ADC pin (e.g. 100 kΩ/100 kΩ) → `battery_mv` on every heartbeat, stored on
`device_events` and denormalized to `devices.last_battery_mv`. Thresholds:

| Level | Action |
|---|---|
| < 3.5 V (1S Li-ion) | `low_battery` notification to the owner |
| < 3.3 V | skip GPS (biggest optional cost), capture + upload only |
| < 3.2 V | capture to SD only, no Wi-Fi; upload when charged |

## RTC alarm vs. `esp_sleep_enable_timer_wakeup`

Use the **DS3231 alarm** as the primary wake source (`ext0` wakeup on the SQW pin):
the ESP32's internal RC timer drifts seconds per hour, so over a week a timer-based node
wanders far off its scheduled time. The DS3231 is ±2 ppm (≈1 min/year) and keeps the
timestamp trustworthy — which matters because `captured_at` drives the aggregation window
in [[Progress-Calculation]]. The internal timer is the fallback if the RTC is absent.

RTC drift correction: every heartbeat response carries `server_time`; if `|drift| > 30 s`
the firmware rewrites the DS3231.

## Environmental

IP65 enclosure, silica gel packet, downward-angled cable glands, clear acrylic window
(anti-fog film), lens hood/sunshade to cut flare, and a monthly wipe of the window in the
maintenance checklist. Tropical site conditions (Philippines: heat, humidity, typhoons) are
a real risk to the data continuity story — cover this in the thesis limitations section.

## Related
[[ESP32-CAM-Node]] · [[Device-Pairing-Protocol]] · [[Progress-Calculation]] · [[Module-13-Firmware]]
