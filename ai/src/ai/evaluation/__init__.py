"""Metrics, benchmarks, and thesis figure generation.

Implemented in **Module 15**. Spec:
``GeoVision-Vault/07-Thesis/Evaluation-Plan.md``.

Every figure in the manuscript is produced by code here, never hand-edited -
the model will be retrained late, and hand-made charts cannot be regenerated.

Contents:

- ``metrics.py`` — classifier metrics: accuracy, per-class P/R/F1, macro-F1,
  confusion matrix, mean absolute ordinal error, top-k accuracy, calibration.
- ``benchmark.py`` — inference latency/throughput, measured through the
  ``StageClassifier``/``ObjectDetector`` protocols so the same code benchmarks
  the stub today and trained weights tomorrow.
- ``detector_eval.py`` — YOLO mAP@0.5 / mAP@0.5:0.95, and the classifier vs.
  rule-based-from-object-counts agreement experiment.
- ``progress_eval.py`` — evaluates ``ai.progress.aggregator`` itself: MAE
  against a ground-truth curve, stage-transition lag, monotonicity
  violations, jitter reduction.
- ``report.py`` — writes every result above to ``outputs/evaluation/<run_id>/``
  as CSV/JSON tables and PNG figures, with a reproducibility manifest.
- ``run_all.py`` — the ``gv-evaluate`` CLI that runs everything currently
  possible and lists what still needs real weights or a labelled dataset.
"""

from __future__ import annotations
