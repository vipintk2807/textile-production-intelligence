"""Report/selector tests with small deterministic datasets.

Expected values below were calculated by hand, independently of the code.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from production import selectors
from production.models import DowntimeRecord, ProductionRecord, QualityRecord
from production.selectors import ReportFilters

D = Decimal


def aware(day, hour, minute=0):
    return timezone.make_aware(datetime(2026, 1, day, hour, minute))


def add_production(order, unit, day, target, actual, batch=None):
    return ProductionRecord.objects.create(
        production_date=date(2026, 1, day), order=order, batch=batch, unit=unit,
        target_quantity=None if target is None else D(target), actual_quantity=D(actual),
    )


def row_for(report, batch_code, unit="kg"):
    for row in report.rows:
        if row.batch_code == batch_code and row.unit == unit:
            return row
    raise AssertionError(f"no row for {batch_code}/{unit}")


@pytest.fixture
def dataset(order, batch, batch2, kg):
    # B1: (50,40) + (50,45) -> target 100, actual 85
    add_production(order, kg, 5, "50", "40", batch)
    add_production(order, kg, 5, "50", "45", batch)
    # B2: no target, actual 30
    add_production(order, kg, 6, None, "30", batch2)
    # order-level: zero target, actual 10
    add_production(order, kg, 7, "0", "10")
    return order


def test_empty_database_report_has_no_data(db):
    report = selectors.build_report(ReportFilters())
    assert not report.has_data and report.rows == [] and report.unit_totals == []


def test_batch_row_matches_hand_calculation(dataset):
    report = selectors.build_report(ReportFilters())
    b1 = row_for(report, "T-BAT-1").production
    assert b1.totals.target_total == D("100")
    assert b1.totals.actual_total == D("85")
    assert b1.achievement.value == D("85")
    assert b1.variance.value == D("-15")


def test_batch_without_target_is_unavailable_but_output_shown(dataset):
    b2 = row_for(selectors.build_report(ReportFilters()), "T-BAT-2").production
    assert b2.totals.actual_total == D("30")
    assert b2.totals.target_total is None
    assert not b2.achievement.ok and not b2.variance.ok


def test_zero_target_row_has_unavailable_achievement_but_variance(dataset):
    row = row_for(selectors.build_report(ReportFilters()), None).production
    assert not row.achievement.ok
    assert row.variance.value == D("10")


def test_unit_total_is_weighted_not_averaged(dataset):
    totals = selectors.build_report(ReportFilters()).unit_totals
    assert len(totals) == 1
    summary = totals[0].summary
    # records with a target: (50,40) (50,45) (0,10) -> target 100, actual 95
    assert summary.totals.actual_total == D("125")
    assert summary.totals.target_total == D("100")
    assert summary.achievement.value == D("95")
    assert summary.variance.value == D("-5")


def test_date_filter_is_inclusive_on_both_ends(dataset):
    day5 = selectors.build_report(
        ReportFilters(start_date=date(2026, 1, 5), end_date=date(2026, 1, 5)))
    assert day5.unit_totals[0].summary.totals.actual_total == D("85")
    days_5_to_6 = selectors.build_report(
        ReportFilters(start_date=date(2026, 1, 5), end_date=date(2026, 1, 6)))
    assert days_5_to_6.unit_totals[0].summary.totals.actual_total == D("115")


def test_records_outside_period_do_not_contribute(dataset):
    report = selectors.build_report(
        ReportFilters(start_date=date(2026, 2, 1), end_date=date(2026, 2, 28)))
    assert not report.has_data


def test_order_and_batch_filters(dataset, batch):
    only_b1 = selectors.build_report(ReportFilters(batch_id=batch.pk))
    assert len(only_b1.rows) == 1
    assert only_b1.unit_totals[0].summary.achievement.value == D("85")


def test_order_status_filter(dataset):
    assert selectors.build_report(ReportFilters(order_status="PLANNED")).has_data
    assert not selectors.build_report(ReportFilters(order_status="COMPLETED")).has_data


def test_different_units_are_never_summed(dataset, pcs):
    add_production(dataset, pcs, 5, "10", "7")
    totals = {t.unit: t for t in selectors.build_report(ReportFilters()).unit_totals}
    assert set(totals) == {"kg", "pcs"}
    assert totals["pcs"].summary.achievement.value == D("70")
    assert totals["kg"].summary.totals.actual_total == D("125")


def test_quality_does_not_multiply_production_totals(dataset, batch, kg):
    for qty in ("1", "2", "3"):
        QualityRecord.objects.create(
            record_date=date(2026, 1, 5), order=dataset, batch=batch,
            record_type="REWORK", quantity=D(qty), unit=kg)
    QualityRecord.objects.create(
        record_date=date(2026, 1, 5), order=dataset, batch=batch,
        record_type="REJECTION", quantity=D("4"), unit=kg)
    report = selectors.build_report(ReportFilters())
    b1 = row_for(report, "T-BAT-1")
    assert b1.production.totals.actual_total == D("85")  # unchanged by joins
    assert b1.rework == D("6") and b1.rejection == D("4")
    assert row_for(report, "T-BAT-2").rework is None  # no records, not zero


def test_quality_only_scope_still_appears(order, kg):
    QualityRecord.objects.create(
        record_date=date(2026, 1, 5), order=order, record_type="REJECTION",
        quantity=D("2"), unit=kg)
    report = selectors.build_report(ReportFilters())
    assert report.rows[0].production is None
    assert report.unit_totals[0].summary is None
    assert report.unit_totals[0].rejection == D("2")


def test_quality_type_filter(order, kg):
    for kind, qty in (("REWORK", "1"), ("REJECTION", "2")):
        QualityRecord.objects.create(
            record_date=date(2026, 1, 5), order=order, record_type=kind,
            quantity=D(qty), unit=kg)
    report = selectors.build_report(ReportFilters(quality_type="REWORK"))
    assert report.show_rework and not report.show_rejection
    assert report.rows[0].rework == D("1") and report.rows[0].rejection is None


def test_quality_rates_are_unavailable_without_a_denominator(order, kg):
    QualityRecord.objects.create(
        record_date=date(2026, 1, 5), order=order, record_type="REJECTION",
        quantity=D("2"), unit=kg)
    totals = selectors.build_report(ReportFilters()).unit_totals[0]
    assert not totals.rejection_rate.ok and totals.rejection_rate.value is None


def test_downtime_cross_midnight_is_split_between_reports(order):
    DowntimeRecord.objects.create(
        order=order, category="MECHANICAL", start_at=aware(5, 23, 30), end_at=aware(6, 0, 15))
    whole = selectors.build_report(ReportFilters())
    day5 = selectors.build_report(
        ReportFilters(start_date=date(2026, 1, 5), end_date=date(2026, 1, 5)))
    day6 = selectors.build_report(
        ReportFilters(start_date=date(2026, 1, 6), end_date=date(2026, 1, 6)))
    assert whole.downtime.sum_minutes == D("45")
    assert day5.downtime.sum_minutes == D("30")
    assert day6.downtime.sum_minutes == D("15")
    assert day5.downtime.event_count == day6.downtime.event_count == 1


def test_downtime_outside_period_excluded(order):
    DowntimeRecord.objects.create(
        order=order, category="OTHER", start_at=aware(5, 8), end_at=aware(5, 9))
    report = selectors.build_report(
        ReportFilters(start_date=date(2026, 1, 6), end_date=date(2026, 1, 6)))
    assert report.downtime.event_count == 0


def test_overlapping_downtime_sum_versus_unique(order):
    DowntimeRecord.objects.create(
        order=order, category="OTHER", start_at=aware(6, 10), end_at=aware(6, 11))
    DowntimeRecord.objects.create(
        order=order, category="SETUP", start_at=aware(6, 10, 30), end_at=aware(6, 11, 30))
    downtime = selectors.build_report(ReportFilters()).downtime
    assert downtime.sum_minutes == D("120")
    assert downtime.unique_minutes == D("90")
    assert downtime.overlap_pairs == 1
    assert {g.label for g in downtime.by_category} == {"Other", "Setup / changeover"}


def test_downtime_category_filter(order):
    DowntimeRecord.objects.create(
        order=order, category="OTHER", start_at=aware(6, 10), end_at=aware(6, 11))
    DowntimeRecord.objects.create(
        order=order, category="SETUP", start_at=aware(6, 12), end_at=aware(6, 13))
    report = selectors.build_report(ReportFilters(downtime_category="SETUP"))
    assert report.downtime.event_count == 1


def test_remaining_quantity_partial_and_over_production(order, kg, metre):
    add_production(order, kg, 5, "50", "30")
    add_production(order, kg, 6, "50", "20.5")
    add_production(order, metre, 6, "5", "999")  # other unit: excluded
    info = selectors.remaining_for_orders([order])[order.pk]
    assert info.result.value == D("49.5")
    assert info.excluded_other_unit_records == 1
    add_production(order, kg, 7, "0", "100")
    info = selectors.remaining_for_orders([order])[order.pk]
    assert info.result.value == D("-50.5")
    assert info.over_produced


def test_attention_orders_flags_completed_with_remaining(order, kg):
    order.status = "IN_PROGRESS"
    order.save()
    order.status = "COMPLETED"
    order.save()
    add_production(order, kg, 5, "10", "10")
    flagged = selectors.attention_orders()
    assert [o.order_code for o, _info, _why in flagged] == ["T-ORD-1"]


def test_status_counts_cover_every_status(order, other_order):
    counts = dict(selectors.status_counts())
    assert counts["Planned"] == 2
    assert counts["Completed"] == 0


def test_decimal_sums_stay_exact(order, kg):
    add_production(order, kg, 5, "0.1", "0.1")
    add_production(order, kg, 5, "0.2", "0.2")
    summary = selectors.build_report(ReportFilters()).unit_totals[0].summary
    assert summary.totals.target_total == D("0.3")
    assert summary.achievement.value == D("100")
