---
title: Thesis Mapping
type: thesis
status: canonical
updated: 2026-08-12
---

# Thesis Mapping — vault → manuscript

Which vault note feeds which chapter, so the write-up is assembly rather than invention.

| Chapter | Section | Source notes |
|---|---|---|
| **1. Introduction** | Background, problem, objectives, scope & limitations, significance | [[Master-Architecture]] §1, [[Open-Questions]] (limitations) |
| **2. Review of Related Literature** | Construction progress monitoring, CNN image classification, transfer learning, object detection, IoT capture nodes, geotagging | *(to write — track sources in `thesis/references.bib`)* |
| **3. Methodology** | 3.1 System architecture | [[Master-Architecture]], [[Repository-Structure]] |
| | 3.2 Hardware design | [[ESP32-CAM-Node]], [[Capture-Schedule-and-Power]] |
| | 3.3 Communication & security | [[Device-Pairing-Protocol]], [[Realtime-Events]] |
| | 3.4 Dataset construction | [[Dataset-Spec]], [[Annotation-Guide]] |
| | 3.5 Image preprocessing | [[Module-06-AI-Preprocessing]] |
| | 3.6 Model architecture & training | [[Module-07-Classifier-Training]], [[Module-08-YOLO-Detection]] |
| | 3.7 Progress estimation algorithm | [[Progress-Calculation]], [[Construction-Stages]] |
| | 3.8 Software design (DB, API, UI) | [[Domain-Model]], [[API-Contract]], [[Module-11-Public-Dashboard]], [[Module-12-Owner-Dashboard]] |
| | 3.9 Evaluation methodology | [[Evaluation-Plan]] |
| **4. Results & Discussion** | Model results, comparison, ablation, progress accuracy, system performance, usability | [[Evaluation-Plan]] §1–7 + `outputs/evaluation/` |
| **5. Conclusion & Recommendations** | Findings, limitations, future work | [[Open-Questions]], [[ADR-Index]] |
| **Appendices** | ERD, API reference, schematics, annotation log, ADRs, source listing | [[Domain-Model]], [[API-Contract]], [[ESP32-CAM-Node]], [[Annotation-Guide]], [[ADR-Index]] |

## Required figures (generate, don't hand-draw)

| # | Figure | Produced by |
|---|---|---|
| 1 | System context diagram | Mermaid in [[Master-Architecture]] → export PNG |
| 2 | End-to-end sequence diagram | Mermaid in [[Master-Architecture]] |
| 3 | ERD | Mermaid in [[Domain-Model]] / SchemaSpy |
| 4 | Hardware block diagram + wiring | Fritzing/draw.io → `documentation/` |
| 5 | Firmware state machine | Mermaid in [[ESP32-CAM-Node]] |
| 6 | Preprocessing before/after strip | `ai/preprocessing` demo script |
| 7 | Training curves (loss/acc/LR) | `outputs/runs/<id>/curves.png` |
| 8 | Confusion matrix | `ai/evaluation/report.py` |
| 9 | Accuracy vs latency scatter | `ai/evaluation/benchmark.py` |
| 10 | Sample YOLO detections | `ai/evaluation/report.py` |
| 11 | Raw vs smoothed progress series | `ai/progress` demo on real data |
| 12 | Dashboard screenshots (public + owner + pairing modal) | Playwright screenshot script |
| 13 | Deployed hardware photos | camera, in situ, with scale reference |
| 14 | Battery discharge curve | `device_events` export |

## Defense — questions to have answers ready for

1. Why ResNet18 and not a deeper/newer model? *(dataset size, latency, overfitting risk, and the comparison table)*
2. Why is TensorFlow excluded? *(project constraint; PyTorch justified on research ecosystem + deployment fit)*
3. How do you know the model isn't memorizing the site? *(grouped split — [[Dataset-Spec]])*
4. What happens on a rainy/occluded day? *(quality gate → reject; median + EMA + ratchet)*
5. Why can't the AI mark a project 100 % complete? *(accountability; [[Progress-Calculation]] §5)*
6. Why HTTP upload if the professor said WebSocket? *(ADR-003 in [[Realtime-Events]])*
7. How is a fake device prevented from injecting progress? *([[Device-Pairing-Protocol]])*
8. Are your stage percentages arbitrary? *(reference table + engineer review — [[Construction-Stages]])*
9. How long does the battery last? *(measured curve, [[Capture-Schedule-and-Power]])*
10. What are the limitations? *([[Open-Questions]] — have an honest list ready; examiners trust candidates who name their own weaknesses first)*

## Related
[[Evaluation-Plan]] · [[Master-Architecture]] · [[Open-Questions]] · [[ADR-Index]]
