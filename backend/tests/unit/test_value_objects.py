"""Tests for the domain value objects.

These are the cheapest tests in the project and guard the most reused
invariants: a malformed project code would poison every device name and image
filename derived from it, and a percentage/confidence mix-up would corrupt
every progress number in the system.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.value_objects import (
    Confidence,
    DomainValidationError,
    GeoPoint,
    ProgressPct,
    ProjectCode,
)

pytestmark = pytest.mark.unit


class TestProjectCode:
    """``NG_00`` — 2-5 uppercase letters, underscore, two digits."""

    @pytest.mark.parametrize("value", ["NG_00", "BM_01", "AYU_05", "JOLLI_99", "AB_00"])
    def test_valid_codes_are_accepted(self, value: str) -> None:
        assert ProjectCode(value).value == value

    @pytest.mark.parametrize(
        "value",
        [
            "ng_00",  # lowercase
            "NG_0",  # one digit
            "NG_000",  # three digits
            "N_00",  # one letter
            "TOOLONG_00",  # six letters
            "NG00",  # missing separator
            "NG-00",  # wrong separator
            "",
            "NG_0A",  # non-digit
            " NG_00",  # leading space
        ],
    )
    def test_invalid_codes_are_rejected(self, value: str) -> None:
        with pytest.raises(DomainValidationError):
            ProjectCode(value)

    def test_build_upper_cases_initials(self) -> None:
        """The form is free text, so lowercase input is normalised."""
        assert ProjectCode.build("ng", 0).value == "NG_00"

    def test_build_zero_pads_the_number(self) -> None:
        assert ProjectCode.build("BM", 1).value == "BM_01"

    @pytest.mark.parametrize(
        ("initials", "number"), [("N", 0), ("TOOLONG", 0), ("NG", 100), ("NG", -1)]
    )
    def test_build_rejects_out_of_range_parts(self, initials: str, number: int) -> None:
        with pytest.raises(DomainValidationError):
            ProjectCode.build(initials, number)

    def test_build_rejects_non_alpha_initials(self) -> None:
        with pytest.raises(DomainValidationError):
            ProjectCode.build("N1", 0)

    def test_parts_round_trip(self) -> None:
        code = ProjectCode("AYU_05")
        assert code.initials == "AYU"
        assert code.number == 5

    def test_suggest_alternatives_increments_the_number(self) -> None:
        """Drives the 409 response on the Create Project form."""
        assert ProjectCode("NG_00").suggest_alternatives(3) == ["NG_01", "NG_02", "NG_03"]

    def test_suggest_alternatives_near_the_ceiling(self) -> None:
        suggestions = ProjectCode("NG_98").suggest_alternatives(3)
        assert "NG_99" in suggestions
        assert all(len(s) <= 8 for s in suggestions)

    def test_is_hashable_and_ordered(self) -> None:
        """Needed for use in sets, dict keys, and sorted output."""
        codes = {ProjectCode("NG_01"), ProjectCode("NG_00"), ProjectCode("NG_00")}
        assert len(codes) == 2
        assert sorted(codes)[0] == ProjectCode("NG_00")

    def test_str_returns_the_bare_code(self) -> None:
        """So f-strings building filenames read naturally."""
        assert f"{ProjectCode('NG_00')}_20260813T070000Z_001.jpg" == (
            "NG_00_20260813T070000Z_001.jpg"
        )


class TestGeoPoint:
    """WGS-84 coordinates."""

    def test_valid_coordinate(self) -> None:
        point = GeoPoint(13.6218, 123.1948)
        assert point.latitude == pytest.approx(13.6218)

    @pytest.mark.parametrize(
        ("lat", "lon"), [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0)]
    )
    def test_out_of_range_is_rejected(self, lat: float, lon: float) -> None:
        with pytest.raises(DomainValidationError):
            GeoPoint(lat, lon)

    @pytest.mark.parametrize(("lat", "lon"), [(90.0, 180.0), (-90.0, -180.0), (0.0, 0.0)])
    def test_boundaries_are_accepted(self, lat: float, lon: float) -> None:
        assert GeoPoint(lat, lon) is not None

    def test_null_island_is_flagged(self) -> None:
        """(0, 0) is a GPS module without a fix, not a site in the Atlantic."""
        assert GeoPoint(0.0, 0.0).is_null_island is True
        assert GeoPoint(13.6218, 123.1948).is_null_island is False

    def test_maps_url_contains_six_decimals(self) -> None:
        url = GeoPoint(13.6218, 123.1948).to_maps_url()
        assert "13.621800,123.194800" in url
        assert url.startswith("https://")

    def test_osm_url_is_offered_as_an_alternative(self) -> None:
        assert "openstreetmap.org" in GeoPoint(13.6218, 123.1948).to_osm_url()


class TestProgressPct:
    """0-100, two decimal places, Decimal-backed."""

    def test_valid_percentage(self) -> None:
        assert ProgressPct(Decimal("63.50")).value == Decimal("63.50")

    def test_quantises_to_two_places(self) -> None:
        assert ProgressPct(Decimal("63.456")).value == Decimal("63.46")

    @pytest.mark.parametrize("value", ["-0.01", "100.01", "300"])
    def test_out_of_range_is_rejected(self, value: str) -> None:
        with pytest.raises(DomainValidationError):
            ProgressPct(Decimal(value))

    def test_float_is_rejected(self) -> None:
        """A float here would reintroduce the precision problem Decimal avoids."""
        with pytest.raises(DomainValidationError):
            ProgressPct(63.5)  # type: ignore[arg-type]

    def test_from_float_converts_via_str(self) -> None:
        """Decimal(str(0.1)) is exact; Decimal(0.1) is not."""
        assert ProgressPct.from_float(0.1).value == Decimal("0.10")

    def test_machine_ceiling_detection(self) -> None:
        """80 % is where the AI stops and a human must inspect (ADR-007)."""
        assert ProgressPct(Decimal("79.99")).is_at_machine_ceiling is False
        assert ProgressPct(Decimal("80.00")).is_at_machine_ceiling is True

    def test_completion_requires_one_hundred(self) -> None:
        assert ProgressPct(Decimal("80")).is_complete is False
        assert ProgressPct(Decimal("100")).is_complete is True

    def test_decimal_arithmetic_is_exact(self) -> None:
        """The reason this type exists rather than a float."""
        total = ProgressPct(Decimal("0.1")).value + ProgressPct(Decimal("0.2")).value
        assert total == Decimal("0.30")

    def test_ordering(self) -> None:
        assert ProgressPct(Decimal("20")) < ProgressPct(Decimal("40"))


class TestConfidence:
    """0-1, three decimal places — deliberately a different type to ProgressPct."""

    def test_valid_confidence(self) -> None:
        assert Confidence(Decimal("0.96")).value == Decimal("0.960")

    @pytest.mark.parametrize("value", ["-0.001", "1.001", "96"])
    def test_out_of_range_is_rejected(self, value: str) -> None:
        with pytest.raises(DomainValidationError):
            Confidence(Decimal(value))

    def test_eligibility_gate_at_0_60(self) -> None:
        """Below the gate a prediction is stored but excluded from aggregation."""
        assert Confidence(Decimal("0.599")).is_eligible is False
        assert Confidence(Decimal("0.600")).is_eligible is True
        assert Confidence(Decimal("0.96")).is_eligible is True

    def test_display_renders_as_a_percentage(self) -> None:
        assert str(Confidence(Decimal("0.96"))) == "96.0%"

    def test_is_not_interchangeable_with_progress(self) -> None:
        """A 0-1 value must never be mistaken for a 0-100 one.

        ``Confidence(0.96)`` and ``ProgressPct(96)`` describe different things;
        keeping them as separate types turns a mix-up into a type error rather
        than a silently wrong progress figure.
        """
        assert Confidence(Decimal("0.96")) != ProgressPct(Decimal("96"))
        with pytest.raises(DomainValidationError):
            Confidence(Decimal("96"))
