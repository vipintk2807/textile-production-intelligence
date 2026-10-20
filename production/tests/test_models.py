"""Model, constraint, relationship and deletion-protection tests."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from production.models import (
    DowntimeRecord,
    ProductionBatch,
    ProductionOrder,
    ProductionRecord,
    QualityRecord,
    UnitOfMeasure,
)

D = Decimal


def aware(day, hour, minute=0):
    return timezone.make_aware(datetime(2026, 1, day, hour, minute))


def test_initial_units_are_seeded_by_migration(db):
    codes = set(UnitOfMeasure.objects.values_list("code", flat=True))
    assert {"kg", "m", "pcs"} <= codes


def test_duplicate_order_code_is_rejected(order, kg):
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductionOrder.objects.create(
            order_code="T-ORD-1", product_reference="x", order_quantity=D("1"), unit=kg
        )


def test_duplicate_batch_code_is_rejected(batch, order):
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductionBatch.objects.create(batch_code="T-BAT-1", order=order)


def test_zero_order_quantity_rejected_by_database(kg):
    bad = ProductionOrder(order_code="Z", product_reference="x", order_quantity=D("0"), unit=kg)
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductionOrder.objects.bulk_create([bad])


def test_zero_order_quantity_rejected_by_full_clean(kg):
    bad = ProductionOrder(order_code="Z", product_reference="x", order_quantity=D("0"), unit=kg)
    with pytest.raises(ValidationError) as caught:
        bad.full_clean()
    assert "order_quantity" in caught.value.message_dict


def test_planned_end_before_start_rejected(kg):
    bad = ProductionOrder(
        order_code="D", product_reference="x", order_quantity=D("1"), unit=kg,
        planned_start_date=date(2026, 2, 2), planned_end_date=date(2026, 2, 1),
    )
    with pytest.raises(ValidationError) as caught:
        bad.full_clean()
    assert "planned_end_date" in caught.value.message_dict


def test_decimal_values_keep_precision(order, kg):
    record = ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=order, unit=kg,
        actual_quantity=D("1234.567"), target_quantity=D("0.001"),
    )
    record.refresh_from_db()
    assert record.actual_quantity == D("1234.567")
    assert record.target_quantity == D("0.001")


def test_too_many_decimal_places_rejected_by_full_clean(order, kg):
    record = ProductionRecord(
        production_date=date(2026, 1, 5), order=order, unit=kg, actual_quantity=D("1.2345")
    )
    with pytest.raises(ValidationError) as caught:
        record.full_clean()
    assert "actual_quantity" in caught.value.message_dict


def test_maximum_quantity_boundary(order, kg):
    ok = ProductionRecord(
        production_date=date(2026, 1, 5), order=order, unit=kg,
        actual_quantity=D("99999999999.999"),
    )
    ok.full_clean()
    too_big = ProductionRecord(
        production_date=date(2026, 1, 5), order=order, unit=kg,
        actual_quantity=D("100000000000.000"),
    )
    with pytest.raises(ValidationError):
        too_big.full_clean()


def test_negative_actual_rejected_by_database(order, kg):
    bad = ProductionRecord(
        production_date=date(2026, 1, 5), order=order, unit=kg, actual_quantity=D("-1")
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductionRecord.objects.bulk_create([bad])


def test_missing_target_is_stored_as_null_not_zero(order, kg):
    record = ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=order, unit=kg, actual_quantity=D("5")
    )
    record.refresh_from_db()
    assert record.target_quantity is None


def test_zero_target_is_stored_as_zero(order, kg):
    record = ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=order, unit=kg,
        actual_quantity=D("5"), target_quantity=D("0"),
    )
    record.refresh_from_db()
    assert record.target_quantity == D("0")


def test_production_record_rejects_batch_from_another_order(order, other_batch, kg):
    record = ProductionRecord(
        production_date=date(2026, 1, 5), order=order, batch=other_batch, unit=kg,
        actual_quantity=D("5"),
    )
    with pytest.raises(ValidationError) as caught:
        record.full_clean()
    assert "batch" in caught.value.message_dict
    with pytest.raises(ValidationError):
        record.save()  # save() guard also refuses the inconsistent link
    assert ProductionRecord.objects.count() == 0


def test_quality_record_rejects_batch_from_another_order(order, other_batch, kg):
    record = QualityRecord(
        record_date=date(2026, 1, 5), order=order, batch=other_batch,
        record_type="REWORK", quantity=D("1"), unit=kg,
    )
    with pytest.raises(ValidationError):
        record.full_clean()
    with pytest.raises(ValidationError):
        record.save()


def test_negative_quality_quantity_rejected(order, kg):
    bad = QualityRecord(
        record_date=date(2026, 1, 5), order=order, record_type="REJECTION",
        quantity=D("-1"), unit=kg,
    )
    with pytest.raises(ValidationError):
        bad.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        QualityRecord.objects.bulk_create([bad])


def test_downtime_end_must_follow_start(order):
    bad = DowntimeRecord(
        order=order, category="OTHER", start_at=aware(5, 11), end_at=aware(5, 10)
    )
    with pytest.raises(ValidationError) as caught:
        bad.full_clean()
    assert "end_at" in caught.value.message_dict
    with pytest.raises(IntegrityError), transaction.atomic():
        DowntimeRecord.objects.bulk_create([bad])


def test_downtime_equal_start_end_rejected(order):
    bad = DowntimeRecord(
        order=order, category="OTHER", start_at=aware(5, 10), end_at=aware(5, 10)
    )
    with pytest.raises(ValidationError):
        bad.full_clean()


def test_downtime_cross_midnight_duration_is_45_minutes(order):
    event = DowntimeRecord.objects.create(
        order=order, category="MECHANICAL", start_at=aware(5, 23, 30), end_at=aware(6, 0, 15)
    )
    assert event.duration_minutes == D("45")


def test_downtime_batch_without_order_fills_order_from_batch(batch):
    event = DowntimeRecord(
        batch=batch, category="OTHER", start_at=aware(5, 8), end_at=aware(5, 9)
    )
    event.full_clean()
    event.save()
    assert event.order_id == batch.order_id


def test_downtime_batch_of_other_order_rejected(order, other_batch):
    event = DowntimeRecord(
        order=order, batch=other_batch, category="OTHER", start_at=aware(5, 8), end_at=aware(5, 9)
    )
    with pytest.raises(ValidationError):
        event.full_clean()


def test_overlapping_records_are_detected_and_touching_are_not(order):
    a = DowntimeRecord.objects.create(
        order=order, category="OTHER", start_at=aware(5, 8), end_at=aware(5, 9)
    )
    DowntimeRecord.objects.create(
        order=order, category="OTHER", start_at=aware(5, 8, 30), end_at=aware(5, 9, 30)
    )
    DowntimeRecord.objects.create(
        order=order, category="OTHER", start_at=aware(5, 9), end_at=aware(5, 10)
    )
    assert a.overlapping_records().count() == 1


def test_batch_unit_must_match_order_unit(order, pcs):
    bad = ProductionBatch(batch_code="B-X", order=order, planned_quantity=D("5"), unit=pcs)
    with pytest.raises(ValidationError) as caught:
        bad.full_clean()
    assert "unit" in caught.value.message_dict


def test_batch_quantity_requires_unit(order):
    bad = ProductionBatch(batch_code="B-Y", order=order, planned_quantity=D("5"))
    with pytest.raises(ValidationError) as caught:
        bad.full_clean()
    assert "unit" in caught.value.message_dict


def test_invalid_status_transition_rejected(order):
    order.status = "COMPLETED"  # PLANNED -> COMPLETED is not permitted
    with pytest.raises(ValidationError) as caught:
        order.full_clean()
    assert "status" in caught.value.message_dict


def test_valid_status_transition_allowed(order):
    order.status = "IN_PROGRESS"
    order.full_clean()


def test_order_unit_cannot_change_when_dependents_exist(order, batch, pcs):
    order.unit = pcs
    with pytest.raises(ValidationError) as caught:
        order.full_clean()
    assert "unit" in caught.value.message_dict


def test_batch_order_cannot_change_after_records_exist(order, other_order, batch, kg):
    ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=order, batch=batch, unit=kg,
        actual_quantity=D("1"),
    )
    batch.order = other_order
    with pytest.raises(ValidationError) as caught:
        batch.full_clean()
    assert "order" in caught.value.message_dict


def test_order_with_batch_cannot_be_deleted(order, batch):
    with pytest.raises(ProtectedError):
        order.delete()


def test_batch_with_records_cannot_be_deleted(order, batch, kg):
    ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=order, batch=batch, unit=kg,
        actual_quantity=D("1"),
    )
    with pytest.raises(ProtectedError):
        batch.delete()


def test_unit_in_use_cannot_be_deleted(order, kg):
    with pytest.raises(ProtectedError):
        kg.delete()


def test_order_without_dependents_can_be_deleted(order):
    order.delete()
    assert ProductionOrder.objects.count() == 0
