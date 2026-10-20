"""Synthetic demonstration-data loader tests."""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command

from production import selectors
from production.models import (
    DowntimeRecord,
    ProductionBatch,
    ProductionOrder,
    ProductionRecord,
    QualityRecord,
)
from production.selectors import ReportFilters

D = Decimal


def run(*args):
    out = StringIO()
    call_command("load_demo_data", *args, stdout=out)
    return out.getvalue()


def counts():
    return (
        ProductionOrder.objects.count(),
        ProductionBatch.objects.count(),
        ProductionRecord.objects.count(),
        DowntimeRecord.objects.count(),
        QualityRecord.objects.count(),
    )


def test_loader_creates_labelled_synthetic_records(db):
    output = run()
    assert "SYNTHETIC" in output
    assert ProductionOrder.objects.count() == 3
    for order in ProductionOrder.objects.all():
        assert order.order_code.startswith("SYN-")
        assert "Synthetic" in order.notes
    for record in ProductionRecord.objects.all():
        assert "Synthetic" in record.notes


def test_loader_is_idempotent(db):
    run()
    first = counts()
    output = run()
    assert counts() == first
    assert "Skipped" in output


def test_loader_does_not_touch_existing_orders(db, kg):
    ProductionOrder.objects.create(
        order_code="SYN-ORD-001", product_reference="mine", order_quantity=D("5"), unit=kg)
    run()
    assert ProductionOrder.objects.get(order_code="SYN-ORD-001").product_reference == "mine"
    assert ProductionRecord.objects.filter(order__order_code="SYN-ORD-001").count() == 0


def test_demo_data_produces_the_documented_kpis(db):
    run()
    report = selectors.build_report(ReportFilters())
    rows = {(r.order_code, r.batch_code, r.unit): r for r in report.rows}
    assert rows[("SYN-ORD-001", "SYN-BAT-001", "kg")].production.achievement.value == D("85")
    assert rows[("SYN-ORD-002", "SYN-BAT-003", "pcs")].production.achievement.value == D("85")
    assert rows[("SYN-ORD-001", None, "kg")].production.achievement.ok is False  # zero target
    order3 = ProductionOrder.objects.get(order_code="SYN-ORD-003")
    info = selectors.remaining_for_orders([order3])[order3.pk]
    assert info.result.value == D("-30") and info.over_produced


def test_demo_downtime_includes_cross_midnight_and_overlap(db):
    run()
    durations = sorted(e.duration_minutes for e in DowntimeRecord.objects.all())
    assert D("45") in durations
    downtime = selectors.build_report(ReportFilters()).downtime
    assert downtime.overlap_pairs == 1
    assert downtime.unique_minutes < downtime.sum_minutes


def test_remove_without_confirmation_deletes_nothing(db):
    run()
    before = counts()
    output = run("--remove")
    assert "Re-run with --yes" in output
    assert counts() == before


def test_remove_with_confirmation_only_removes_synthetic(db, kg):
    run()
    ProductionOrder.objects.create(
        order_code="REAL-1", product_reference="real", order_quantity=D("5"), unit=kg)
    run("--remove", "--yes")
    assert list(ProductionOrder.objects.values_list("order_code", flat=True)) == ["REAL-1"]
    assert ProductionRecord.objects.count() == 0
