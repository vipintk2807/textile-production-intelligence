"""KPI engine tests. Synthetic test inputs; expected values hand-calculated."""

from decimal import Decimal

import pytest

from production.services import kpis
from production.services.kpis import ProductionFigure, ProductionTotals, Status

D = Decimal


def test_target_achievement_below_target():
    result = kpis.target_achievement(D("85"), D("100"))
    assert result.ok and result.value == D("85")


def test_target_achievement_equal_to_target_is_100():
    assert kpis.target_achievement(D("100"), D("100")).value == D("100")


def test_target_achievement_above_target():
    assert kpis.target_achievement(D("120"), D("100")).value == D("120")


def test_zero_actual_is_a_genuine_zero_percent():
    result = kpis.target_achievement(D("0"), D("100"))
    assert result.ok and result.value == D("0")


def test_zero_target_is_unavailable_not_division_error():
    result = kpis.target_achievement(D("10"), D("0"))
    assert result.status is Status.UNAVAILABLE and result.value is None
    assert "zero" in result.reason.lower()


def test_missing_target_is_unavailable():
    result = kpis.target_achievement(D("10"), None)
    assert not result.ok and "missing" in result.reason.lower()


def test_missing_actual_is_unavailable_not_zero():
    result = kpis.target_achievement(None, D("100"))
    assert not result.ok and result.value is None


def test_incompatible_units_are_unavailable():
    result = kpis.target_achievement(D("5"), D("10"), "kg", "m")
    assert not result.ok and "unit" in result.reason.lower()


def test_unknown_unit_is_unavailable_when_one_side_given():
    assert not kpis.target_achievement(D("5"), D("10"), "kg", None).ok


def test_same_units_are_compatible_case_insensitively():
    assert kpis.target_achievement(D("5"), D("10"), "kg", "KG").value == D("50")


def test_negative_quantity_is_invalid():
    assert not kpis.target_achievement(D("-1"), D("10")).ok
    assert not kpis.target_achievement(D("1"), D("-10")).ok


def test_non_numeric_input_is_invalid():
    assert not kpis.target_achievement("abc", D("10")).ok
    assert not kpis.target_achievement(D("NaN"), D("10")).ok


def test_achievement_is_not_rounded_internally():
    # 1/3 of 100 -> repeating decimal must stay unrounded in the result
    result = kpis.target_achievement(D("1"), D("3"))
    assert result.value != kpis.quantize_percent(result.value)
    assert kpis.quantize_percent(result.value) == D("33.33")


def test_percent_rounding_is_half_up():
    assert kpis.quantize_percent(D("12.345")) == D("12.35")
    assert kpis.quantize_percent(D("12.344")) == D("12.34")


def test_variance_negative_zero_and_positive():
    assert kpis.production_variance(D("85"), D("100")).value == D("-15")
    assert kpis.production_variance(D("100"), D("100")).value == D("0")
    assert kpis.production_variance(D("120"), D("100")).value == D("20")


def test_variance_is_available_for_zero_target():
    result = kpis.production_variance(D("10"), D("0"))
    assert result.ok and result.value == D("10")


def test_variance_unavailable_for_missing_or_incompatible():
    assert not kpis.production_variance(D("10"), None).ok
    assert not kpis.production_variance(D("10"), D("5"), "kg", "pcs").ok


def test_aggregate_uses_sums_not_average_of_percentages():
    # A: actual 10 / target 10 = 100%; B: actual 50 / target 90 = 55.55...%
    figures = [
        ProductionFigure(D("10"), D("10"), "kg"),
        ProductionFigure(D("50"), D("90"), "kg"),
    ]
    summary = kpis.summarize_figures(figures)["kg"]
    # 60 / 100 * 100 = 60 exactly; mean of 100% and 55.55% would be 77.78%
    assert summary.achievement.value == D("60")
    assert summary.variance.value == D("-40")


def test_aggregate_example_from_domain_rules():
    figures = [ProductionFigure(D("40"), D("50"), "kg"), ProductionFigure(D("45"), D("50"), "kg")]
    summary = kpis.summarize_figures(figures)["kg"]
    assert summary.totals.actual_total == D("85")
    assert summary.totals.target_total == D("100")
    assert summary.achievement.value == D("85")
    assert summary.variance.value == D("-15")


