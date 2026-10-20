"""Initial schema (hand-written to match production/models.py).

If ``python manage.py makemigrations --check --dry-run`` ever reports changes
for the production app, regenerate with ``python manage.py makemigrations``.
"""

import django.db.models.deletion
from django.db import migrations, models

STATUS_CHOICES = [
    ("PLANNED", "Planned"),
    ("IN_PROGRESS", "In progress"),
    ("COMPLETED", "Completed"),
    ("CANCELLED", "Cancelled"),
]


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="UnitOfMeasure",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.CharField(max_length=16, unique=True)),
                ("name", models.CharField(max_length=64)),
                (
                    "dimension",
                    models.CharField(
                        choices=[("MASS", "Mass"), ("LENGTH", "Length"), ("COUNT", "Count")],
                        max_length=16,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="ProductionOrder",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("order_code", models.CharField(max_length=40, unique=True)),
                ("product_reference", models.CharField(max_length=120)),
                ("order_quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("planned_start_date", models.DateField(blank=True, null=True)),
                ("planned_end_date", models.DateField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(choices=STATUS_CHOICES, default="PLANNED", max_length=20),
                ),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="production.unitofmeasure",
                    ),
                ),
            ],
            options={
                "ordering": ["order_code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(order_quantity__gt=0), name="order_quantity_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(planned_start_date__isnull=True)
                        | models.Q(planned_end_date__isnull=True)
                        | models.Q(planned_end_date__gte=models.F("planned_start_date")),
                        name="order_planned_dates_ordered",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ProductionBatch",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("batch_code", models.CharField(max_length=40, unique=True)),
                (
                    "planned_quantity",
                    models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True),
                ),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(choices=STATUS_CHOICES, default="PLANNED", max_length=20),
                ),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="batches",
                        to="production.productionorder",
                    ),
                ),
                (
                    "unit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="production.unitofmeasure",
                    ),
                ),
            ],
            options={
                "ordering": ["batch_code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(planned_quantity__isnull=True)
                        | models.Q(planned_quantity__gt=0),
                        name="batch_quantity_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(start_date__isnull=True)
                        | models.Q(end_date__isnull=True)
                        | models.Q(end_date__gte=models.F("start_date")),
                        name="batch_dates_ordered",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ProductionRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("production_date", models.DateField()),
                ("period_label", models.CharField(blank=True, max_length=60)),
                (
                    "target_quantity",
                    models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True),
                ),
                ("actual_quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "batch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="production_records",
                        to="production.productionbatch",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="production_records",
                        to="production.productionorder",
                    ),
                ),
                (
                    "unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="production.unitofmeasure",
                    ),
                ),
            ],
            options={
                "ordering": ["-production_date", "-id"],
                "indexes": [
                    models.Index(fields=["production_date"], name="prodrec_date_idx"),
                    models.Index(
                        fields=["order", "production_date"], name="prodrec_order_date_idx"
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(actual_quantity__gte=0),
                        name="prodrec_actual_nonnegative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(target_quantity__isnull=True)
                        | models.Q(target_quantity__gte=0),
                        name="prodrec_target_nonnegative",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DowntimeRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("MECHANICAL", "Mechanical"),
                            ("ELECTRICAL_POWER", "Electrical / power"),
                            ("MATERIAL", "Material unavailable"),
                            ("SETUP", "Setup / changeover"),
                            ("OTHER", "Other"),
                        ],
                        max_length=20,
                    ),
                ),
                ("start_at", models.DateTimeField()),
                ("end_at", models.DateTimeField()),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "batch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="downtime_records",
                        to="production.productionbatch",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="downtime_records",
                        to="production.productionorder",
                    ),
                ),
            ],
            options={
                "ordering": ["-start_at", "-id"],
                "indexes": [models.Index(fields=["start_at"], name="downtime_start_idx")],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(end_at__gt=models.F("start_at")),
                        name="downtime_end_after_start",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="QualityRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("record_date", models.DateField()),
                (
                    "record_type",
                    models.CharField(
                        choices=[("REWORK", "Rework"), ("REJECTION", "Rejection")],
                        max_length=12,
                    ),
                ),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("reason", models.CharField(blank=True, max_length=200)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "batch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="quality_records",
                        to="production.productionbatch",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="quality_records",
                        to="production.productionorder",
                    ),
                ),
                (
                    "unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="production.unitofmeasure",
                    ),
                ),
            ],
            options={
                "ordering": ["-record_date", "-id"],
                "indexes": [models.Index(fields=["record_date"], name="quality_date_idx")],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(quantity__gte=0), name="quality_quantity_nonnegative"
                    ),
                ],
            },
        ),
    ]
