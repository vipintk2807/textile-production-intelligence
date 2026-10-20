"""Forms: server-side validation is authoritative (JavaScript is optional)."""

from django import forms
from django.db.models import Q

from .models import (
    DowntimeRecord,
    ProductionBatch,
    ProductionOrder,
    ProductionRecord,
    QualityRecord,
    UnitOfMeasure,
    WorkStatus,
)
from .services import status as status_rules

DATETIME_INPUT_FORMATS = [
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
]


def _date_widget():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def _style_widgets(form):
    for field in form.fields.values():
        widget = field.widget
        existing = widget.attrs.get("class", "")
        if isinstance(widget, forms.CheckboxInput):
            css = "form-check"
        elif isinstance(widget, forms.Select):
            css = "form-select"
        else:
            css = "form-control"
        widget.attrs["class"] = f"{existing} {css}".strip()


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_widgets(self)

    def limit_units(self):
        """Offer active units only (plus the record's current unit when editing)."""
        if "unit" not in self.fields:
            return
        condition = Q(is_active=True)
        if self.instance.pk and self.instance.unit_id:
            condition |= Q(pk=self.instance.unit_id)
        self.fields["unit"].queryset = UnitOfMeasure.objects.filter(condition)
        self.fields["unit"].empty_label = "Select a unit"

    def restrict_status_choices(self):
        """New records start as Planned; edits may only follow allowed transitions."""
        if "status" not in self.fields:
            return
        if not self.instance.pk:
            del self.fields["status"]
            return
        current = self.instance.status
        allowed = status_rules.allowed_next(current)
        self.fields["status"].choices = [(current, WorkStatus(current).label)] + [
            (value, WorkStatus(value).label)
            for value in status_rules.ALL_STATUSES
            if value in allowed
        ]


def _label_batch(batch):
    return f"{batch.batch_code} (order {batch.order.order_code})"


class ProductionOrderForm(StyledModelForm):
    class Meta:
        model = ProductionOrder
        fields = [
            "order_code",
            "product_reference",
            "order_quantity",
            "unit",
            "planned_start_date",
            "planned_end_date",
            "status",
            "notes",
        ]
        labels = {
            "order_code": "Order ID",
            "product_reference": "Product / style reference",
            "order_quantity": "Order quantity",
            "planned_start_date": "Planned start date",
            "planned_end_date": "Planned end date",
        }
        widgets = {
            "planned_start_date": _date_widget(),
            "planned_end_date": _date_widget(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        error_messages = {
            "order_code": {"unique": "This order ID already exists. Order IDs must be unique."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit_units()
        self.restrict_status_choices()


class ProductionBatchForm(StyledModelForm):
    class Meta:
        model = ProductionBatch
        fields = [
            "batch_code",
            "order",
            "planned_quantity",
            "unit",
            "start_date",
            "end_date",
            "status",
            "notes",
        ]
        labels = {
            "batch_code": "Batch ID",
            "planned_quantity": "Planned batch quantity (optional)",
            "start_date": "Start date",
            "end_date": "End date",
        }
        widgets = {
            "start_date": _date_widget(),
            "end_date": _date_widget(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        error_messages = {
            "batch_code": {"unique": "This batch ID already exists. Batch IDs must be unique."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit_units()
        self.restrict_status_choices()
        self.fields["unit"].required = False
        self.fields["unit"].empty_label = "Select a unit (required with a quantity)"
        self.fields["order"].empty_label = "Select an order"


class ProductionRecordForm(StyledModelForm):
    class Meta:
        model = ProductionRecord
        fields = [
            "production_date",
            "order",
            "batch",
            "period_label",
            "target_quantity",
            "actual_quantity",
            "unit",
            "notes",
        ]
        labels = {
            "production_date": "Production date",
            "period_label": "Reporting period / shift label (optional)",
            "target_quantity": "Production target (leave blank if none)",
            "actual_quantity": "Actual output",
        }
        widgets = {
            "production_date": _date_widget(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit_units()
        self.fields["order"].empty_label = "Select an order"
        self.fields["batch"].queryset = ProductionBatch.objects.select_related("order")
        self.fields["batch"].label_from_instance = _label_batch
        self.fields["batch"].empty_label = "No batch (order-level record)"


class DowntimeRecordForm(StyledModelForm):
    class Meta:
        model = DowntimeRecord
        fields = ["order", "batch", "category", "start_at", "end_at", "notes"]
        labels = {"start_at": "Start (date and time)", "end_at": "End (date and time)"}
        widgets = {
            "start_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "end_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("start_at", "end_at"):
            self.fields[name].input_formats = DATETIME_INPUT_FORMATS
        self.fields["order"].empty_label = "Not linked to an order"
        self.fields["batch"].queryset = ProductionBatch.objects.select_related("order")
        self.fields["batch"].label_from_instance = _label_batch
        self.fields["batch"].empty_label = "Not linked to a batch"


class QualityRecordForm(StyledModelForm):
    class Meta:
        model = QualityRecord
        fields = [
            "record_date",
            "order",
            "batch",
            "record_type",
            "quantity",
            "unit",
            "reason",
            "notes",
        ]
        labels = {
            "record_date": "Reporting date",
            "record_type": "Record type",
            "quantity": "Quantity (newly identified, this event)",
            "reason": "Reason / category (optional)",
        }
        widgets = {
            "record_date": _date_widget(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.limit_units()
        self.fields["order"].empty_label = "Select an order"
        self.fields["batch"].queryset = ProductionBatch.objects.select_related("order")
        self.fields["batch"].label_from_instance = _label_batch
        self.fields["batch"].empty_label = "No batch (order-level record)"


class ListFilterForm(forms.Form):
    """One validating filter form; each page keeps only the fields it needs."""

    q = forms.CharField(required=False, max_length=100, label="Search")
    order = forms.ModelChoiceField(
        queryset=ProductionOrder.objects.all(), required=False, empty_label="All orders"
    )
    batch = forms.ModelChoiceField(
        queryset=ProductionBatch.objects.select_related("order"),
        required=False,
        empty_label="All batches",
    )
    start_date = forms.DateField(required=False, widget=_date_widget(), label="From date")
    end_date = forms.DateField(required=False, widget=_date_widget(), label="To date")
    status = forms.ChoiceField(
        required=False, choices=[("", "Any status"), *WorkStatus.choices], label="Status"
    )
    order_status = forms.ChoiceField(
        required=False,
        choices=[("", "Any order status"), *WorkStatus.choices],
        label="Order status",
    )
    downtime_category = forms.ChoiceField(
        required=False,
        choices=[("", "Any category"), *DowntimeRecord.Category.choices],
        label="Downtime category",
    )
    quality_type = forms.ChoiceField(
        required=False,
        choices=[("", "Rework and rejection"), *QualityRecord.RecordType.choices],
        label="Quality record type",
    )

    def __init__(self, *args, keep=None, **kwargs):
        super().__init__(*args, **kwargs)
        if keep is not None:
            for name in list(self.fields):
                if name not in keep:
                    del self.fields[name]
        if "batch" in self.fields:
            self.fields["batch"].label_from_instance = _label_batch
        _style_widgets(self)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and start > end:
            self.add_error("end_date", "The end date cannot be earlier than the start date.")
        order = cleaned.get("order")
        batch = cleaned.get("batch")
        if order and batch and batch.order_id != order.pk:
            self.add_error("batch", "The selected batch does not belong to the selected order.")
        return cleaned
