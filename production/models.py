"""Data model.

Validation layers
-----------------
1. Forms (ModelForms call ``full_clean`` through Django's form machinery).
2. ``clean()`` methods below, which hold the cross-field / cross-record rules.
3. Database constraints (CheckConstraint, unique, PROTECT foreign keys).

``Model.save()`` does not call ``full_clean()`` in Django. Code that bypasses
forms (e.g. the demo-data command) must call ``full_clean()`` explicitly. As an
extra safeguard, models that link an order and a batch refuse to save a batch
that belongs to a different order.

Quantities: DecimalField(max_digits=14, decimal_places=3), i.e. up to
99,999,999,999.999. Percentages and other derived values are never stored.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from .services import downtime as downtime_service
from .services import integrity
from .services import status as status_rules

QUANTITY_MAX_DIGITS = 14
QUANTITY_DECIMAL_PLACES = 3

# Prefix used by the synthetic demonstration data loader.
SYNTHETIC_PREFIX = "SYN-"
SYNTHETIC_NOTE = "Synthetic demonstration data - not actual factory records."


class WorkStatus(models.TextChoices):
    PLANNED = "PLANNED", "Planned"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class UnitOfMeasure(models.Model):
    """A controlled unit. Quantities in different units are never combined."""

    class Dimension(models.TextChoices):
        MASS = "MASS", "Mass"
        LENGTH = "LENGTH", "Length"
        COUNT = "COUNT", "Count"

    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=64)
    dimension = models.CharField(max_length=16, choices=Dimension.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} ({self.name})"


class ProductionOrder(models.Model):
    order_code = models.CharField(max_length=40, unique=True)
    product_reference = models.CharField(max_length=120)
    order_quantity = models.DecimalField(
        max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES
    )
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="+")
    planned_start_date = models.DateField(null=True, blank=True)
    planned_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=WorkStatus.choices, default=WorkStatus.PLANNED
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order_code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(order_quantity__gt=0), name="order_quantity_positive"
            ),
            models.CheckConstraint(
                condition=Q(planned_start_date__isnull=True)
                | Q(planned_end_date__isnull=True)
                | Q(planned_end_date__gte=F("planned_start_date")),
                name="order_planned_dates_ordered",
            ),
        ]

    def __str__(self):
        return self.order_code

    def has_dependents(self):
        return (
            self.batches.exists()
            or self.production_records.exists()
            or self.downtime_records.exists()
            or self.quality_records.exists()
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.order_quantity is not None and self.order_quantity <= 0:
            errors["order_quantity"] = "The order quantity must be greater than zero."
        if (
            self.planned_start_date
            and self.planned_end_date
            and self.planned_end_date < self.planned_start_date
        ):
            errors["planned_end_date"] = (
                "The planned end date cannot be earlier than the start date."
            )
        if self.pk:
            old = ProductionOrder.objects.filter(pk=self.pk).values("status", "unit_id").first()
            if old:
                if not status_rules.can_transition(old["status"], self.status):
                    errors["status"] = (
                        f"A {old['status'].replace('_', ' ').lower()} order cannot be "
                        f"changed to {str(self.status).replace('_', ' ').lower()}."
                    )
                if self.unit_id and old["unit_id"] != self.unit_id and self.has_dependents():
                    errors["unit"] = (
                        "The unit cannot be changed while batches or records exist for this order."
                    )
        if errors:
            raise ValidationError(errors)


class OrderBatchLinked(models.Model):
    """Shared order/batch consistency rule for records that reference both."""

    ORDER_OPTIONAL = False

    class Meta:
        abstract = True

    def _order_batch_errors(self):
        if not self.batch_id:
            return {}
        batch_order_id = (
            ProductionBatch.objects.filter(pk=self.batch_id)
            .values_list("order_id", flat=True)
            .first()
        )
        if batch_order_id is None:
            return {"batch": "Select an existing batch."}
        if self.order_id is None:
            if self.ORDER_OPTIONAL:
                self.order_id = batch_order_id
                return {}
            return {"order": "Select the order this batch belongs to."}
        if not integrity.batch_matches_order(batch_order_id, self.order_id):
            return {"batch": "The selected batch does not belong to the selected order."}
        return {}

    def save(self, *args, **kwargs):
        errors = self._order_batch_errors()
        if errors:
            raise ValidationError(errors)
        super().save(*args, **kwargs)


class ProductionBatch(models.Model):
    batch_code = models.CharField(max_length=40, unique=True)
    order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="batches"
    )
    planned_quantity = models.DecimalField(
        max_digits=QUANTITY_MAX_DIGITS,
        decimal_places=QUANTITY_DECIMAL_PLACES,
        null=True,
        blank=True,
    )
    unit = models.ForeignKey(
        UnitOfMeasure, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=WorkStatus.choices, default=WorkStatus.PLANNED
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["batch_code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(planned_quantity__isnull=True) | Q(planned_quantity__gt=0),
                name="batch_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(start_date__isnull=True)
                | Q(end_date__isnull=True)
                | Q(end_date__gte=F("start_date")),
                name="batch_dates_ordered",
            ),
        ]

    def __str__(self):
        return self.batch_code

    def has_dependents(self):
        return (
            self.production_records.exists()
            or self.downtime_records.exists()
            or self.quality_records.exists()
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.planned_quantity is not None:
            if self.planned_quantity <= 0:
                errors["planned_quantity"] = "The planned quantity must be greater than zero."
            if not self.unit_id:
                errors["unit"] = "Select a unit when a planned quantity is entered."
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = "The end date cannot be earlier than the start date."
        if self.order_id and self.unit_id:
            order_unit_id = (
                ProductionOrder.objects.filter(pk=self.order_id)
                .values_list("unit_id", flat=True)
                .first()
            )
            if order_unit_id is not None and order_unit_id != self.unit_id and "unit" not in errors:
                errors["unit"] = "The batch unit must match the unit of its order."
        if self.pk:
            old = ProductionBatch.objects.filter(pk=self.pk).values("status", "order_id").first()
            if old:
                if not status_rules.can_transition(old["status"], self.status):
                    errors["status"] = (
                        f"A {old['status'].replace('_', ' ').lower()} batch cannot be "
                        f"changed to {str(self.status).replace('_', ' ').lower()}."
                    )
                if self.order_id and old["order_id"] != self.order_id and self.has_dependents():
                    errors["order"] = (
                        "The order cannot be changed after records have been linked to this batch."
                    )
        if errors:
            raise ValidationError(errors)


class ProductionRecord(OrderBatchLinked):
    """Target and actual output for one reporting scope.

    The target belongs to this record (not to the order), so several records
    never repeat one order-level target. The target may be missing (NULL),
    which is different from a genuine target of zero.
    """

    production_date = models.DateField()
    order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="production_records"
    )
    batch = models.ForeignKey(
        ProductionBatch,
        on_delete=models.PROTECT,
        related_name="production_records",
        null=True,
        blank=True,
    )
    period_label = models.CharField(max_length=60, blank=True)
    target_quantity = models.DecimalField(
        max_digits=QUANTITY_MAX_DIGITS,
        decimal_places=QUANTITY_DECIMAL_PLACES,
        null=True,
        blank=True,
    )
    actual_quantity = models.DecimalField(
        max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES
    )
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="+")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-production_date", "-id"]
        indexes = [
            models.Index(fields=["production_date"], name="prodrec_date_idx"),
            models.Index(fields=["order", "production_date"], name="prodrec_order_date_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(actual_quantity__gte=0), name="prodrec_actual_nonnegative"
            ),
            models.CheckConstraint(
                condition=Q(target_quantity__isnull=True) | Q(target_quantity__gte=0),
                name="prodrec_target_nonnegative",
            ),
        ]

    def __str__(self):
        return f"Production record #{self.pk or 'new'} ({self.production_date})"

    def clean(self):
        super().clean()
        errors = {}
        if self.actual_quantity is not None and self.actual_quantity < 0:
            errors["actual_quantity"] = "Actual output cannot be negative."
        if self.target_quantity is not None and self.target_quantity < 0:
            errors["target_quantity"] = "The target cannot be negative."
        errors.update(self._order_batch_errors())
        if errors:
            raise ValidationError(errors)


class DowntimeRecord(OrderBatchLinked):
    """A recorded interruption. Start/end timestamps are authoritative.

    Duration is derived (never stored separately), so it cannot disagree with
    the timestamps. Incomplete events (no end time) are not supported.
    """

    ORDER_OPTIONAL = True

    class Category(models.TextChoices):
        # Initial, configurable defaults - NOT an industry-standard list.
        MECHANICAL = "MECHANICAL", "Mechanical"
        ELECTRICAL_POWER = "ELECTRICAL_POWER", "Electrical / power"
        MATERIAL = "MATERIAL", "Material unavailable"
        SETUP = "SETUP", "Setup / changeover"
        OTHER = "OTHER", "Other"

    order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.PROTECT,
        related_name="downtime_records",
        null=True,
        blank=True,
    )
    batch = models.ForeignKey(
        ProductionBatch,
        on_delete=models.PROTECT,
        related_name="downtime_records",
        null=True,
        blank=True,
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_at", "-id"]
        indexes = [models.Index(fields=["start_at"], name="downtime_start_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_at__gt=F("start_at")), name="downtime_end_after_start"
            ),
        ]

    def __str__(self):
        when = self.start_at.strftime("%Y-%m-%d %H:%M") if self.start_at else "no start time"
        return f"Downtime #{self.pk or 'new'} ({when})"

    @property
    def duration_minutes(self):
        return downtime_service.duration_minutes(self.start_at, self.end_at)

    def overlapping_records(self):
        """Other recorded events whose time range overlaps this one.

        The model has no machine field, so an overlap is a flag for review,
        not proof that the same machine was counted twice.
        """
        return DowntimeRecord.objects.filter(
            start_at__lt=self.end_at, end_at__gt=self.start_at
        ).exclude(pk=self.pk)

    def clean(self):
        super().clean()
        errors = {}
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            errors["end_at"] = "The end time must be after the start time."
        errors.update(self._order_batch_errors())
        if errors:
            raise ValidationError(errors)


class QualityRecord(OrderBatchLinked):
    """A rework or rejection quantity, recorded per event.

    Each record is a newly identified quantity (not a cumulative total).
    Quality quantities are never added to or subtracted from production output.
    """

    class RecordType(models.TextChoices):
        REWORK = "REWORK", "Rework"
        REJECTION = "REJECTION", "Rejection"

    record_date = models.DateField()
    order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="quality_records"
    )
    batch = models.ForeignKey(
        ProductionBatch,
        on_delete=models.PROTECT,
        related_name="quality_records",
        null=True,
        blank=True,
    )
    record_type = models.CharField(max_length=12, choices=RecordType.choices)
    quantity = models.DecimalField(
        max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES
    )
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-record_date", "-id"]
        indexes = [models.Index(fields=["record_date"], name="quality_date_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=0), name="quality_quantity_nonnegative"
            ),
        ]

    def __str__(self):
        return f"Quality record #{self.pk or 'new'} ({self.record_type})"

    def clean(self):
        super().clean()
        errors = {}
        if self.quantity is not None and self.quantity < 0:
            errors["quantity"] = "The quantity cannot be negative."
        errors.update(self._order_batch_errors())
        if errors:
            raise ValidationError(errors)
