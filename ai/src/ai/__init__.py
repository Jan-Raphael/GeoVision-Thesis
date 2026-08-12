"""GeoVision AI package.

Standalone by design: everything here runs without the backend
(``python -m ai.training.train_classifier``). The backend imports *this*
package; this package must never import from ``backend``. See ADR-011.

Subpackages
-----------
``preprocessing``
    OpenCV pipeline and the image quality gate (Module 06).
``data``
    Dataset assembly, Albumentations transforms, leakage-free splitting (Module 07).
``models``
    Backbone wrappers behind shared protocols: ResNet18, MobileNetV3, YOLOv8.
``training``
    Training loops, callbacks, CLI entrypoints (Modules 07-08).
``progress``
    Stage mapping and the progress aggregator - pure functions, no I/O (Module 09).
``inference``
    The serving path used by the Celery worker (Module 09).
``evaluation``
    Metrics, benchmarks, and thesis figure generation (Module 15).
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