def test_mixed_units_are_separated_never_summed():
    figures = [
        ProductionFigure(D("40"), D("50"), "kg"),
        ProductionFigure(D("7"), D("10"), "pcs"),
    ]
    summaries = kpis.summarize_figures(figures)
    assert set(summaries) == {"kg", "pcs"}
    assert summaries["kg"].achievement.value == D("80")
    assert summaries["pcs"].achievement.value == D("70")


def test_records_without_target_do_not_inflate_achievement():
    figures = [
        ProductionFigure(D("40"), D("50"), "kg"),
        ProductionFigure(D("500"), None, "kg"),  # no target
    ]
    summary = kpis.summarize_figures(figures)["kg"]
    assert summary.totals.actual_total == D("540")  # all output still reported
    assert summary.achievement.value == D("80")  # 40/50 only
    assert summary.totals.records_without_target == 1
    assert any("no target" in note for note in summary.notes)


def test_all_records_without_target_makes_kpis_unavailable():
    summary = kpis.summarize_figures([ProductionFigure(D("5"), None, "kg")])["kg"]
    assert not summary.achievement.ok and not summary.variance.ok


def test_aggregate_with_zero_total_target_is_unavailable_but_variance_available():
    figures = [ProductionFigure(D("5"), D("0"), "kg"), ProductionFigure(D("3"), D("0"), "kg")]
    summary = kpis.summarize_figures(figures)["kg"]
    assert not summary.achievement.ok
    assert summary.variance.value == D("8")


def test_missing_actual_is_excluded_and_counted_not_zeroed():
    figures = [ProductionFigure(None, D("50"), "kg"), ProductionFigure(D("25"), D("50"), "kg")]
    summary = kpis.summarize_figures(figures)["kg"]
    assert summary.totals.records_missing_actual == 1
    assert summary.totals.actual_total == D("25")
    assert summary.achievement.value == D("50")


def test_evaluate_production_matches_figure_path():
    totals = ProductionTotals(
        unit="kg",
        records=2,
        actual_total=D("85"),
        records_with_target=2,
        target_total=D("100"),
        actual_with_target=D("85"),
    )
    summary = kpis.evaluate_production(totals)
    assert summary.achievement.value == D("85")
    assert summary.variance.value == D("-15")


def test_decimal_precision_is_exact():
    result = kpis.target_achievement(D("0.1") + D("0.2"), D("0.3"))
    assert result.value == D("100")


def test_remaining_no_completed_quantity():
    result = kpis.remaining_quantity(D("100"), "kg", [])
    assert result.result.value == D("100") and not result.over_produced


def test_remaining_partial_completion():
    result = kpis.remaining_quantity(D("100"), "kg", [("kg", D("30")), ("kg", D("20.5"))])
    assert result.result.value == D("49.5") and result.completed == D("50.5")


def test_remaining_exact_completion_is_zero_not_flagged():
    result = kpis.remaining_quantity(D("100"), "kg", [("kg", D("100"))])
    assert result.result.value == D("0") and not result.over_produced


def test_remaining_over_production_is_negative_and_flagged():
    result = kpis.remaining_quantity(D("100"), "kg", [("kg", D("130"))])
    assert result.result.value == D("-30")
    assert result.over_produced


def test_remaining_excludes_other_units_and_counts_them():
    outputs = [("kg", D("40")), ("m", D("999")), ("pcs", D("1"))]
    result = kpis.remaining_quantity(D("100"), "kg", outputs)
    assert result.result.value == D("60")
    assert result.excluded_other_unit_records == 2


def test_remaining_counts_records_of_pre_aggregated_entries():
    outputs = [("kg", D("40"), 3), ("m", D("999"), 4)]
    result = kpis.remaining_quantity(D("100"), "kg", outputs)
    assert result.result.value == D("60")
    assert result.excluded_other_unit_records == 4


def test_remaining_unavailable_for_invalid_order_quantity():
    assert not kpis.remaining_quantity(None, "kg", []).result.ok
    assert not kpis.remaining_quantity(D("0"), "kg", []).result.ok
    assert not kpis.remaining_quantity(D("10"), "", []).result.ok


def test_remaining_unavailable_for_invalid_output():
    assert not kpis.remaining_quantity(D("10"), "kg", [("kg", D("-1"))]).result.ok


@pytest.mark.parametrize(
    "actual,target,expected",
    [
        ("50", "100", "50"),
        ("100", "100", "100"),
        ("250", "100", "250"),
        ("0", "5", "0"),
    ],
)
def test_achievement_table(actual, target, expected):
    assert kpis.target_achievement(D(actual), D(target)).value == D(expected)
