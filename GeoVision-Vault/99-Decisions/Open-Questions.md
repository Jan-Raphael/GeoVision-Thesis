---
title: Open Questions & Deferred Scope
type: decisions
status: living
updated: 2026-08-12
---

# Open Questions, Assumptions & Deferred Scope

Three lists. Keep them current — the third one is your thesis "Limitations and Future Work"
chapter, written incrementally instead of invented the night before submission.

---

## 1. Needs a decision or verification (blocking-ish)

| # | Question | Why it matters | Owner | Status |
|---|---|---|---|---|
| Q1 | Are the nominal stage percentages in [[Construction-Stages]] realistic? | They set every progress number in the system. Get a civil engineer / project manager to review and cite it. | you + advisor | **open** |
| Q2 | Exact ESP32-CAM pinout for GPS + DS3231 on *your* board revision | Board revisions differ; camera uses most GPIOs. Verify with a multimeter and record in [[ESP32-CAM-Node]]. | you | **open** |
| Q3 | Which real construction site(s) can you deploy on, and with whose permission? | Real captures are what make this a thesis instead of a demo. Written permission also matters for the images you publish. | you | **open** |
| Q4 | Where does the server run for the live deployment? | The ESP32 needs a reachable HTTPS endpoint (Cloudflare Tunnel is the cheap answer). | you | **open** |
| Q5 | How many labelled images can you realistically gather before training? | Determines whether the ≥ 85 % target is achievable ([[Dataset-Spec]]). | you | **open** |
| Q6 | Timezone/window policy — daily windows in `Asia/Manila`? | Affects aggregation boundaries and reports. Default assumed daily/Manila. | you | assumed |
| Q7 | GPU available for training? | If not, budget Colab/Kaggle time for YOLO ([[Module-08-YOLO-Detection]]). | you | **open** |
| Q8 | Does the panel expect a specific documentation format (IEEE/school template)? | Cheap to ask now, expensive to reformat later. | you + advisor | **open** |
| Q9 | **Install Docker Desktop (WSL2 backend).** | Not installed on the dev machine as of 2026-08-13. Module 01 verifies fully without it, but Module 02 onward needs a real PostgreSQL, and ADR-013 puts the Celery worker in a Linux container. This is the one prerequisite blocking the next module. | you | **open — do first** |
| Q10 | Where will trained checkpoints (`models/*.pt`) live, given they are git-ignored? | They are too large for git and must still be reproducible/shareable for the defense. Options: GitHub Release assets, Google Drive with a documented hash, or git-lfs. | you | **open** |

## 2. Assumptions made (revisit if any proves false)

1. Cameras are **rigidly fixed**; the viewpoint does not change across the project. If a
   camera is bumped, its homography and history are invalidated — currently handled only by
   re-calibration.
2. One primary building per camera view.
3. Construction proceeds in the canonical order in [[Construction-Stages]] (renovations and
   phased/multi-tower builds are out of scope).
4. Daylight captures only; night imagery is rejected by the quality gate.
5. Site Wi-Fi is available at least intermittently.
6. Progress is estimated from **exterior** appearance only — interior work is invisible to
   the system. This is a real and significant limitation: a building can be 40 % complete
   externally and far along internally. **Say this plainly in the thesis.**
7. Linear expected-progress curve for the delay calculation ([[Project-Status-Rules]]).
8. One project = one building.

## 3. Deferred to future work (explicitly out of v1 scope)

| Feature | Note |
|---|---|
| Blueprint/3D-render-aware AI | ADR-010 — v1 stores references but does not model them |
| Automatic weather ingestion (PAGASA/OpenWeather) to justify delays | v1 uses manual weather remarks |
| Email verification + password reset | column exists; flow deferred |
| Push/email/SMS notifications | in-app only in v1 |
| Multi-building and phased projects | one building per project |
| Interior progress monitoring | needs indoor cameras or manual input |
| Device OTA firmware updates | manual flashing in v1 |
| Remote "capture now" over a device WebSocket | only meaningful for mains-powered nodes |
| Solar power | documented in [[Capture-Schedule-and-Power]], not built |
| Mobile app | the dashboard is responsive instead |
| Cost/budget tracking, Gantt integration | out of scope |
| Multi-tenant orgs / teams | projects + members are sufficient for v1 |
| Model retraining from production captures (active learning) | strong future-work section |
| Semantic segmentation for finer progress | a natural next research step |
| Time-lapse video export | nice demo feature, low thesis value |
| i18n / Filipino localization | English only in v1 |

## 4. Known risks

| Risk | Impact | Mitigation |
|---|---|---|
| Not enough training data | model underperforms the target | start collecting now; time-lapse frames; transfer learning; report honestly |
| Hardware arrives late or DOA | no field deployment | order early, buy a spare ESP32-CAM, build against `simulate_device.py` |
| Site access withdrawn | no real captures | secure a backup site; keep a public time-lapse fallback |
| Typhoon damages the deployment | data gap | IP65 enclosure, SD buffering, and document the gap (it is itself a finding) |
| Scope creep | nothing finishes | [[Build-Order]] is the contract; new ideas go in section 3 above |
| Model plateaus below 85 % | weak headline result | ablations + error analysis turn a weak number into a strong discussion; a well-analyzed 78 % beats an unexplained 85 % |

## Log

| Date | Change |
|---|---|
| 2026-08-13 | Module 01 shipped. ADR-011…014 recorded (packaging, tooling, Celery/Windows, stringzilla). Added Q9 (Docker Desktop) and Q10 (checkpoint distribution). |
| 2026-08-12 | Initial architecture finalized; ADR-001…010 recorded |

## Related
[[ADR-Index]] · [[Build-Order]] · [[Thesis-Mapping]] · [[Progress-Log]]
