"""Training loops, callbacks, and CLI entrypoints.

Implemented in **Modules 07-08**.

Required features (all specified in ``Module-07-Classifier-Training.md``):
early stopping, LR scheduling, mixed precision on GPU with a working **CPU
fallback**, checkpointing by best macro-F1, resume, and a per-run artifact
directory under ``outputs/runs/<run_id>/`` so every thesis number is traceable.

Planned contents: ``trainer.py``, ``callbacks.py``, ``train_classifier.py``,
``train_detector.py``.
"""

from __future__ import annotations
