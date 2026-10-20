"""Form validation tests (server-side)."""

from datetime import date
from decimal import Decimal

from production.forms import (
    DowntimeRecordForm,
    ListFilterForm,
    ProductionBatchForm,
    ProductionOrderForm,
    ProductionRecordForm,
    QualityRecordForm,
)

def order_data(kg, **overrides):
    data = {
        "order_code": "T-NEW-1",
        "product_reference": "STYLE",
        "order_quantity": "100",
        "unit": kg.pk,
        "planned_start_date": "2026-01-01",
        "planned_end_date": "2026-01-31",
        "notes": "",
    }
    data.update(overrides)
    return data


def test_order_form_valid(kg, db):
    form = ProductionOrderForm(order_data(kg))
    assert form.is_valid(), form.errors
    order = form.save()
    assert order.status == "PLANNED"
    assert order.order_quantity == Decimal("100")


def test_order_form_has_no_status_field_on_create(kg, db):
    assert "status" not in ProductionOrderForm().fields


def test_order_form_duplicate_code(kg, order):
    form = ProductionOrderForm(order_data(kg, order_code="T-ORD-1"))
    assert not form.is_valid()
    assert "order_code" in form.errors


def test_order_form_missing_required_fields(kg, db):
    form = ProductionOrderForm({})
    assert not form.is_valid()
    for name in ("order_code", "product_reference", "order_quantity", "unit"):
        assert name in form.errors


def test_order_form_rejects_zero_negative_and_text_quantity(kg, db):
    for bad in ("0", "-5", "abc", ""):
        form = ProductionOrderForm(order_data(kg, order_quantity=bad))
        assert not form.is_valid(), bad
        assert "order_quantity" in form.errors, bad


def test_order_form_rejects_too_many_decimals(kg, db):
    form = ProductionOrderForm(order_data(kg, order_quantity="1.2345"))
    assert not form.is_valid()
    assert "order_quantity" in form.errors


def test_order_form_rejects_unknown_unit(kg, db):
    form = ProductionOrderForm(order_data(kg, unit=999999))
    assert not form.is_valid()
    assert "unit" in form.errors


def test_order_form_rejects_inactive_unit(kg, db):
    kg.is_active = False
    kg.save()
    form = ProductionOrderForm(order_data(kg))
    assert not form.is_valid()
    assert "unit" in form.errors


def test_order_form_rejects_end_before_start(kg, db):
    form = ProductionOrderForm(order_data(kg, planned_end_date="2025-12-31"))
    assert not form.is_valid()
    assert "planned_end_date" in form.errors


def test_order_form_edit_limits_status_choices(order):
    form = ProductionOrderForm(instance=order)
    values = [value for value, _label in form.fields["status"].choices]
    assert values == ["PLANNED", "IN_PROGRESS", "CANCELLED"]


def test_order_form_rejects_tampered_status_transition(kg, order):
    data = order_data(kg, order_code="T-ORD-1", status="COMPLETED")
    form = ProductionOrderForm(data, instance=order)
    assert not form.is_valid()


def test_batch_form_valid_and_order_required(kg, order):
    form = ProductionBatchForm(
        {"batch_code": "B-1", "order": order.pk, "planned_quantity": "10", "unit": kg.pk}
    )
    assert form.is_valid(), form.errors
    missing = ProductionBatchForm({"batch_code": "B-2"})
    assert not missing.is_valid() and "order" in missing.errors


def test_batch_form_rejects_nonexistent_order(db):
    form = ProductionBatchForm({"batch_code": "B-3", "order": 424242})
    assert not form.is_valid()
    assert "order" in form.errors


def production_data(order, kg, **overrides):
    data = {
        "production_date": "2026-01-05",
        "order": order.pk,
        "batch": "",
        "period_label": "",
        "target_quantity": "100",
        "actual_quantity": "85",
        "unit": kg.pk,
        "notes": "",
    }
    data.update(overrides)
    return data


def test_production_form_valid_with_target(order, kg):
    form = ProductionRecordForm(production_data(order, kg))
    assert form.is_valid(), form.errors


def test_production_form_blank_target_is_allowed_and_stays_null(order, kg):
    form = ProductionRecordForm(production_data(order, kg, target_quantity=""))
    assert form.is_valid(), form.errors
    assert form.save().target_quantity is None


def test_production_form_zero_actual_allowed(order, kg):
    assert ProductionRecordForm(production_data(order, kg, actual_quantity="0")).is_valid()


