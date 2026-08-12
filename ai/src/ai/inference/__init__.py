"""The serving path used by the Celery worker.

Implemented in **Module 09**. Spec:
``GeoVision-Vault/03-Modules/Module-09-Inference-Service.md``.

``InferenceService`` loads the active classifier and detector **once per worker
process** (loading a checkpoint per task is the classic performance bug here)
and exposes a single ``predict()`` entrypoint.

Planned contents: ``service.py``, ``schemas.py``.
"""

from __future__ import annotations
