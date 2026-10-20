from django.urls import path

from . import views

app_name = "production"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("health/", views.health, name="health"),
    # Orders
    path("orders/", views.OrderListView.as_view(), name="order_list"),
    path("orders/new/", views.OrderCreateView.as_view(), name="order_create"),
    path("orders/<int:pk>/", views.OrderDetailView.as_view(), name="order_detail"),
    path("orders/<int:pk>/edit/", views.OrderUpdateView.as_view(), name="order_update"),
    path("orders/<int:pk>/delete/", views.OrderDeleteView.as_view(), name="order_delete"),
    # Batches
    path("batches/", views.BatchListView.as_view(), name="batch_list"),
    path("batches/new/", views.BatchCreateView.as_view(), name="batch_create"),
    path("batches/<int:pk>/", views.BatchDetailView.as_view(), name="batch_detail"),
    path("batches/<int:pk>/edit/", views.BatchUpdateView.as_view(), name="batch_update"),
    path("batches/<int:pk>/delete/", views.BatchDeleteView.as_view(), name="batch_delete"),
    # Production records
    path("production/", views.ProductionListView.as_view(), name="production_list"),
    path("production/new/", views.ProductionCreateView.as_view(), name="production_create"),
    path("production/<int:pk>/", views.ProductionDetailView.as_view(), name="production_detail"),
    path(
        "production/<int:pk>/edit/",
        views.ProductionUpdateView.as_view(),
        name="production_update",
    ),
    # Downtime
    path("downtime/", views.DowntimeListView.as_view(), name="downtime_list"),
    path("downtime/new/", views.DowntimeCreateView.as_view(), name="downtime_create"),
    path("downtime/<int:pk>/", views.DowntimeDetailView.as_view(), name="downtime_detail"),
    path("downtime/<int:pk>/edit/", views.DowntimeUpdateView.as_view(), name="downtime_update"),
    # Quality
    path("quality/", views.QualityListView.as_view(), name="quality_list"),
    path("quality/new/", views.QualityCreateView.as_view(), name="quality_create"),
    path("quality/<int:pk>/", views.QualityDetailView.as_view(), name="quality_detail"),
    path("quality/<int:pk>/edit/", views.QualityUpdateView.as_view(), name="quality_update"),
    # Reports
    path("reports/", views.report, name="report"),
    path("reports/export.csv", views.report_export, name="report_export"),
]
