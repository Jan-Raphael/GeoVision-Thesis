"""OpenCV preprocessing pipeline and image quality gate.

Implemented in **Module 06**. Spec:
``GeoVision-Vault/03-Modules/Module-06-AI-Preprocessing.md``.

The same pipeline runs at training time and at serving time; that is what
prevents train/serve skew. Planned contents:

``pipeline.py``    composable ``PreprocessingPipeline`` built from YAML
``perspective.py`` homography rectification to a canonical facade view
``normalize.py``   CLAHE on the LAB L-channel + gray-world white balance
``denoise.py``     bilateral filter (edge-preserving)
``resize.py``      aspect-preserving resize + letterbox pad
``quality.py``     blur / darkness / occlusion gate
``calibration.py`` build a device homography from 4 reference points
"""

from __future__ import annotations