def test_production_form_missing_actual_rejected(order, kg):
    form = ProductionRecordForm(production_data(order, kg, actual_quantity=""))
    assert not form.is_valid() and "actual_quantity" in form.errors


def test_production_form_negative_values_rejected(order, kg):
    assert not ProductionRecordForm(production_data(order, kg, actual_quantity="-1")).is_valid()
    assert not ProductionRecordForm(production_data(order, kg, target_quantity="-1")).is_valid()


def test_production_form_batch_must_belong_to_order(order, other_batch, kg):
    form = ProductionRecordForm(production_data(order, kg, batch=other_batch.pk))
    assert not form.is_valid()
    assert "batch" in form.errors


def test_production_form_accepts_matching_batch(order, batch, kg):
    assert ProductionRecordForm(production_data(order, kg, batch=batch.pk)).is_valid()


def test_production_form_invalid_date_rejected(order, kg):
    form = ProductionRecordForm(production_data(order, kg, production_date="2026-13-45"))
    assert not form.is_valid() and "production_date" in form.errors


def downtime_data(order, **overrides):
    data = {
        "order": order.pk,
        "batch": "",
        "category": "MECHANICAL",
        "start_at": "2026-01-05T23:30",
        "end_at": "2026-01-06T00:15",
        "notes": "",
    }
    data.update(overrides)
    return data


def test_downtime_form_cross_midnight_is_valid(order):
    form = DowntimeRecordForm(downtime_data(order))
    assert form.is_valid(), form.errors
    assert form.save().duration_minutes == Decimal("45")


def test_downtime_form_end_before_start_rejected(order):
    form = DowntimeRecordForm(downtime_data(order, end_at="2026-01-05T23:00"))
    assert not form.is_valid() and "end_at" in form.errors


def test_downtime_form_equal_times_rejected(order):
    form = DowntimeRecordForm(downtime_data(order, end_at="2026-01-05T23:30"))
    assert not form.is_valid()


def test_downtime_form_missing_end_rejected(order):
    form = DowntimeRecordForm(downtime_data(order, end_at=""))
    assert not form.is_valid() and "end_at" in form.errors


def test_downtime_form_invalid_category_rejected(order):
    form = DowntimeRecordForm(downtime_data(order, category="NOT_A_CATEGORY"))
    assert not form.is_valid() and "category" in form.errors


def test_downtime_form_order_optional(db):
    data = {
        "order": "",
        "batch": "",
        "category": "OTHER",
        "start_at": "2026-01-05T08:00",
        "end_at": "2026-01-05T09:00",
        "notes": "",
    }
    form = DowntimeRecordForm(data)
    assert form.is_valid(), form.errors


def quality_data(order, kg, **overrides):
    data = {
        "record_date": "2026-01-05",
        "order": order.pk,
        "batch": "",
        "record_type": "REWORK",
        "quantity": "5",
        "unit": kg.pk,
        "reason": "",
        "notes": "",
    }
    data.update(overrides)
    return data


def test_quality_form_valid(order, kg):
    assert QualityRecordForm(quality_data(order, kg)).is_valid()


def test_quality_form_rejects_negative_and_bad_type(order, kg):
    assert not QualityRecordForm(quality_data(order, kg, quantity="-1")).is_valid()
    assert not QualityRecordForm(quality_data(order, kg, record_type="SCRAP")).is_valid()


def test_quality_form_batch_must_belong_to_order(order, other_batch, kg):
    form = QualityRecordForm(quality_data(order, kg, batch=other_batch.pk))
    assert not form.is_valid() and "batch" in form.errors


def test_filter_form_rejects_reversed_dates(db):
    form = ListFilterForm({"start_date": "2026-02-01", "end_date": "2026-01-01"})
    assert not form.is_valid() and "end_date" in form.errors


def test_filter_form_rejects_mismatched_batch(order, other_batch):
    form = ListFilterForm({"order": order.pk, "batch": other_batch.pk})
    assert not form.is_valid() and "batch" in form.errors


def test_filter_form_rejects_nonexistent_order(db):
    form = ListFilterForm({"order": 987654})
    assert not form.is_valid() and "order" in form.errors


def test_filter_form_valid_dates_and_equal_dates(db):
    form = ListFilterForm({"start_date": "2026-01-05", "end_date": "2026-01-05"})
    assert form.is_valid()
    assert form.cleaned_data["start_date"] == date(2026, 1, 5)
