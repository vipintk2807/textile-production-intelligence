"""Views: thin request handling. Calculations live in services/selectors."""

import logging

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from . import formatting, selectors
from .forms import (
    DowntimeRecordForm,
    ListFilterForm,
    ProductionBatchForm,
    ProductionOrderForm,
    ProductionRecordForm,
    QualityRecordForm,
)
from .models import (
    DowntimeRecord,
    ProductionBatch,
    ProductionOrder,
    ProductionRecord,
    QualityRecord,
)
from .selectors import ReportFilters
from .services import csv_export, kpis
from .services import downtime as downtime_service

logger = logging.getLogger(__name__)

PAGE_SIZE = 25


# --------------------------------------------------------------------------
# Shared mixins
# --------------------------------------------------------------------------
class SafeSaveMixin:
    """Save inside a transaction; never report a failed write as a success."""

    def form_valid(self, form):
        try:
            with transaction.atomic():
                return super().form_valid(form)
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
        except (IntegrityError, DatabaseError):
            logger.exception("Database error while saving %s", self.model.__name__)
            form.add_error(
                None,
                "The record could not be saved because of a database error. "
                "Nothing was saved. Please try again.",
            )
        return self.form_invalid(form)


class FormPageMixin:
    """Common context/redirect behaviour for create and edit pages."""

    page_title = ""
    list_url_name = ""
    detail_url_name = ""
    prefill_fields = ("order", "batch")

    def get_initial(self):
        initial = super().get_initial()
        for name in self.prefill_fields:
            value = self.request.GET.get(name, "")
            if value.isdigit():
                initial[name] = int(value)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = getattr(self, "object", None)
        is_edit = bool(obj is not None and obj.pk)
        context["page_title"] = self.page_title
        context["is_edit"] = is_edit
        context["cancel_url"] = (
            reverse(self.detail_url_name, args=[obj.pk])
            if is_edit
            else reverse(self.list_url_name)
        )
        return context

    def get_success_url(self):
        return reverse(self.detail_url_name, args=[self.object.pk])


class FilteredListView(ListView):
    paginate_by = PAGE_SIZE
    filter_fields = ()
    page_title = ""
    create_url_name = ""
    create_label = ""

    def base_queryset(self):
        return self.model.objects.all()

    def apply_filters(self, queryset, cleaned):
        return queryset

    def get_queryset(self):
        self.filter_form = ListFilterForm(self.request.GET or None, keep=self.filter_fields)
        self.filter_invalid = False
        queryset = self.base_queryset()
        if self.filter_form.is_bound:
            if self.filter_form.is_valid():
                queryset = self.apply_filters(queryset, self.filter_form.cleaned_data)
            else:
                self.filter_invalid = True
                queryset = queryset.none()
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        cleaned = (
            self.filter_form.cleaned_data
            if self.filter_form.is_bound and not self.filter_invalid
            else {}
        )
        context.update(
            filter_form=self.filter_form,
            filter_invalid=self.filter_invalid,
            filters_active=any(cleaned.values()),
            query_string=params.urlencode(),
            page_title=self.page_title,
            create_url=reverse(self.create_url_name),
            create_label=self.create_label,
        )
        return context


# --------------------------------------------------------------------------
# Dashboard, reports, health
# --------------------------------------------------------------------------
def _filters_from_request(request, keep):
    """Return (form, ReportFilters or None). None means the filters are invalid."""
    form = ListFilterForm(request.GET or None, keep=keep)
    if not form.is_bound:
        return form, ReportFilters()
    if form.is_valid():
        return form, ReportFilters.from_cleaned(form.cleaned_data)
    return form, None


def dashboard(request):
    form, filters = _filters_from_request(request, ("start_date", "end_date", "order", "batch"))
    context = {
        "page_title": "Dashboard",
        "filter_form": form,
        "filter_invalid": filters is None,
        "status_counts": selectors.status_counts(),
        "attention": selectors.attention_orders(),
        "report": None,
        "order_count": ProductionOrder.objects.count(),
    }
    if filters is not None:
        context["report"] = selectors.build_report(filters)
        context["filter_descriptions"] = filters.describe()
    return render(request, "production/dashboard.html", context)


