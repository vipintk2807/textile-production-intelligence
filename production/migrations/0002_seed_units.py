"""Seed the small initial unit catalogue.

The catalogue is an assumption (see docs/DOMAIN_RULES.md): it can be extended
from the Django admin site. No conversion between units is ever performed.
"""

from django.db import migrations

INITIAL_UNITS = [
    ("kg", "Kilogram", "MASS"),
    ("m", "Metre", "LENGTH"),
    ("pcs", "Pieces", "COUNT"),
]


def seed_units(apps, schema_editor):
    UnitOfMeasure = apps.get_model("production", "UnitOfMeasure")
    for code, name, dimension in INITIAL_UNITS:
        UnitOfMeasure.objects.get_or_create(
            code=code,
            defaults={"name": name, "dimension": dimension, "is_active": True},
        )


class Migration(migrations.Migration):
    dependencies = [("production", "0001_initial")]

    operations = [migrations.RunPython(seed_units, migrations.RunPython.noop)]
