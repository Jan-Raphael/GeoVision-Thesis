"""Stage mapping and the progress aggregation algorithm.

Implemented in **Module 09**. Spec:
``GeoVision-Vault/02-Domain/Progress-Calculation.md``.

.. important::
   Everything in this subpackage stays **pure**: no I/O, no ORM, no torch.
   It is the core thesis contribution and must be walkable line-by-line during
   the defense, and unit-testable without a database or a GPU. The
   import-linter contract in ``backend/.importlinter`` and the review checklist
   both depend on this staying true.

Planned contents:

``constants.py``  single definition site for every threshold
``mapping.py``    fine class -> macro stage -> nominal percentage
``estimator.py``  per-image raw progress + confidence/quality gating
``aggregator.py`` median -> weighted multi-camera mean -> EMA -> ratchet
"""

from __future__ import annotations