REPORT_FILTER_FIELDS = (
    "start_date",
    "end_date",
    "order",
    "batch",
    "order_status",
    "downtime_category",
    "quality_type",
)


def report(request):
    form, filters = _filters_from_request(request, REPORT_FILTER_FIELDS)
    context = {
        "page_title": "Reports",
        "filter_form": form,
        "filter_invalid": filters is None,
        "report": None,
        "export_query": request.GET.urlencode(),
    }
    if filters is not None:
        context["report"] = selectors.build_report(filters)
        context["filter_descriptions"] = filters.describe()
    return render(request, "production/report.html", context)


SUMMARY_CSV_HEADER = [
    "period_start",
    "period_end",
    "order_code",
    "batch_code",
    "unit",
    "production_records",
    "target_total_records_with_target",
    "actual_total_all_records",
    "actual_total_records_with_target",
    "target_achievement_percent",
    "variance",
    "rework_quantity",
    "rejection_quantity",
]


def _summary_csv_rows(data):
    filters = data.filters
    start = filters.start_date.isoformat() if filters.start_date else ""
    end = filters.end_date.isoformat() if filters.end_date else ""
    for row in data.rows:
        summary = row.production
        totals = summary.totals if summary else None
        achievement = (
            kpis.quantize_percent(summary.achievement.value)
            if summary and summary.achievement.ok
            else None
        )
        variance = (
            kpis.quantize_quantity(summary.variance.value)
            if summary and summary.variance.ok
            else None
        )
        yield [
            start,
            end,
            row.order_code,
            row.batch_code or "",
            row.unit,
            totals.records if totals else 0,
            totals.target_total if totals else None,
            totals.actual_total if totals else None,
            totals.actual_with_target if totals else None,
            achievement,
            variance,
            row.rework if data.show_rework else None,
            row.rejection if data.show_rejection else None,
        ]


DOWNTIME_CSV_HEADER = [
    "event_id",
    "order_code",
    "batch_code",
    "category",
    "start_at",
    "end_at",
    "duration_minutes",
    "minutes_within_report_period",
]


def _downtime_csv_rows(data):
    window_start, window_end = data.filters.window()
    local = timezone.localtime
    for event in data.downtime.events:
        yield [
            event.id,
            event.order_code or "",
            event.batch_code or "",
            event.category_label,
            local(event.start).isoformat(),
            local(event.end).isoformat(),
            kpis.quantize_quantity(downtime_service.duration_minutes(event.start, event.end)),
            kpis.quantize_quantity(
                downtime_service.sum_event_minutes(
                    [(event.start, event.end)], window_start, window_end
                )
            ),
        ]


def report_export(request):
    form, filters = _filters_from_request(request, REPORT_FILTER_FIELDS)
    if filters is None:
        problems = "; ".join(
            f"{name}: {' '.join(errors)}" for name, errors in form.errors.items()
        )
        return HttpResponseBadRequest(
            f"Invalid report filters - {problems}", content_type="text/plain"
        )
    section = request.GET.get("section", "summary")
    if section not in ("summary", "downtime"):
        return HttpResponseBadRequest("Unknown export section.", content_type="text/plain")
    data = selectors.build_report(filters)
    if section == "downtime":
        header, rows = DOWNTIME_CSV_HEADER, list(_downtime_csv_rows(data))
    else:
        header, rows = SUMMARY_CSV_HEADER, list(_summary_csv_rows(data))
    logger.info("CSV export section=%s rows=%d", section, len(rows))
    content = "\ufeff" + csv_export.to_csv(header, rows)
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="tpi_{section}_report.csv"'
    return response


