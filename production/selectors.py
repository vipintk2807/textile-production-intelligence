"""Read/query layer: filtered ORM aggregation feeding the KPI services.

Rules applied everywhere
------------------------
* Filters are applied in the database, never to an in-memory sample.
* Date filters are INCLUSIVE of both the start and end date (local dates).
  Downtime uses the half-open window [start 00:00, end + 1 day 00:00).
* Production and quality are aggregated in SEPARATE queries and merged in
  Python, so joining one-to-many tables can never multiply sums.
* Different units are never added together: every group carries its unit.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    DowntimeRecord,
    ProductionBatch,
    ProductionOrder,
    ProductionRecord,
    QualityRecord,
    WorkStatus,
)
from .services import downtime as downtime_service
from .services import kpis, quality
from .services.kpis import KpiResult, ProductionTotals

logger = logging.getLogger(__name__)

QUANTITY_PLACES = Decimal("0.001")


def _q(value):
    """Normalise an aggregate coming back from the database (None stays None)."""
    if value is None:
        return None
    return Decimal(value).quantize(QUANTITY_PLACES)


@dataclass(frozen=True)
class ReportFilters:
    start_date: date | None = None
    end_date: date | None = None
    order_id: int | None = None
    batch_id: int | None = None
    order_status: str = ""
    downtime_category: str = ""
    quality_type: str = ""

    @classmethod
    def from_cleaned(cls, cleaned):
        order = cleaned.get("order")
        batch = cleaned.get("batch")
        return cls(
            start_date=cleaned.get("start_date"),
            end_date=cleaned.get("end_date"),
            order_id=order.pk if order else None,
            batch_id=batch.pk if batch else None,
            order_status=cleaned.get("order_status") or "",
            downtime_category=cleaned.get("downtime_category") or "",
            quality_type=cleaned.get("quality_type") or "",
        )

    def window(self):
        """Half-open aware datetime window for timestamp-based records."""
        return downtime_service.window_from_dates(
            self.start_date, self.end_date, timezone.get_current_timezone()
        )

    def describe(self):
        """Human-readable list of the active filters."""
        parts = []
        if self.start_date or self.end_date:
            start = self.start_date.isoformat() if self.start_date else "earliest"
            end = self.end_date.isoformat() if self.end_date else "latest"
            parts.append(f"Period: {start} to {end} (inclusive)")
        else:
            parts.append("Period: all dates")
        if self.order_id:
            code = ProductionOrder.objects.filter(pk=self.order_id).values_list(
                "order_code", flat=True
            ).first()
            parts.append(f"Order: {code or self.order_id}")
        if self.batch_id:
            code = ProductionBatch.objects.filter(pk=self.batch_id).values_list(
                "batch_code", flat=True
            ).first()
            parts.append(f"Batch: {code or self.batch_id}")
        if self.order_status:
            parts.append(f"Order status: {WorkStatus(self.order_status).label}")
        if self.downtime_category:
            label = DowntimeRecord.Category(self.downtime_category).label
            parts.append(f"Downtime category: {label}")
        if self.quality_type:
            parts.append(f"Quality type: {QualityRecord.RecordType(self.quality_type).label}")
        return parts


# --------------------------------------------------------------------------
# Shared filter helpers (used by list pages and reports)
# --------------------------------------------------------------------------
def apply_order_batch(qs, cleaned):
    order = cleaned.get("order")
    batch = cleaned.get("batch")
    if order:
        qs = qs.filter(order=order)
    if batch:
        qs = qs.filter(batch=batch)
    return qs


def apply_date_range(qs, cleaned, field_name):
    start = cleaned.get("start_date")
    end = cleaned.get("end_date")
    if start:
        qs = qs.filter(**{f"{field_name}__gte": start})
    if end:
        qs = qs.filter(**{f"{field_name}__lte": end})
    return qs


def apply_downtime_window(qs, window_start, window_end):
    """Keep events overlapping the half-open window."""
    if window_end is not None:
        qs = qs.filter(start_at__lt=window_end)
    if window_start is not None:
        qs = qs.filter(end_at__gt=window_start)
    return qs


def production_qs(f):
    qs = ProductionRecord.objects.all()
    if f.start_date:
        qs = qs.filter(production_date__gte=f.start_date)
    if f.end_date:
        qs = qs.filter(production_date__lte=f.end_date)
    if f.order_id:
        qs = qs.filter(order_id=f.order_id)
    if f.batch_id:
        qs = qs.filter(batch_id=f.batch_id)
    if f.order_status:
        qs = qs.filter(order__status=f.order_status)
    return qs


def quality_qs(f):
    qs = QualityRecord.objects.all()
    if f.start_date:
        qs = qs.filter(record_date__gte=f.start_date)
    if f.end_date:
        qs = qs.filter(record_date__lte=f.end_date)
    if f.order_id:
        qs = qs.filter(order_id=f.order_id)
    if f.batch_id:
        qs = qs.filter(batch_id=f.batch_id)
    if f.order_status:
        qs = qs.filter(order__status=f.order_status)
    if f.quality_type:
        qs = qs.filter(record_type=f.quality_type)
    return qs


def downtime_qs(f):
    qs = DowntimeRecord.objects.all()
    window_start, window_end = f.window()
    qs = apply_downtime_window(qs, window_start, window_end)
    if f.order_id:
        qs = qs.filter(order_id=f.order_id)
    if f.batch_id:
        qs = qs.filter(batch_id=f.batch_id)
    if f.order_status:
        qs = qs.filter(order__status=f.order_status)
    if f.downtime_category:
        qs = qs.filter(category=f.downtime_category)
    return qs


# --------------------------------------------------------------------------
# Report structures
# --------------------------------------------------------------------------
@dataclass
class ReportRow:
    order_id: int
    order_code: str
    product_reference: str
    batch_id: int | None
    batch_code: str | None
    unit: str
    order_status: str = ""
    production: kpis.ProductionSummary | None = None
    rework: Decimal | None = None
    rejection: Decimal | None = None

    @property
    def order_status_label(self):
        return ROW_STATUS_LABELS.get(self.order_status, self.order_status)


ROW_STATUS_LABELS = dict(WorkStatus.choices)


@dataclass
class UnitTotals:
    unit: str
    summary: kpis.ProductionSummary | None
    rework: Decimal | None
    rejection: Decimal | None
    rework_rate: KpiResult
    rejection_rate: KpiResult


@dataclass
class DowntimeEvent:
    id: int
    order_id: int | None
    order_code: str | None
    batch_id: int | None
    batch_code: str | None
    category: str
    start: object
    end: object

    @property
    def category_label(self):
        try:
            return DowntimeRecord.Category(self.category).label
        except ValueError:
            return self.category


@dataclass
class DowntimeGroup:
    label: str
    events: int
    sum_minutes: Decimal
    unique_minutes: Decimal


@dataclass
class DowntimeSummary:
    events: list = field(default_factory=list)
    event_count: int = 0
    sum_minutes: Decimal = Decimal("0")
    unique_minutes: Decimal = Decimal("0")
    overlap_pairs: int = 0
    groups: list = field(default_factory=list)
    by_category: list = field(default_factory=list)


@dataclass
class ReportData:
    filters: ReportFilters
    rows: list
    unit_totals: list
    downtime: DowntimeSummary
    show_rework: bool = True
    show_rejection: bool = True

    @property
    def has_data(self):
        return bool(self.rows or self.downtime.event_count)


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------
def _production_rows(f):
    aggregated = (
        production_qs(f)
        .order_by()
        .values(
            "order_id",
            "order__order_code",
            "order__product_reference",
            "order__status",
            "batch_id",
            "batch__batch_code",
            "unit__code",
        )
        .annotate(
            records=Count("id"),
            records_with_target=Count("target_quantity"),
            target=Sum("target_quantity"),
            actual=Sum("actual_quantity"),
            actual_with_target=Sum(
                "actual_quantity", filter=Q(target_quantity__isnull=False)
            ),
        )
    )
    rows = {}
    for item in aggregated:
        key = (item["order_id"], item["batch_id"], item["unit__code"])
        totals = ProductionTotals(
            unit=item["unit__code"],
            records=item["records"],
            actual_total=_q(item["actual"]) or Decimal("0"),
            records_with_target=item["records_with_target"],
            target_total=_q(item["target"]),
            actual_with_target=_q(item["actual_with_target"]) or Decimal("0"),
        )
        rows[key] = ReportRow(
            order_id=item["order_id"],
            order_code=item["order__order_code"],
            product_reference=item["order__product_reference"],
            batch_id=item["batch_id"],
            batch_code=item["batch__batch_code"],
            unit=item["unit__code"],
            order_status=item["order__status"],
            production=kpis.evaluate_production(totals),
        )
    return rows


def _merge_quality(rows, f):
    aggregated = (
        quality_qs(f)
        .order_by()
        .values(
            "order_id",
            "order__order_code",
            "order__product_reference",
            "order__status",
            "batch_id",
            "batch__batch_code",
            "unit__code",
            "record_type",
        )
        .annotate(total=Sum("quantity"))
    )
    for item in aggregated:
        key = (item["order_id"], item["batch_id"], item["unit__code"])
        row = rows.get(key)
        if row is None:
            row = ReportRow(
                order_id=item["order_id"],
                order_code=item["order__order_code"],
                product_reference=item["order__product_reference"],
                batch_id=item["batch_id"],
                batch_code=item["batch__batch_code"],
                unit=item["unit__code"],
                order_status=item["order__status"],
            )
            rows[key] = row
        total = _q(item["total"])
        if item["record_type"] == quality.REWORK:
            row.rework = total
        elif item["record_type"] == quality.REJECTION:
            row.rejection = total


def _add(current, value):
    if value is None:
        return current
    return value if current is None else current + value


def _unit_totals(rows):
    by_unit = defaultdict(list)
    for row in rows:
        by_unit[row.unit].append(row)
    result = []
    for unit in sorted(by_unit):
        group = by_unit[unit]
        production_rows = [r.production for r in group if r.production is not None]
        summary = None
        if production_rows:
            target_total = None
            for item in production_rows:
                target_total = _add(target_total, item.totals.target_total)
            summary = kpis.evaluate_production(
                ProductionTotals(
                    unit=unit,
                    records=sum(i.totals.records for i in production_rows),
                    actual_total=sum(
                        (i.totals.actual_total for i in production_rows), Decimal("0")
                    ),
                    records_with_target=sum(i.totals.records_with_target for i in production_rows),
                    target_total=target_total,
                    actual_with_target=sum(
                        (i.totals.actual_with_target for i in production_rows), Decimal("0")
                    ),
                )
            )
        rework = None
        rejection = None
        for row in group:
            rework = _add(rework, row.rework)
            rejection = _add(rejection, row.rejection)
        # No approved denominator exists, so rates are always "not available".
        result.append(
            UnitTotals(
                unit=unit,
                summary=summary,
                rework=rework,
                rejection=rejection,
                rework_rate=quality.quality_rate(rework, None, unit, None),
                rejection_rate=quality.quality_rate(rejection, None, unit, None),
            )
        )
    return result


def downtime_events(f):
    rows = (
        downtime_qs(f)
        .order_by("start_at", "id")
        .values(
            "id",
            "order_id",
            "order__order_code",
            "batch_id",
            "batch__batch_code",
            "category",
            "start_at",
            "end_at",
        )
    )
    return [
        DowntimeEvent(
            id=r["id"],
            order_id=r["order_id"],
            order_code=r["order__order_code"],
            batch_id=r["batch_id"],
            batch_code=r["batch__batch_code"],
            category=r["category"],
            start=r["start_at"],
            end=r["end_at"],
        )
        for r in rows
    ]


def summarize_downtime(events, window_start=None, window_end=None):
    """Both downtime metrics, clearly separated (see services/downtime.py)."""
    intervals = [(e.start, e.end) for e in events]
    summary = DowntimeSummary(events=events, event_count=len(events))
    if not events:
        return summary
    summary.sum_minutes = downtime_service.sum_event_minutes(intervals, window_start, window_end)
    summary.unique_minutes = downtime_service.unique_elapsed_minutes(
        intervals, window_start, window_end
    )
    summary.overlap_pairs = len(downtime_service.find_overlaps(intervals))

    grouped = defaultdict(list)
    for event in events:
        grouped[(event.order_code or "", event.batch_code or "")].append(event)
    for (order_code, batch_code), items in sorted(grouped.items()):
        pairs = [(e.start, e.end) for e in items]
        label = order_code or "Not linked to an order"
        if batch_code:
            label += f" / {batch_code}"
        summary.groups.append(
            DowntimeGroup(
                label=label,
                events=len(items),
                sum_minutes=downtime_service.sum_event_minutes(pairs, window_start, window_end),
                unique_minutes=downtime_service.unique_elapsed_minutes(
                    pairs, window_start, window_end
                ),
            )
        )
    by_category = defaultdict(list)
    for event in events:
        by_category[event.category_label].append(event)
    for label, items in sorted(by_category.items()):
        pairs = [(e.start, e.end) for e in items]
        summary.by_category.append(
            DowntimeGroup(
                label=label,
                events=len(items),
                sum_minutes=downtime_service.sum_event_minutes(pairs, window_start, window_end),
                unique_minutes=downtime_service.unique_elapsed_minutes(
                    pairs, window_start, window_end
                ),
            )
        )
    return summary


def build_report(f):
    """The single authoritative report used by dashboard, details and exports."""
    rows = _production_rows(f)
    _merge_quality(rows, f)
    ordered = sorted(
        rows.values(), key=lambda r: (r.order_code, r.batch_code or "", r.unit)
    )
    window_start, window_end = f.window()
    return ReportData(
        filters=f,
        rows=ordered,
        unit_totals=_unit_totals(ordered),
        downtime=summarize_downtime(downtime_events(f), window_start, window_end),
        show_rework=f.quality_type in ("", quality.REWORK),
        show_rejection=f.quality_type in ("", quality.REJECTION),
    )


# --------------------------------------------------------------------------
# Orders: remaining quantity, status counts, items needing attention
# --------------------------------------------------------------------------
def remaining_for_orders(orders):
    """Map order pk -> RemainingResult (orders need ``unit`` select_related)."""
    orders = list(orders)
    ids = [o.pk for o in orders]
    outputs = defaultdict(list)
    aggregated = (
        ProductionRecord.objects.filter(order_id__in=ids)
        .order_by()
        .values("order_id", "unit__code")
        .annotate(total=Sum("actual_quantity"), records=Count("id"))
    )
    for item in aggregated:
        outputs[item["order_id"]].append((item["unit__code"], _q(item["total"]), item["records"]))
    return {
        o.pk: kpis.remaining_quantity(o.order_quantity, o.unit.code, outputs[o.pk])
        for o in orders
    }


def status_counts():
    counts = {value: 0 for value, _label in WorkStatus.choices}
    for item in ProductionOrder.objects.order_by().values("status").annotate(n=Count("id")):
        counts[item["status"]] = item["n"]
    return [(WorkStatus(value).label, n) for value, n in counts.items()]


def attention_orders(limit=20):
    """Orders whose recorded status and recorded output disagree.

    Flags (a) recorded output above the order quantity and (b) orders marked
    Completed that still have a positive remaining quantity. These are prompts
    to investigate, not verdicts.
    """
    orders = list(ProductionOrder.objects.select_related("unit").exclude(status="CANCELLED"))
    remaining = remaining_for_orders(orders)
    flagged = []
    for order in orders:
        info = remaining[order.pk]
        if not info.result.ok:
            continue
        if info.over_produced:
            flagged.append((order, info, "Recorded output exceeds the order quantity."))
        elif order.status == WorkStatus.COMPLETED and info.result.value > 0:
            flagged.append(
                (order, info, "Marked Completed but recorded output is below the order quantity.")
            )
    return flagged[:limit]
