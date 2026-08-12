"""Value objects — small immutable types that validate themselves.

The point of these is that **an invalid instance cannot exist**. A
:class:`ProjectCode` is always well-formed; a :class:`ProgressPct` is always in
range. Validation happens once, at construction, instead of being re-checked
(and occasionally forgotten) at every call site.

They are pure Python: no ORM, no framework, no I/O. That is what lets the
permission rules and the progress algorithm be tested without a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Self

__all__ = ["Confidence", "GeoPoint", "ProgressPct", "ProjectCode"]

#: ``NG_00`` — 2-5 uppercase letters, underscore, exactly two digits.
PROJECT_CODE_PATTERN: Final = re.compile(r"^[A-Z]{2,5}_[0-9]{2}$")

#: Bounds for the owner-supplied halves of a project code.
MIN_INITIALS_LEN: Final = 2
MAX_INITIALS_LEN: Final = 5
MIN_PROJECT_NUMBER: Final = 0
MAX_PROJECT_NUMBER: Final = 99


class DomainValidationError(ValueError):
    """A value object was constructed with an invalid value.

    Deliberately a :class:`ValueError` subclass so it behaves naturally in
    Pydantic validators and in plain Python, without the domain layer importing
    a web framework.
    """


@dataclass(frozen=True, slots=True, order=True)
class ProjectCode:
    """A globally unique project identifier such as ``NG_00``.

    The code is **immutable after project creation**: it is embedded in device
    names (``ESP_NG_00_FD``) and in every captured image filename
    (``NG_00_20260813T070000Z_001.jpg``), so changing it would orphan history.

    See ``GeoVision-Vault/01-Architecture/Naming-Conventions.md``.
    """

    value: str

    def __post_init__(self) -> None:
        """Validate the code's shape."""
        if not isinstance(self.value, str):
            msg = f"project code must be a string, got {type(self.value).__name__}"
            raise DomainValidationError(msg)
        if not PROJECT_CODE_PATTERN.match(self.value):
            msg = (
                f"invalid project code {self.value!r}: expected 2-5 uppercase "
                "letters, an underscore, then two digits (e.g. 'NG_00')"
            )
            raise DomainValidationError(msg)

    @classmethod
    def build(cls, initials: str, number: int) -> Self:
        """Construct from the two fields on the Create Project form.

        Args:
            initials: 2-5 letters; lowercase input is upper-cased for
                convenience, since the form is free text.
            number: Project counter, 0-99, zero-padded to two digits.

        Returns:
            The assembled project code.

        Raises:
            DomainValidationError: If either part is out of range.
        """
        cleaned = initials.strip().upper()
        if not (MIN_INITIALS_LEN <= len(cleaned) <= MAX_INITIALS_LEN):
            msg = (
                f"initials must be {MIN_INITIALS_LEN}-{MAX_INITIALS_LEN} letters, got {initials!r}"
            )
            raise DomainValidationError(msg)
        if not cleaned.isalpha() or not cleaned.isascii():
            msg = f"initials must be ASCII letters only, got {initials!r}"
            raise DomainValidationError(msg)
        if not MIN_PROJECT_NUMBER <= number <= MAX_PROJECT_NUMBER:
            msg = f"project number must be {MIN_PROJECT_NUMBER}-{MAX_PROJECT_NUMBER}, got {number}"
            raise DomainValidationError(msg)
        return cls(f"{cleaned}_{number:02d}")

    @property
    def initials(self) -> str:
        """The letter prefix, e.g. ``NG``."""
        return self.value.split("_")[0]

    @property
    def number(self) -> int:
        """The numeric suffix as an int, e.g. ``0``."""
        return int(self.value.split("_")[1])

    def suggest_alternatives(self, count: int = 3) -> list[str]:
        """Suggest unused-looking codes when this one is taken.

        Returns purely syntactic candidates — the caller checks availability
        against the database. Used by the 409 response on the Create Project
        form (see ``API-Contract.md``).

        Args:
            count: How many suggestions to return.

        Returns:
            Candidate codes, nearest variations first.
        """
        suggestions: list[str] = []
        number = self.number
        while len(suggestions) < count and number < MAX_PROJECT_NUMBER:
            number += 1
            suggestions.append(f"{self.initials}_{number:02d}")
        # If the numeric space is exhausted, vary the initials instead.
        if len(suggestions) < count and len(self.initials) < MAX_INITIALS_LEN:
            suggestions.append(f"{self.initials}V_{self.number:02d}")
        return suggestions[:count]

    def __str__(self) -> str:
        """Return the raw code, so f-strings and paths read naturally."""
        return self.value


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """A WGS-84 coordinate captured alongside an image or pinned to a project.

    Stored at six decimal places (~0.11 m at the equator), which is far finer
    than consumer GPS accuracy and matches the ``numeric(9,6)`` columns in
    ``Domain-Model.md``.
    """

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        """Validate that the coordinate is on Earth."""
        if not -90.0 <= self.latitude <= 90.0:
            msg = f"latitude must be between -90 and 90, got {self.latitude}"
            raise DomainValidationError(msg)
        if not -180.0 <= self.longitude <= 180.0:
            msg = f"longitude must be between -180 and 180, got {self.longitude}"
            raise DomainValidationError(msg)

    @property
    def is_null_island(self) -> bool:
        """Whether this is exactly (0, 0).

        Almost always a GPS module reporting before it has a fix, rather than a
        genuine site in the Gulf of Guinea. Callers should treat it as missing.
        """
        return self.latitude == 0.0 and self.longitude == 0.0

    def to_maps_url(self) -> str:
        """Google Maps link for the public "open in maps" button."""
        return (
            "https://www.google.com/maps/search/?api=1&"
            f"query={self.latitude:.6f},{self.longitude:.6f}"
        )

    def to_osm_url(self) -> str:
        """OpenStreetMap link, offered as a non-proprietary alternative."""
        return (
            f"https://www.openstreetmap.org/?mlat={self.latitude:.6f}"
            f"&mlon={self.longitude:.6f}#map=18/{self.latitude:.6f}/{self.longitude:.6f}"
        )

    def __str__(self) -> str:
        """Return ``lat, lon`` at six decimal places."""
        return f"{self.latitude:.6f}, {self.longitude:.6f}"


