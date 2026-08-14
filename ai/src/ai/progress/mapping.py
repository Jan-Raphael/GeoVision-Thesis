"""The construction-stage vocabulary: fine classes, macro stages, nominal %.

Loaded once from ``ai/configs/classes.yaml``, which is the canonical definition
(``GeoVision-Vault/02-Domain/Construction-Stages.md``). Nothing here is
hard-coded — a percentage typed into a second file is a percentage that will
eventually disagree with the first.

The index order is **frozen**. It is the output order of the trained checkpoint,
so reordering silently relabels every prediction already stored: the database
keeps ``fine_class_index``, not the name. :func:`load_reference` verifies the
order on load rather than trusting it.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "CLASSES_CONFIG_PATH",
    "FineClass",
    "MacroStage",
    "StageReference",
    "class_names",
    "load_reference",
    "reference_for",
    "reference_for_name",
]

CLASSES_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "classes.yaml"


class MacroStage(StrEnum):
    """The five bars the dashboard shows.

    Mirrors ``backend/app/domain/enums.py``. The two cannot import each other
    (ADR-011/ADR-023), so the values are kept identical by hand and the string
    values are what actually crosses the boundary — a mismatch would surface
    immediately as an unknown enum value on insert, not silently.
    """

    FOUNDATION = "foundation"
    FRAMING = "framing"
    ROOFING = "roofing"
    FINISHING = "finishing"
    APPROVAL = "approval"


class FineClass(StrEnum):
    """The ten classes the CNN predicts, by token.

    Tokens rather than names because they are what appears in dataset filenames
    (``GV_[PROJECT]_[STAGE]_[NUM].jpg``) and in the confusion matrix axis labels,
    where "FTG" fits and "Footings" does not.
    """

    CLR = "CLR"
    EXC = "EXC"
    FTG = "FTG"
    FDN = "FDN"
    COL = "COL"
    SLB = "SLB"
    WAL = "WAL"
    ROF = "ROF"
    FIN = "FIN"
    CMP = "CMP"


@dataclass(frozen=True, slots=True)
class StageReference:
    """Everything known about one fine class."""

    index: int
    name: str
    token: FineClass
    macro_stage: MacroStage
    nominal_progress_pct: float
    stage_floor_pct: float
    stage_ceiling_pct: float

    @property
    def is_terminal(self) -> bool:
        """Whether this class means "looks finished to the machine".

        Reaching it triggers the human inspection flow rather than 100 %
        (ADR-007).
        """
        return self.macro_stage is MacroStage.APPROVAL


@lru_cache(maxsize=4)
def load_reference(path: str | None = None) -> tuple[StageReference, ...]:
    """Load the class table, indexed by ``class_index``.

    Args:
        path: Override for the config file. Defaults to the packaged
            ``classes.yaml``.

    Returns:
        References in frozen index order, so ``result[i].index == i``.

    Raises:
        ValueError: If the file is malformed, or the indices are not a complete
            gapless sequence from zero. That check is not pedantry: the
            classifier outputs a bare integer, and a gap would make some outputs
            unmappable while others silently shifted meaning.
    """
    config_path = Path(path) if path else CLASSES_CONFIG_PATH
    document = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    if not isinstance(document, dict) or "classes" not in document:
        msg = f"{config_path} must be a mapping containing 'classes'"
        raise ValueError(msg)

    bands = _stage_bands(document, config_path)
    entries = sorted(document["classes"], key=lambda item: item["index"])

    references: list[StageReference] = []
    for position, entry in enumerate(entries):
        if entry["index"] != position:
            msg = (
                f"{config_path}: class indices must run 0..N with no gaps; "
                f"found {entry['index']} at position {position}. The index is "
                f"the checkpoint's output order - a gap silently relabels history."
            )
            raise ValueError(msg)

        stage = MacroStage(entry["macro_stage"])
        floor, ceiling = bands[stage]
        references.append(
            StageReference(
                index=entry["index"],
                name=entry["name"],
                token=FineClass(entry["token"]),
                macro_stage=stage,
                nominal_progress_pct=float(entry["nominal_progress_pct"]),
                stage_floor_pct=floor,
                stage_ceiling_pct=ceiling,
            )
        )

    _verify_monotonic(references, config_path)
    return tuple(references)


def reference_for(class_index: int, *, path: str | None = None) -> StageReference:
    """Look up a class by the index the model emitted.

    Raises:
        KeyError: If the index is outside the frozen list. A model whose head
            emits an index this table does not know is a model trained against a
            different vocabulary, and guessing would corrupt the progress
            history.
    """
    references = load_reference(path)
    if not 0 <= class_index < len(references):
        msg = (
            f"class index {class_index} is outside the frozen 0..{len(references) - 1} "
            f"range - the checkpoint does not match classes.yaml"
        )
        raise KeyError(msg)
    return references[class_index]


def reference_for_name(name_or_token: str, *, path: str | None = None) -> StageReference:
    """Look up a class by its name or token, case-insensitively.

    Raises:
        KeyError: If nothing matches.
    """
    needle = name_or_token.strip().casefold()
    for reference in load_reference(path):
        if needle in {reference.name.casefold(), reference.token.value.casefold()}:
            return reference
    msg = f"no construction stage named {name_or_token!r}"
    raise KeyError(msg)


def class_names(*, path: str | None = None) -> tuple[str, ...]:
    """Class names in frozen index order, for the model head and `/model/status`."""
    return tuple(reference.name for reference in load_reference(path))


def _stage_bands(
    document: dict[str, Any], config_path: Path
) -> dict[MacroStage, tuple[float, float]]:
    """Extract each macro stage's progress band."""
    bands: dict[MacroStage, tuple[float, float]] = {}
    for entry in document.get("macro_stages", []):
        stage = MacroStage(entry["name"])
        bands[stage] = (float(entry["floor_pct"]), float(entry["ceiling_pct"]))

    missing = set(MacroStage) - set(bands)
    if missing:
        names = ", ".join(sorted(stage.value for stage in missing))
        msg = f"{config_path}: missing macro_stages: {names}"
        raise ValueError(msg)
    return bands


def _verify_monotonic(references: list[StageReference], config_path: Path) -> None:
    """Check the nominal percentages never decrease as the index rises.

    The classes describe a monotone construction sequence, and the whole
    ordinal treatment downstream — the ratchet, the mean-absolute-ordinal-error
    metric, the stage-advance guard — assumes it. A table where Slab scored
    lower than Columns would make the ratchet fight the data forever, and the
    symptom would be a progress number that mysteriously refuses to move.

    Raises:
        ValueError: If the sequence decreases anywhere.
    """
    for previous, current in itertools.pairwise(references):
        if current.nominal_progress_pct < previous.nominal_progress_pct:
            msg = (
                f"{config_path}: nominal_progress_pct must not decrease with class "
                f"index ({previous.token}={previous.nominal_progress_pct} then "
                f"{current.token}={current.nominal_progress_pct}); the classes are "
                f"an ordered construction sequence"
            )
            raise ValueError(msg)