def health(request):
    """Startup verification: confirms the database answers a trivial query."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        logger.exception("Health check failed")
        return JsonResponse({"status": "database unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------
class OrderListView(FilteredListView):
    model = ProductionOrder
    template_name = "production/order_list.html"
    filter_fields = ("q", "status")
    page_title = "Production Orders"
    create_url_name = "production:order_create"
    create_label = "Add Order"

    def base_queryset(self):
        return ProductionOrder.objects.select_related("unit")

    def apply_filters(self, queryset, cleaned):
        if cleaned.get("q"):
            term = cleaned["q"].strip()
            queryset = queryset.filter(
                Q(order_code__icontains=term) | Q(product_reference__icontains=term)
            )
        if cleaned.get("status"):
            queryset = queryset.filter(status=cleaned["status"])
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        remaining = selectors.remaining_for_orders(context["page_obj"].object_list)
        context["rows"] = [(order, remaining[order.pk]) for order in context["page_obj"]]
        return context


class OrderDetailView(DetailView):
    model = ProductionOrder
    template_name = "production/order_detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return ProductionOrder.objects.select_related("unit")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.object
        context["page_title"] = f"Order {order.order_code}"
        context["report"] = selectors.build_report(ReportFilters(order_id=order.pk))
        context["remaining"] = selectors.remaining_for_orders([order])[order.pk]
        context["batches"] = order.batches.select_related("unit")
        return context


class OrderCreateView(FormPageMixin, SafeSaveMixin, SuccessMessageMixin, CreateView):
    model = ProductionOrder
    form_class = ProductionOrderForm
    template_name = "production/form.html"
    page_title = "Add Production Order"
    list_url_name = "production:order_list"
    detail_url_name = "production:order_detail"
    success_message = "Order %(order_code)s was created."
    prefill_fields = ()


class OrderUpdateView(FormPageMixin, SafeSaveMixin, SuccessMessageMixin, UpdateView):
    model = ProductionOrder
    form_class = ProductionOrderForm
    template_name = "production/form.html"
    page_title = "Edit Production Order"
    list_url_name = "production:order_list"
    detail_url_name = "production:order_detail"
    success_message = "Order %(order_code)s was updated."
    prefill_fields = ()


class ProtectedDeleteView(DeleteView):
    """Confirmation page (GET) and POST-only deletion with dependency protection."""

    template_name = "production/confirm_delete.html"
    list_url_name = ""
    detail_url_name = ""
    label = ""

    def get_success_url(self):
        return reverse(self.list_url_name)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Delete {self.label}"
        context["label"] = self.label
        context["blocked"] = self.object.has_dependents()
        context["cancel_url"] = reverse(self.detail_url_name, args=[self.object.pk])
        return context

    def form_valid(self, form):
        if self.object.has_dependents():
            messages.error(
                self.request,
                f"This {self.label} has linked records and cannot be deleted. "
                "Historical records are protected; change its status instead.",
            )
            return redirect(self.detail_url_name, pk=self.object.pk)
        name = str(self.object)
        try:
            with transaction.atomic():
                response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request, f"{name} is referenced by other records and cannot be deleted."
            )
            return redirect(self.detail_url_name, pk=self.object.pk)
        messages.success(self.request, f"{self.label.capitalize()} {name} was deleted.")
        return response


class OrderDeleteView(ProtectedDeleteView):
    model = ProductionOrder
    list_url_name = "production:order_list"
    detail_url_name = "production:order_detail"
    label = "order"


# --------------------------------------------------------------------------
# Batches
# --------------------------------------------------------------------------
class BatchListView(FilteredListView):
    model = ProductionBatch
    template_name = "production/batch_list.html"
    filter_fields = ("q", "order", "status")
    page_title = "Production Batches"
    create_url_name = "production:batch_create"
    create_label = "Add Batch"

    def base_queryset(self):
        return ProductionBatch.objects.select_related("order", "unit")

    def apply_filters(self, queryset, cleaned):
        if cleaned.get("q"):
            term = cleaned["q"].strip()
            queryset = queryset.filter(
                Q(batch_code__icontains=term) | Q(order__order_code__icontains=term)
            )
        if cleaned.get("order"):
            queryset = queryset.filter(order=cleaned["order"])
        if cleaned.get("status"):
            queryset = queryset.filter(status=cleaned["status"])
        return queryset


class BatchDetailView(DetailView):
    model = ProductionBatch
    template_name = "production/batch_detail.html"
    context_object_name = "batch"

    def get_queryset(self):
        return ProductionBatch.objects.select_related("order", "unit")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        batch = self.object
        context["page_title"] = f"Batch {batch.batch_code}"
        context["report"] = selectors.build_report(ReportFilters(batch_id=batch.pk))
        return context


class BatchCreateView(FormPageMixin, SafeSaveMixin, SuccessMessageMixin, CreateView):
    model = ProductionBatch
    form_class = ProductionBatchForm
    template_name = "production/form.html"
    page_title = "Add Production Batch"
    list_url_name = "production:batch_list"
    detail_url_name = "production:batch_detail"
    success_message = "Batch %(batch_code)s was created."
    prefill_fields = ("order",)


class BatchUpdateView(FormPageMixin, SafeSaveMixin, SuccessMessageMixin, UpdateView):
    model = ProductionBatch
    form_class = ProductionBatchForm
    template_name = "production/form.html"
    page_title = "Edit Production Batch"
    list_url_name = "production:batch_list"
    detail_url_name = "production:batch_detail"
    success_message = "Batch %(batch_code)s was updated."
    prefill_fields = ()


class BatchDeleteView(ProtectedDeleteView):
    model = ProductionBatch
    list_url_name = "production:batch_list"
    detail_url_name = "production:batch_detail"
    label = "batch"


# --------------------------------------------------------------------------
# Generic record detail page
# --------------------------------------------------------------------------
class RecordDetailView(DetailView):
    template_name = "production/record_detail.html"
    list_url_name = ""
    edit_url_name = ""
    title_prefix = ""

    def detail_rows(self, obj):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"{self.title_prefix} #{self.object.pk}"
        context["rows"] = self.detail_rows(self.object)
        context["list_url"] = reverse(self.list_url_name)
        context["edit_url"] = reverse(self.edit_url_name, args=[self.object.pk])
        context["extra_note"] = getattr(self, "extra_note", "")
        return context


def _order_link(obj):
    if obj.order_id:
        return (obj.order.order_code, reverse("production:order_detail", args=[obj.order_id]))
    return ("Not linked to an order", None)


def _batch_link(obj):
    if obj.batch_id:
        return (obj.batch.batch_code, reverse("production:batch_detail", args=[obj.batch_id]))
    return ("No batch", None)


def _stamp(value):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------
# Production records
# --------------------------------------------------------------------------
class ProductionListView(FilteredListView):
    model = ProductionRecord
    template_name = "production/production_list.html"
    filter_fields = ("q", "order", "batch", "start_date", "end_date")
    page_title = "Production Records"
    create_url_name = "production:production_create"
    create_label = "Add Production Record"

    def base_queryset(self):
        return ProductionRecord.objects.select_related("order", "batch", "unit")

    def apply_filters(self, queryset, cleaned):
        term = (cleaned.get("q") or "").strip()
        if term:
            condition = Q(order__order_code__icontains=term) | Q(batch__batch_code__icontains=term)
            if term.isdigit():
                condition |= Q(pk=int(term))
            queryset = queryset.filter(condition)
        queryset = selectors.apply_order_batch(queryset, cleaned)
        return selectors.apply_date_range(queryset, cleaned, "production_date")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = []
        for record in context["page_obj"]:
            rows.append(
                (
                    record,
                    kpis.target_achievement(record.actual_quantity, record.target_quantity),
                    kpis.production_variance(record.actual_quantity, record.target_quantity),
                )
            )
        context["rows"] = rows
        return context


class ProductionDetailView(RecordDetailView):
    model = ProductionRecord
    list_url_name = "production:production_list"
    edit_url_name = "production:production_update"
    title_prefix = "Production record"
    extra_note = (
        "Target achievement and variance are calculated from this record's stored "
        "target and actual output; they are not stored."
    )

    def get_queryset(self):
        return ProductionRecord.objects.select_related("order", "batch", "unit")

    def detail_rows(self, obj):
        unit = obj.unit.code
        achievement = kpis.target_achievement(obj.actual_quantity, obj.target_quantity)
        variance = kpis.production_variance(obj.actual_quantity, obj.target_quantity)
        actual_text = formatting.format_quantity(obj.actual_quantity)
        target_text = (
            f"{formatting.format_quantity(obj.target_quantity)} {unit}"
            if obj.target_quantity is not None
            else "Not recorded (no target)"
        )
        return [
            ("Production date", obj.production_date.isoformat(), None),
            ("Order", *_order_link(obj)),
            ("Batch", *_batch_link(obj)),
            ("Reporting period / shift label", obj.period_label or "Not recorded", None),
            ("Target (stored)", target_text, None),
            ("Actual output (stored)", f"{actual_text} {unit}", None),
            ("Target achievement (calculated)", formatting.kpi_percent(achievement), None),
            ("Variance (calculated)", formatting.kpi_quantity(variance, unit), None),
            ("Notes", obj.notes or "-", None),
            ("Created", _stamp(obj.created_at), None),
            ("Last updated", _stamp(obj.updated_at), None),
        ]


class ProductionCreateView(FormPageMixin, SafeSaveMixin, SuccessMessageMixin, CreateView):
    model = ProductionRecord
    form_class = ProductionRecordForm
    template_name = "production/form.html"
    page_title = "Add Production Record"
    list_url_name = "production:production_list"
    detail_url_name = "production:production_detail"
    success_message = "Production record saved."


class ProductionUpdateView(FormPageMixin, SafeSaveMixin, SuccessMessageMixin, UpdateView):
    model = ProductionRecord
    form_class = ProductionRecordForm
    template_name = "production/form.html"
    page_title = "Edit Production Record"
    list_url_name = "production:production_list"
    detail_url_name = "production:production_detail"
    success_message = "Production record updated."
    prefill_fields = ()


# --------------------------------------------------------------------------
# Downtime
# --------------------------------------------------------------------------
class OverlapWarningMixin:
    """After a successful save, warn when the event overlaps other events."""

    def form_valid(self, form):
        response = super().form_valid(form)
        saved = getattr(self, "object", None)
        if response.status_code == 302 and saved is not None and saved.pk:
            count = saved.overlapping_records().count()
            if count:
                messages.warning(
                    self.request,
                    f"This event overlaps {count} other recorded downtime event(s). "
                    "Overlapping time is counted more than once in the 'sum of event "
                    "durations' total; review it against the 'unique elapsed' total.",
                )
        return response


class DowntimeListView(FilteredListView):
    model = DowntimeRecord
    template_name = "production/downtime_list.html"
    filter_fields = ("order", "batch", "start_date", "end_date", "downtime_category")
    page_title = "Downtime"
    create_url_name = "production:downtime_create"
    create_label = "Add Downtime Record"

    def base_queryset(self):
        return DowntimeRecord.objects.select_related("order", "batch")

    def apply_filters(self, queryset, cleaned):
        queryset = selectors.apply_order_batch(queryset, cleaned)
        window_start, window_end = downtime_service.window_from_dates(
            cleaned.get("start_date"), cleaned.get("end_date"), timezone.get_current_timezone()
        )
        queryset = selectors.apply_downtime_window(queryset, window_start, window_end)
        if cleaned.get("downtime_category"):
            queryset = queryset.filter(category=cleaned["downtime_category"])
        return queryset


class DowntimeDetailView(RecordDetailView):
    model = DowntimeRecord
    list_url_name = "production:downtime_list"
    edit_url_name = "production:downtime_update"
    title_prefix = "Downtime record"
    extra_note = (
        "Duration is derived from the start and end timestamps. The model has no "
        "machine identifier, so overlapping events are flagged for review only."
    )

    def get_queryset(self):
        return DowntimeRecord.objects.select_related("order", "batch")

    def detail_rows(self, obj):
        overlaps = obj.overlapping_records().count()
        return [
            ("Event date (start, local)", _stamp(obj.start_at)[:10], None),
            ("Order", *_order_link(obj)),
            ("Batch", *_batch_link(obj)),
            ("Category", obj.get_category_display(), None),
            ("Start", _stamp(obj.start_at), None),
            ("End", _stamp(obj.end_at), None),
            ("Duration (calculated)", formatting.format_minutes(obj.duration_minutes), None),
            (
                "Overlaps with other events",
                f"Yes - {overlaps} other event(s)" if overlaps else "No overlap recorded",
                None,
            ),
            ("Notes", obj.notes or "-", None),
            ("Created", _stamp(obj.created_at), None),
            ("Last updated", _stamp(obj.updated_at), None),
        ]


class DowntimeCreateView(
    OverlapWarningMixin, FormPageMixin, SafeSaveMixin, SuccessMessageMixin, CreateView
):
    model = DowntimeRecord
    form_class = DowntimeRecordForm
    template_name = "production/form.html"
    page_title = "Add Downtime Record"
    list_url_name = "production:downtime_list"
    detail_url_name = "production:downtime_detail"
    success_message = "Downtime record saved."


class DowntimeUpdateView(
    OverlapWarningMixin, FormPageMixin, SafeSaveMixin, SuccessMessageMixin, UpdateView
):
    model = DowntimeRecord
    form_class = DowntimeRecordForm
    template_name = "production/form.html"
    page_title = "Edit Downtime Record"
    list_url_name = "production:downtime_list"
    detail_url_name = "production:downtime_detail"
    success_message = "Downtime record updated."
    prefill_fields = ()


# --------------------------------------------------------------------------
# Quality records
# --------------------------------------------------------------------------
class QualityListView(FilteredListView):
    model = QualityRecord
    template_name = "production/quality_list.html"
    filter_fields = ("order", "batch", "start_date", "end_date", "quality_type")
    page_title = "Quality Records"
    create_url_name = "production:quality_create"
    create_label = "Add Quality Record"

    def base_queryset(self):
        return QualityRecord.objects.select_related("order", "batch", "unit")

    def apply_filters(self, queryset, cleaned):
        queryset = selectors.apply_order_batch(queryset, cleaned)
        queryset = selectors.apply_date_range(queryset, cleaned, "record_date")
        if cleaned.get("quality_type"):
            queryset = queryset.filter(record_type=cleaned["quality_type"])
        return queryset


class QualityDetailView(RecordDetailView):
    model = QualityRecord
    list_url_name = "production:quality_list"
    edit_url_name = "production:quality_update"
    title_prefix = "Quality record"
    extra_note = (
        "Each record is a newly identified quantity for one event. It is never added "
        "to or subtracted from production output, and no rate is calculated because "
        "no denominator has been approved."
    )

    def get_queryset(self):
        return QualityRecord.objects.select_related("order", "batch", "unit")

    def detail_rows(self, obj):
        return [
            ("Reporting date", obj.record_date.isoformat(), None),
            ("Order", *_order_link(obj)),
            ("Batch", *_batch_link(obj)),
            ("Record type", obj.get_record_type_display(), None),
            ("Quantity", f"{formatting.format_quantity(obj.quantity)} {obj.unit.code}", None),
            ("Reason / category", obj.reason or "Not recorded", None),
            ("Notes", obj.notes or "-", None),
            ("Created", _stamp(obj.created_at), None),
            ("Last updated", _stamp(obj.updated_at), None),
        ]


class QualityCreateView(FormPageMixin, SafeSaveMixin, SuccessMessageMixin, CreateView):
    model = QualityRecord
    form_class = QualityRecordForm
    template_name = "production/form.html"
    page_title = "Add Quality Record"
    list_url_name = "production:quality_list"
    detail_url_name = "production:quality_detail"
    success_message = "Quality record saved."


class QualityUpdateView(FormPageMixin, SafeSaveMixin, SuccessMessageMixin, UpdateView):
    model = QualityRecord
    form_class = QualityRecordForm
    template_name = "production/form.html"
    page_title = "Edit Quality Record"
    list_url_name = "production:quality_list"
    detail_url_name = "production:quality_detail"
    success_message = "Quality record updated."
    prefill_fields = ()

