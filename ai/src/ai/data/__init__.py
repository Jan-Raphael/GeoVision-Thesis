"""Dataset assembly, transforms, and leakage-free splitting.

Implemented in **Module 07**. Spec: ``GeoVision-Vault/06-Dataset/Dataset-Spec.md``.

Planned contents:

``datamodule.py`` ``ConstructionStageDataset`` + dataloader builders
``transforms.py`` Albumentations train/val/test pipelines
``splitter.py``   grouped stratified 70/15/15 split

.. warning::
   The split is grouped **by site**, not random. Fixed-angle cameras produce
   many near-identical frames of one building; a random split leaks that
   building across train and test and inflates accuracy. See ADR-009.
"""

from __future__ import annotations
