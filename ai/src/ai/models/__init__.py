"""Model wrappers behind shared protocols.

Implemented in **Modules 07-08**. Specs:
``Module-07-Classifier-Training.md``, ``Module-08-YOLO-Detection.md``.

Every model is reached through a Protocol declared in ``base.py``
(``StageClassifier``, ``ObjectDetector``), so callers depend on the interface
rather than on a concrete backbone. Two payoffs:

1. ResNet18 / MobileNetV3 / a future model swap with no caller changes.
2. ``StubClassifier`` satisfies the same protocol, which is what lets Modules
   09-14 be built and tested **before any dataset exists**.

Planned contents: ``base.py``, ``resnet18.py``, ``mobilenetv3.py``,
``yolov8.py``, ``stub.py``.
"""

from __future__ import annotations
