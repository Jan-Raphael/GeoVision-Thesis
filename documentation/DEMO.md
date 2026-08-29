# Defense demo script

~8 minutes, rehearsed end to end at least once before the real thing (Module-16's own done
criterion). Run `make deploy-demo` first to confirm every container is healthy and get the
URLs printed to copy into a browser.

**Offline fallback**: assume the venue's Wi-Fi fails. `make deploy-seed` loads sample
projects with real-looking data (progress curves, images, reports) so every step below
works with no live camera and no internet — narrate step 4 ("here's what a real capture
looks like") over the seeded data instead of a live device if the network isn't
cooperating.

## 1. Homepage as a visitor (30s)

Open `https://localhost` in a private/incognito window — no login. Point out: public
projects listed with GPS and a "last capture X ago" timestamp, no auth wall for the
public-facing half of the system.

## 2. Open a project (30s)

Click into one project. Progress percentage, the stage timeline, geotagged images. This
is the number the whole AI pipeline exists to produce — say so explicitly before moving on.

## 3. Log in, create a project live (60s)

Log in as the seeded owner account. Profile page, then create a brand-new project on
stage, live, in front of the panel — not a pre-made one.

## 4. Pair a camera (90s)

Project Folder -> Devices -> Pair Camera. Show the QR + pairing code on screen. If real
ESP32-CAM hardware is available and powered on: pair it for real. If not (hardware not
yet on site, or Wi-Fi is uncooperative): narrate this step over
`backend/scripts/simulate_device.py` or `backend/scripts/capture_and_upload.py` run from a
laptop instead — both hit the exact same ingest API a real camera does, so the pipeline
being demonstrated is identical either way.

## 5. A capture flows through the system (90s)

Trigger an upload (real camera, or `capture_and_upload.py --code <pairing-code> --source
file --path <a-site-photo.jpg>` for a one-shot upload). Watch it **appear on
the dashboard without a refresh** — this is Module 14's WebSocket push, worth naming
explicitly since it's easy for a panel to assume it's just a page reload. Progress moves.

## 6. Show the AI detail (60s)

Open the capture's detail view: predicted stage, confidence, the preprocessing
before/after (Module 06), and — if Module 08 has unblocked by defense day — the YOLO
detection overlay. If it hasn't: say so plainly ("YOLO training is blocked on annotation,
which is ongoing — here's the classifier's honest accuracy on held-out data instead") and
move to the evaluation figures in step 9. An honest gap stated once beats a dodged
question later.

## 7. Generate a PDF report (45s)

From the project page, generate and open a report. Nine sections, three charts, the
required disclaimer — point out the disclaimer specifically, since it's a deliberate
design choice (the AI number is an estimate, not a certified measurement) worth defending
on its own.

## 8. Approve a near-complete project (45s)

Show a seeded project sitting around 80%. Approve it -> 100%, and explain the
accountability rationale: completion is a human sign-off, not something the model claims
for itself.

## 9. Close on the evaluation figures (60s)

`ai/tests` and `gv-evaluate`'s output: the confusion matrix, the ResNet18 vs MobileNetV3
comparison table, the raw-vs-smoothed progress plot. These numbers are honestly below the
85% target — say the actual figures out loud (ResNet18 31.7% top-1, MobileNetV3 35.8%)
and name the reason (dataset size/imbalance, Foundation-class shortfall specifically), the
same way the vault itself documents it. A defended, honest weak number is stronger than a
number the panel suspects is cherry-picked.

## Before you walk in

- [ ] `make deploy-up` && `make deploy-migrate` && `make deploy-seed`, rehearsed at least
      once end to end, timed
- [ ] `make deploy-demo` shows every container healthy
- [ ] A charged, paired ESP32-CAM if hardware is ready — otherwise `capture_and_upload.py`
      tested and ready as the fallback
- [ ] This laptop's Wi-Fi hotspot as a backup network if venue Wi-Fi is unreliable
- [ ] `documentation/screenshots/` open in a second tab in case a live step fails entirely

## Related

[[Module-16-Deployment]] · [DEPLOYMENT.md](DEPLOYMENT.md) · [RUNBOOK.md](RUNBOOK.md)
