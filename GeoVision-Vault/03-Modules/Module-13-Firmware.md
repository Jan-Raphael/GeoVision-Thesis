---
title: Module 13 — ESP32-CAM Firmware
type: module
module: 13
status: planned
updated: 2026-08-12
---

# Module 13 — ESP32-CAM Firmware

## Scope
The physical node: capture, geotag, buffer, upload, sleep. Full design in [[ESP32-CAM-Node]];
this note is the build plan.

## Deliverables
- `platformio.ini` — `board = esp32cam`, `platform = espressif32`, libs: TinyGPSPlus,
  RTClib, ArduinoJson; `build_flags` for PSRAM and the server URL.
- `config.h/.cpp` — NVS-backed settings (`server_url`, `wifi_ssid/pass`, `device_id`,
  `device_secret`, `device_name`, `project_code`, `capture_times[]`, `FIRMWARE_VERSION`).
- `camera.h/.cpp` — init (SVGA, quality 12, `fb_count=2`), **warm-up discard of 3 frames**,
  `capture_jpeg()`, reject frames < 8 KB.
- `gps.h/.cpp` — TinyGPS++ over `HardwareSerial(1)`, `fix_with_timeout(60s)`, returns
  lat/lon/HDOP/satellites/UTC + `stale` flag using the last known fix.
- `rtc.h/.cpp` — DS3231 read/set, `set_alarm(next_capture_time)`, drift correction from the
  server's `server_time`.
- `storage.h/.cpp` — SD_MMC **1-bit**, queue at `/queue/`, sidecar JSON, atomic `.tmp`→rename,
  `mark_sent()`, rotation at 80 % full.
- `uploader.h/.cpp` — multipart POST, **HMAC-SHA256 signing via mbedTLS**
  ([[Device-Pairing-Protocol]]), retry with backoff, `MAX_UPLOADS_PER_WAKE=10`, 90 s budget.
- `pairing.h/.cpp` — SoftAP `GeoVision-Setup-XXXX` + captive portal (Wi-Fi creds + pairing
  code, or scan the QR payload), then `POST /pair/claim`, persist to NVS.
- `power.h/.cpp` — battery ADC read, low-battery degradation ladder, `deep_sleep_until_alarm()`.
- `main.cpp` — the state machine from [[ESP32-CAM-Node]], entirely inside `setup()`
  (`loop()` is never reached; the device sleeps instead).
- `firmware/README.md` — wiring table, flashing steps, provisioning walkthrough, troubleshooting.

## Build order within the module
Bring it up **one subsystem at a time**, verifying each on the serial monitor before adding
the next. Debugging a full state machine that has never had a working part is the slowest
possible path.
```
1. blink + serial + deep sleep wake       (proves the board and the toolchain)
2. camera capture → serial size print     (proves PSRAM + sensor)
3. SD write/read                           (proves storage)
4. Wi-Fi connect + plain HTTP GET          (proves networking)
5. GPS fix                                 (slowest to test — do it outdoors)
6. DS3231 read/set/alarm wake              (proves scheduled wake)
7. HMAC signing vs a known-good Python vector  ← verify byte-for-byte before touching the server
8. full multipart upload to /ingest/images
9. pairing flow via SoftAP
10. assemble the complete state machine
11. enclosure, mount, field deploy
```

Step 7 deserves emphasis: generate a canonical string in Python, sign it with a known key,
and assert the ESP32 produces the identical hex digest. Chasing a signature mismatch through
a full upload path is miserable; chasing it with a fixed test vector takes minutes.

## Critical implementation notes
- **SD before network. Always.** A capture that only exists in RAM is a capture you will lose.
- `captured_at` from GPS UTC when available, else DS3231; record which source was used.
- Free the camera framebuffer (`esp_camera_fb_return`) on **every** path, including errors —
  a leak here bricks the next capture.
- Stream the file from SD in chunks during upload; never load a 500 KB JPEG into heap
  alongside the TLS buffers.
- TLS on an ESP32 is memory-hungry: budget ~40 KB, use `setInsecure()` only for local
  development, and pin the CA for production.
- Enable the brownout detector and the task watchdog; on a watchdog trip, log to SD and sleep
  rather than boot-looping and draining the battery.
- Handle `401 DEVICE_REVOKED` by clearing NVS and re-entering provisioning.
- Print a one-line status summary every wake (battery, RSSI, queue depth, upload result) —
  this serial log is your field-debugging lifeline and a thesis figure.

## Dependencies
Module 05 (the server side must exist first). Hardware from the BOM in [[ESP32-CAM-Node]].

## How to run
```bash
cd firmware/esp32cam-node
pio run -t upload && pio device monitor -b 115200
```

## Testing procedure
1. Bench: each of the 11 build-order steps verified individually on serial.
2. HMAC test vector matches Python byte-for-byte.
3. Upload with Wi-Fi on → 201; server row created with correct name and GPS.
4. **Wi-Fi off** → capture still lands on SD; turn Wi-Fi on → backlog uploads with the
   **original** `captured_at`.
5. Power-cycle mid-upload → no corrupt file, no duplicate row (server idempotency).
6. Unpair from the dashboard → next upload 401 → device re-enters provisioning.
7. Deep sleep current measured with a USB power meter; record the number.
8. 72-hour bench soak: capture count == scheduled count, no reboots, battery curve logged.
9. Field deployment: mount at a real site, verify a week of captures and a rising progress
   curve in the dashboard.

## Expected output
A camera that wakes on schedule, captures, geotags, uploads, and sleeps — unattended for
weeks — with the images appearing automatically in the right project folder.

## Done criteria
- [ ] All subsystems verified individually and in the assembled state machine
- [ ] Offline buffering and backlog upload proven
- [ ] Pairing and re-provisioning working
- [ ] Deep-sleep current and battery life measured (not estimated)
- [ ] Deployed on a real site with captures flowing
- [ ] Wiring table and photos captured for the thesis

## Related
[[ESP32-CAM-Node]] · [[Capture-Schedule-and-Power]] · [[Device-Pairing-Protocol]] · [[Module-05-Device-Pairing-and-Ingestion]]
