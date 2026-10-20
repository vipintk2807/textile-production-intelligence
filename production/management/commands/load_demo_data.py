"""Load (or remove) clearly labelled SYNTHETIC demonstration data.

    python manage.py load_demo_data            insert missing demo orders
    python manage.py load_demo_data --remove   show what would be removed
    python manage.py load_demo_data --remove --yes   remove synthetic data only

Rules
-----
* Never runs automatically (not at startup, not in migrations).
* Every demo order/batch code starts with ``SYN-`` and every note says the data
  is synthetic.
* Idempotent: an order whose code already exists is left completely untouched
  (including its records); nothing is overwritten.
* ``--remove`` only touches records belonging to ``SYN-`` orders, and never
  runs without ``--yes``.
* All values are fixed (no randomness, no dependence on today's date).
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from production.models import (
    SYNTHETIC_NOTE,
    SYNTHETIC_PREFIX,
    DowntimeRecord,
    ProductionBatch,
    ProductionOrder,
    ProductionRecord,
    QualityRecord,
    UnitOfMeasure,
)

logger = logging.getLogger(__name__)
D = Decimal


def _at(day, hour, minute=0):
    """Fixed timestamp in January 2026, in the configured timezone."""
    return timezone.make_aware(datetime(2026, 1, day, hour, minute))


def _save(instance):
    """Validate explicitly (save() does not call full_clean) and store."""
    instance.full_clean()
    instance.save()
    return instance


def _unit(code):
    try:
        return UnitOfMeasure.objects.get(code=code)
    except UnitOfMeasure.DoesNotExist as exc:
        raise CommandError(
            f"Unit '{code}' is missing. Run 'python manage.py migrate' first."
        ) from exc


def _order(code, product, quantity, unit, status):
    return _save(
        ProductionOrder(
            order_code=code,
            product_reference=product,
            order_quantity=quantity,
            unit=unit,
            status=status,
            planned_start_date=date(2026, 1, 5),
            planned_end_date=date(2026, 1, 31),
            notes=SYNTHETIC_NOTE,
        )
    )


def _batch(code, order, quantity, unit):
    return _save(
        ProductionBatch(
            batch_code=code, order=order, planned_quantity=quantity, unit=unit,
            notes=SYNTHETIC_NOTE,
        )
    )


def _prod(day, order, batch, target, actual, unit, label="", note=""):
    return _save(
        ProductionRecord(
            production_date=date(2026, 1, day), order=order, batch=batch,
            period_label=label, target_quantity=target, actual_quantity=actual,
            unit=unit, notes=f"{SYNTHETIC_NOTE} {note}".strip(),
        )
    )


def _quality(day, order, batch, kind, quantity, unit, reason=""):
    return _save(
        QualityRecord(
            record_date=date(2026, 1, day), order=order, batch=batch, record_type=kind,
            quantity=quantity, unit=unit, reason=reason, notes=SYNTHETIC_NOTE,
        )
    )


def _down(order, batch, category, start, end, note=""):
    return _save(
        DowntimeRecord(
            order=order, batch=batch, category=category, start_at=start, end_at=end,
            notes=f"{SYNTHETIC_NOTE} {note}".strip(),
        )
    )


def create_order_one(kg):
    order = _order("SYN-ORD-001", "SYN-STYLE-A", D("1000"), kg, "IN_PROGRESS")
    b1 = _batch("SYN-BAT-001", order, D("400"), kg)
    b2 = _batch("SYN-BAT-002", order, D("600"), kg)
    # Two records on one batch/day: aggregate = (40+45)/(50+50) = 85%.
    _prod(5, order, b1, D("50"), D("40"), kg, "Period A", "Below target.")
    _prod(5, order, b1, D("50"), D("45"), kg, "Period B", "Below target.")
    _prod(6, order, b2, D("100"), D("100"), kg, note="Equal to target.")
    _prod(7, order, b2, D("100"), D("120"), kg, note="Above target.")
    _prod(8, order, b2, None, D("30"), kg, note="Deliberately has no target.")
    _prod(9, order, None, D("0"), D("10"), kg, note="Zero target: achievement unavailable.")
    _down(order, b1, "MECHANICAL", _at(5, 23, 30), _at(6, 0, 15), "Crosses midnight (45 min).")
    _down(order, b2, "SETUP", _at(6, 10, 0), _at(6, 11, 0), "Overlaps the next event.")
    _down(order, b2, "MATERIAL", _at(6, 10, 30), _at(6, 11, 30), "Overlaps the previous.")
    _down(order, None, "OTHER", _at(7, 14, 0), _at(7, 14, 20), "Short event.")
    _quality(5, order, b1, "REWORK", D("5"), kg, "Synthetic reason")
    _quality(6, order, b2, "REWORK", D("2"), kg)
    _quality(5, order, b1, "REJECTION", D("3"), kg, "Synthetic reason")
    _quality(7, order, None, "REJECTION", D("1"), kg)


def create_order_two(pcs, kg):
    order = _order("SYN-ORD-002", "SYN-STYLE-B", D("500"), pcs, "IN_PROGRESS")
    batch = _batch("SYN-BAT-003", order, D("500"), pcs)
    _prod(5, order, batch, D("100"), D("85"), pcs, note="Synthetic 85% example.")
    _prod(
        6, order, batch, D("10"), D("8"), kg,
        note="Deliberately in a different unit to show unit separation.",
    )


def create_order_three(kg):
    order = _order("SYN-ORD-003", "SYN-STYLE-C", D("100"), kg, "COMPLETED")
    _prod(5, order, None, D("100"), D("130"), kg, note="Over-production example (remaining -30).")


class Command(BaseCommand):
    help = "Load or remove clearly labelled synthetic demonstration data (SYN- references)."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true",
                            help="Remove synthetic (SYN-) data instead of loading it.")
        parser.add_argument("--yes", action="store_true",
                            help="Confirm removal. Required together with --remove.")

    def handle(self, *args, **options):
        if options["remove"]:
            return self.remove(confirmed=options["yes"])
        return self.load()

    @transaction.atomic
    def load(self):
        kg, pcs = _unit("kg"), _unit("pcs")
        created = []
        builders = [
            ("SYN-ORD-001", lambda: create_order_one(kg)),
            ("SYN-ORD-002", lambda: create_order_two(pcs, kg)),
            ("SYN-ORD-003", lambda: create_order_three(kg)),
        ]
        for code, build in builders:
            if ProductionOrder.objects.filter(order_code=code).exists():
                self.stdout.write(f"Skipped {code}: already exists (left untouched).")
                continue
            build()
            created.append(code)
            self.stdout.write(f"Created {code} with its records.")
        logger.info("Demo data load finished; created=%s", created)
        self.stdout.write(self.style.WARNING(
            "These are SYNTHETIC demonstration records for software verification. "
            "They are not actual factory records or benchmarks."))

    def _synthetic_orders(self):
        return ProductionOrder.objects.filter(order_code__startswith=SYNTHETIC_PREFIX)

    def remove(self, confirmed):
        orders = self._synthetic_orders()
        ids = list(orders.values_list("pk", flat=True))
        counts = {
            "quality records": QualityRecord.objects.filter(order_id__in=ids).count(),
            "downtime records": DowntimeRecord.objects.filter(order_id__in=ids).count(),
            "production records": ProductionRecord.objects.filter(order_id__in=ids).count(),
            "batches": ProductionBatch.objects.filter(order_id__in=ids).count(),
            "orders": len(ids),
        }
        summary = ", ".join(f"{n} {label}" for label, n in counts.items())
        if not confirmed:
            self.stdout.write(f"Would remove: {summary}. Re-run with --yes to confirm.")
            return
        with transaction.atomic():
            QualityRecord.objects.filter(order_id__in=ids).delete()
            DowntimeRecord.objects.filter(order_id__in=ids).delete()
            ProductionRecord.objects.filter(order_id__in=ids).delete()
            ProductionBatch.objects.filter(order_id__in=ids).delete()
            ProductionOrder.objects.filter(pk__in=ids).delete()
        logger.info("Synthetic demo data removed: %s", summary)
        self.stdout.write(self.style.SUCCESS(f"Removed synthetic data: {summary}."))
