"""Every threshold the progress and preprocessing logic depends on.

This is the **single definition site** for these numbers
(``GeoVision-Vault/02-Domain/Progress-Calculation.md`` §9). They appear in the
thesis, in the API, and in the model checkpoint metadata, and a number that
disagrees with itself across those three places is the kind of defect nobody
finds until an examiner asks why the figure says 0.6 and the code says 0.5.

.. important::
   The backend **cannot import this module.** Its base dependency group
   deliberately excludes ``geovision-ai`` so the API process never loads torch
   (ADR-011), and installing this package would drag torch in. So
   ``backend/app/domain/value_objects.py`` restates a few of these values, and
   ``scripts/check_constants_parity.py`` — run in CI — parses both files and
   fails the build if they ever disagree. See ADR-023.

   If you change a number here, change it there too. CI will tell you if you
   forget, which is the point.

No imports, by design: this module is read by an AST parser that must not have
to execute it.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "ADVANCE_CONFIRMATIONS",
    "ALGORITHM_VERSION",
    "ALPHA",
    "APPROVAL_WEIGHT_PCT",
    "BLUR_THRESHOLD",
    "DARKNESS_THRESHOLD",
    "MACHINE_CEILING_PCT",
    "MIN_CONFIDENCE",
    "OCCLUSION_MAX_RATIO",
    "REGRESS_CONFIRMATIONS",
]

# ---------------------------------------------------------------------------
# Scoring eligibility
# ---------------------------------------------------------------------------

#: A prediction below this confidence is stored and shown with a badge, but is
#: excluded from aggregation. Set at 0.60 rather than higher because a 10-class
#: ordinal problem with visually adjacent neighbours (Footings vs Foundation)
#: produces plenty of correct-but-hedged predictions, and discarding them all
#: would leave some windows with no data at all.
MIN_CONFIDENCE: Final = 0.60

# ---------------------------------------------------------------------------
# Temporal smoothing
# ---------------------------------------------------------------------------

#: EMA weight on the newest window. 0.30 gives roughly a 3-window memory: fast
#: enough that real progress appears within days, slow enough that one bad
#: weather day does not move the headline number.
ALPHA: Final = 0.30

#: Consecutive windows agreeing before the displayed stage may advance.
ADVANCE_CONFIRMATIONS: Final = 2

#: Consecutive windows required before allowing a *regression*. Higher than
#: ADVANCE_CONFIRMATIONS on purpose - going backwards is the claim that needs
#: more evidence, because it is usually occlusion or weather rather than
#: demolition.
REGRESS_CONFIRMATIONS: Final = 3

# ---------------------------------------------------------------------------
# The human-in-the-loop ceiling (ADR-007)
# ---------------------------------------------------------------------------

#: The machine can never report more than this. The last 20 % requires a named
#: person to inspect and sign off. This is a deliberate safety property, not a
#: limitation: no model should be the sole basis for declaring a building
#: finished.
MACHINE_CEILING_PCT: Final = 80.0

#: What that human approval is worth.
APPROVAL_WEIGHT_PCT: Final = 20.0

# ---------------------------------------------------------------------------
# Quality gate (ai/preprocessing/quality.py)
# ---------------------------------------------------------------------------

#: Variance of the Laplacian, below which an image is too blurry to classify.
#: Scale-dependent - it is measured on the decoded original, before any resize,
#: so that the same photograph always scores the same regardless of what the
#: pipeline does to it afterwards.
BLUR_THRESHOLD: Final = 60.0

#: Mean of the LAB L channel (0-255), below which the frame is too dark. Catches
#: the 18:00 capture that fired after sunset, and a camera whose IR-cut filter
#: stuck.
DARKNESS_THRESHOLD: Final = 25.0

#: Fraction of the reference façade ROI that may be covered by a near-field
#: blob - a parked truck, a tarpaulin, a worker standing in front of the lens -
#: before the frame is rejected.
OCCLUSION_MAX_RATIO: Final = 0.40

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

#: Stamped onto every snapshot. When the aggregation maths changes, this changes,
#: so a chart drawn from mixed versions is identifiable rather than merely wrong.
ALGORITHM_VERSION: Final = "progress-v1"