@dataclass(frozen=True, slots=True, order=True)
class ProgressPct:
    """A construction progress percentage in ``[0, 100]``.

    Held as :class:`~decimal.Decimal` quantised to two places, matching the
    ``numeric(5,2)`` columns. Binary floats are avoided deliberately: progress
    values are summed, averaged, and compared against thresholds, and ``0.1 +
    0.2 != 0.3`` is not a property you want in a number a user reads as
    authoritative.

    Naming rule from ``Naming-Conventions.md``: percentages are 0-100 and their
    field names end ``_pct``; confidences are 0-1 and end ``_confidence``.
    """

    value: Decimal

    #: The AI can never exceed this; the last 20 % needs human sign-off (ADR-007).
    MACHINE_CEILING: Final[Decimal] = Decimal("80.00")

    def __post_init__(self) -> None:
        """Validate and quantise to two decimal places."""
        if not isinstance(self.value, Decimal):
            msg = f"ProgressPct requires a Decimal, got {type(self.value).__name__}"
            raise DomainValidationError(msg)
        if not Decimal("0") <= self.value <= Decimal("100"):
            msg = f"progress must be between 0 and 100, got {self.value}"
            raise DomainValidationError(msg)
        object.__setattr__(
            self, "value", self.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )

    @classmethod
    def from_float(cls, value: float) -> Self:
        """Build from a float, e.g. the output of the progress aggregator."""
        return cls(Decimal(str(value)))

    @classmethod
    def zero(cls) -> Self:
        """A project that has not started."""
        return cls(Decimal("0.00"))

    @property
    def is_at_machine_ceiling(self) -> bool:
        """Whether the AI has taken this project as far as it may.

        When true, the project moves to ``AWAITING_INSPECTION`` and the owner is
        notified.
        """
        return self.value >= self.MACHINE_CEILING

    @property
    def is_complete(self) -> bool:
        """Whether the project is fully complete (human-approved)."""
        return self.value >= Decimal("100")

    def as_float(self) -> float:
        """Lossy float view, for charts and JSON."""
        return float(self.value)

    def __str__(self) -> str:
        """Render as a percentage, e.g. ``63.50%``."""
        return f"{self.value}%"


@dataclass(frozen=True, slots=True, order=True)
class Confidence:
    """A model's softmax confidence in ``[0, 1]``.

    Deliberately a distinct type from :class:`ProgressPct`. The two are easy to
    mix up (0-1 versus 0-100), and doing so silently would corrupt every
    progress number in the system; separate types make the mistake a
    ``TypeError`` instead.
    """

    value: Decimal

    #: Predictions below this are stored but excluded from aggregation
    #: (``Progress-Calculation.md`` §1).
    MIN_ELIGIBLE: Final[Decimal] = Decimal("0.600")

    def __post_init__(self) -> None:
        """Validate and quantise to three decimal places."""
        if not isinstance(self.value, Decimal):
            msg = f"Confidence requires a Decimal, got {type(self.value).__name__}"
            raise DomainValidationError(msg)
        if not Decimal("0") <= self.value <= Decimal("1"):
            msg = f"confidence must be between 0 and 1, got {self.value}"
            raise DomainValidationError(msg)
        object.__setattr__(
            self, "value", self.value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        )

    @classmethod
    def from_float(cls, value: float) -> Self:
        """Build from a model output float."""
        return cls(Decimal(str(value)))

    @property
    def is_eligible(self) -> bool:
        """Whether this prediction may influence the project's progress."""
        return self.value >= self.MIN_ELIGIBLE

    def as_float(self) -> float:
        """Lossy float view, for JSON."""
        return float(self.value)

    def __str__(self) -> str:
        """Render as a percentage for display, e.g. ``96.0%``."""
        return f"{self.value * 100:.1f}%"
