"""Django admin (optional; requires `createsuperuser`). Deletion of protected
records is still blocked by PROTECT foreign keys."""

from django.contrib import admin

from .models import (
    DowntimeRecord,
    ProductionBatch,
    ProductionOrder,
    ProductionRecord,
    QualityRecord,
    UnitOfMeasure,
)


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "dimension", "is_active")
    list_filter = ("dimension", "is_active")


@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    list_display = ("order_code", "product_reference", "order_quantity", "unit", "status")
    search_fields = ("order_code", "product_reference")
    list_filter = ("status",)


@admin.register(ProductionBatch)
class ProductionBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_code", "order", "planned_quantity", "unit", "status")
    search_fields = ("batch_code", "order__order_code")


@admin.register(ProductionRecord)
class ProductionRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "production_date", "order", "batch", "target_quantity", "actual_quantity")
    list_filter = ("production_date",)


@admin.register(DowntimeRecord)
class DowntimeRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "batch", "category", "start_at", "end_at")
    list_filter = ("category",)


@admin.register(QualityRecord)
class QualityRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "record_date", "order", "batch", "record_type", "quantity", "unit")
    list_filter = ("record_type",)
