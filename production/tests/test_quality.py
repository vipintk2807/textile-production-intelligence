"""Quality service tests."""

from decimal import Decimal

import pytest

from production.services import quality

D = Decimal


def test_rate_with_valid_denominator():
    assert quality.quality_rate(D("5"), D("100")).value == D("5")


def test_rate_zero_numerator_is_a_genuine_zero():
    result = quality.quality_rate(D("0"), D("100"))
    assert result.ok and result.value == D("0")


def test_rate_without_denominator_is_unavailable_never_zero():
    result = quality.quality_rate(D("5"), None)
    assert not result.ok and result.value is None
    assert "denominator" in result.reason.lower()


def test_rate_zero_denominator_is_undefined():
    result = quality.quality_rate(D("5"), D("0"))
    assert not result.ok and "zero" in result.reason.lower()


def test_rate_missing_numerator_is_unavailable():
    assert not quality.quality_rate(None, D("100")).ok


def test_rate_incompatible_units_unavailable():
    assert not quality.quality_rate(D("1"), D("10"), "kg", "pcs").ok


def test_rate_negative_values_invalid():
    assert not quality.quality_rate(D("-1"), D("10")).ok
    assert not quality.quality_rate(D("1"), D("-10")).ok


def test_rate_may_exceed_100_because_no_exclusivity_rule_is_assumed():
    assert quality.quality_rate(D("150"), D("100")).value == D("150")


def test_total_by_type_keeps_units_and_types_apart():
    rows = [
        ("REWORK", "kg", D("5")),
        ("REWORK", "kg", D("2.5")),
        ("REJECTION", "kg", D("3")),
        ("REWORK", "pcs", D("10")),
    ]
    totals = quality.total_by_type(rows)
    assert totals[("REWORK", "kg")] == D("7.5")
    assert totals[("REJECTION", "kg")] == D("3")
    assert totals[("REWORK", "pcs")] == D("10")
    assert len(totals) == 3


def test_total_by_type_rejects_invalid_quantity():
    with pytest.raises(ValueError):
        quality.total_by_type([("REWORK", "kg", D("-1"))])


def test_total_by_type_empty():
    assert quality.total_by_type([]) == {}
