"""Request-level tests: pages, workflows, CSRF, HTTP methods, error handling."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from production.models import (
    DowntimeRecord,
    ProductionBatch,
    ProductionOrder,
    ProductionRecord,
    QualityRecord,
)

D = Decimal

PAGES = [
    "production:dashboard",
    "production:order_list",
    "production:batch_list",
    "production:production_list",
    "production:downtime_list",
    "production:quality_list",
    "production:report",
    "production:order_create",
    "production:batch_create",
    "production:production_create",
    "production:downtime_create",
    "production:quality_create",
]


def aware(day, hour, minute=0):
    return timezone.make_aware(datetime(2026, 1, day, hour, minute))


@pytest.mark.parametrize("name", PAGES)
def test_every_main_page_opens_on_empty_database(client, db, name):
    response = client.get(reverse(name))
    assert response.status_code == 200


def test_health_endpoint(client, db):
    response = client.get(reverse("production:health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_empty_state_is_explicit(client, db):
    response = client.get(reverse("production:dashboard"))
    assert b"No data has been recorded yet" in response.content


def test_empty_list_says_nothing_recorded_not_filtered(client, db):
    response = client.get(reverse("production:order_list"))
    assert b"No orders have been recorded yet" in response.content


def test_filtered_empty_list_is_distinct_from_empty_database(client, order):
    response = client.get(reverse("production:order_list"), {"q": "no-such-order"})
    assert response.status_code == 200
    assert b"match the selected filters" in response.content


def test_invalid_filters_do_not_crash(client, order):
    response = client.get(reverse("production:production_list"), {"order": "99999"})
    assert response.status_code == 200
    assert b"filters are not valid" in response.content
    response = client.get(
        reverse("production:dashboard"), {"start_date": "2026-02-01", "end_date": "2026-01-01"}
    )
    assert response.status_code == 200
    assert b"filters are not valid" in response.content


def test_create_order_post_redirect_get(client, kg):
    response = client.post(
        reverse("production:order_create"),
        {"order_code": "NEW-1", "product_reference": "S", "order_quantity": "10",
         "unit": kg.pk, "notes": ""},
    )
    order = ProductionOrder.objects.get(order_code="NEW-1")
    assert response.status_code == 302
    assert response.url == reverse("production:order_detail", args=[order.pk])


def test_invalid_order_post_saves_nothing_and_keeps_input(client, kg):
    response = client.post(
        reverse("production:order_create"),
        {"order_code": "KEEP-ME", "product_reference": "S", "order_quantity": "-3", "unit": kg.pk},
    )
    assert response.status_code == 200
    assert ProductionOrder.objects.count() == 0
    assert b"KEEP-ME" in response.content


def test_duplicate_order_post_shows_error(client, order, kg):
    response = client.post(
        reverse("production:order_create"),
        {"order_code": "T-ORD-1", "product_reference": "S", "order_quantity": "1", "unit": kg.pk},
    )
    assert response.status_code == 200
    assert b"already exists" in response.content
    assert ProductionOrder.objects.count() == 1


def test_csrf_is_enforced_on_posts(order, kg):
    strict = Client(enforce_csrf_checks=True)
    response = strict.post(
        reverse("production:order_create"),
        {"order_code": "X", "product_reference": "S", "order_quantity": "1", "unit": kg.pk},
    )
    assert response.status_code == 403
    assert ProductionOrder.objects.count() == 1


def test_form_page_contains_csrf_token(client, db):
    response = client.get(reverse("production:order_create"))
    assert b"csrfmiddlewaretoken" in response.content


def test_get_never_deletes(client, order):
    response = client.get(reverse("production:order_delete", args=[order.pk]))
    assert response.status_code == 200
    assert ProductionOrder.objects.filter(pk=order.pk).exists()


def test_post_delete_removes_order_without_dependents(client, order):
    response = client.post(reverse("production:order_delete", args=[order.pk]))
    assert response.status_code == 302
    assert not ProductionOrder.objects.filter(pk=order.pk).exists()


def test_post_delete_blocked_when_dependents_exist(client, order, batch):
    response = client.post(reverse("production:order_delete", args=[order.pk]))
    assert response.status_code == 302
    assert ProductionOrder.objects.filter(pk=order.pk).exists()
    assert ProductionBatch.objects.filter(pk=batch.pk).exists()


def test_batch_delete_blocked_when_records_exist(client, order, batch, kg):
    ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=order, batch=batch, unit=kg,
        actual_quantity=D("1"),
    )
    client.post(reverse("production:batch_delete", args=[batch.pk]))
    assert ProductionBatch.objects.filter(pk=batch.pk).exists()


def test_missing_records_return_404(client, db):
    for name in ("order_detail", "batch_detail", "production_detail",
                 "downtime_detail", "quality_detail", "order_update"):
        assert client.get(reverse(f"production:{name}", args=[424242])).status_code == 404


def test_full_workflow_through_the_interface(client, kg):
    client.post(reverse("production:order_create"), {
        "order_code": "WF-1", "product_reference": "S", "order_quantity": "100", "unit": kg.pk})
    order = ProductionOrder.objects.get(order_code="WF-1")
    client.post(reverse("production:batch_create"), {
        "batch_code": "WF-B1", "order": order.pk, "planned_quantity": "50", "unit": kg.pk})
    batch = ProductionBatch.objects.get(batch_code="WF-B1")
    response = client.post(reverse("production:production_create"), {
        "production_date": "2026-01-05", "order": order.pk, "batch": batch.pk,
        "target_quantity": "100", "actual_quantity": "85", "unit": kg.pk})
    assert response.status_code == 302
    client.post(reverse("production:downtime_create"), {
        "order": order.pk, "batch": batch.pk, "category": "MECHANICAL",
        "start_at": "2026-01-05T23:30", "end_at": "2026-01-06T00:15"})
    client.post(reverse("production:quality_create"), {
        "record_date": "2026-01-05", "order": order.pk, "batch": batch.pk,
        "record_type": "REJECTION", "quantity": "3", "unit": kg.pk})
    assert DowntimeRecord.objects.count() == 1
    assert QualityRecord.objects.count() == 1

    detail = client.get(reverse("production:order_detail", args=[order.pk]))
    assert detail.status_code == 200
    assert b"85.00%" in detail.content  # 85/100 x 100
    assert b"45 min" in detail.content
    dashboard = client.get(reverse("production:dashboard"))
    assert b"85.00%" in dashboard.content
    report = client.get(reverse("production:report"), {"order": order.pk})
    assert b"85.00%" in report.content
    assert client.get(reverse("production:batch_detail", args=[batch.pk])).status_code == 200


def test_tampered_batch_order_mismatch_is_rejected(client, order, other_batch, kg):
    response = client.post(reverse("production:production_create"), {
        "production_date": "2026-01-05", "order": order.pk, "batch": other_batch.pk,
        "target_quantity": "1", "actual_quantity": "1", "unit": kg.pk})
    assert response.status_code == 200
    assert b"does not belong" in response.content
    assert ProductionRecord.objects.count() == 0


def test_editing_a_production_record_updates_reports(client, order, kg):
    record = ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=order, unit=kg,
        target_quantity=D("100"), actual_quantity=D("50"))
    assert b"50.00%" in client.get(reverse("production:report")).content
    response = client.post(reverse("production:production_update", args=[record.pk]), {
        "production_date": "2026-01-05", "order": order.pk, "batch": "",
        "target_quantity": "100", "actual_quantity": "75", "unit": kg.pk})
    assert response.status_code == 302
    content = client.get(reverse("production:report")).content
    assert b"75.00%" in content and b"50.00%" not in content


def test_zero_target_shows_not_available_never_a_percentage(client, order, kg):
    ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=order, unit=kg,
        target_quantity=D("0"), actual_quantity=D("10"))
    response = client.get(reverse("production:report"))
    assert b"Not available" in response.content
    assert b"The target is zero" in response.content


def test_overlapping_downtime_creates_warning_message(client, order):
    DowntimeRecord.objects.create(
        order=order, category="OTHER", start_at=aware(5, 8), end_at=aware(5, 9))
    response = client.post(reverse("production:downtime_create"), {
        "order": order.pk, "category": "OTHER",
        "start_at": "2026-01-05T08:30", "end_at": "2026-01-05T09:30"}, follow=True)
    texts = [str(m) for m in response.context["messages"]]
    assert any("overlaps" in t for t in texts)


def test_invalid_downtime_post_saves_nothing(client, order):
    response = client.post(reverse("production:downtime_create"), {
        "order": order.pk, "category": "OTHER",
        "start_at": "2026-01-05T09:00", "end_at": "2026-01-05T08:00"})
    assert response.status_code == 200
    assert DowntimeRecord.objects.count() == 0


def test_list_pages_paginate(client, order, kg):
    ProductionRecord.objects.bulk_create([
        ProductionRecord(production_date=date(2026, 1, 5), order=order, unit=kg,
                         actual_quantity=D("1")) for _ in range(30)])
    first = client.get(reverse("production:production_list"))
    assert len(first.context["rows"]) == 25
    second = client.get(reverse("production:production_list"), {"page": 2})
    assert len(second.context["rows"]) == 5


def test_user_text_is_escaped(client, kg):
    ProductionOrder.objects.create(
        order_code="XSS-1", product_reference="<script>alert(1)</script>",
        order_quantity=D("1"), unit=kg)
    response = client.get(reverse("production:order_list"))
    assert b"<script>alert(1)</script>" not in response.content
    assert b"&lt;script&gt;" in response.content


def test_csv_export_matches_report_and_filters(client, order, other_order, kg):
    ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=order, unit=kg,
        target_quantity=D("100"), actual_quantity=D("85"))
    ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=other_order, unit=kg,
        target_quantity=D("10"), actual_quantity=D("10"))
    response = client.get(reverse("production:report_export"), {"order": order.pk})
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 1
    assert rows[0]["order_code"] == "T-ORD-1"
    assert rows[0]["target_achievement_percent"] == "85.00"
    assert rows[0]["variance"] == "-15.000"


def test_csv_export_neutralises_formula_injection(client, kg):
    hostile = ProductionOrder.objects.create(
        order_code="=1+1", product_reference="x", order_quantity=D("1"), unit=kg)
    ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=hostile, unit=kg,
        target_quantity=D("1"), actual_quantity=D("1"))
    response = client.get(reverse("production:report_export"))
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0]["order_code"] == "'=1+1"


def test_csv_export_empty_report_has_only_header(client, db):
    response = client.get(reverse("production:report_export"))
    lines = response.content.decode("utf-8-sig").strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("period_start")


def test_csv_export_rejects_invalid_filters(client, db):
    response = client.get(reverse("production:report_export"), {"order": "9999"})
    assert response.status_code == 400
    response = client.get(reverse("production:report_export"), {"section": "nope"})
    assert response.status_code == 400


def test_downtime_csv_export(client, order):
    DowntimeRecord.objects.create(
        order=order, category="MECHANICAL", start_at=aware(5, 23, 30), end_at=aware(6, 0, 15))
    response = client.get(reverse("production:report_export"), {"section": "downtime"})
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0]["duration_minutes"] == "45.000"


def test_export_does_not_modify_data(client, order, kg):
    ProductionRecord.objects.create(
        production_date=date(2026, 1, 5), order=order, unit=kg, actual_quantity=D("1"))
    before = ProductionRecord.objects.count()
    client.get(reverse("production:report_export"))
    assert ProductionRecord.objects.count() == before
