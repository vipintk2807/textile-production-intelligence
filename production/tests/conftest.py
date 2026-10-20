"""Shared synthetic test fixtures. All records here are SYNTHETIC test data."""

from datetime import date
from decimal import Decimal

import pytest

from production.models import ProductionBatch, ProductionOrder, UnitOfMeasure


def _unit(code, name, dimension):
    return UnitOfMeasure.objects.get_or_create(
        code=code, defaults={"name": name, "dimension": dimension}
    )[0]


@pytest.fixture
def kg(db):
    return _unit("kg", "Kilogram", "MASS")


@pytest.fixture
def pcs(db):
    return _unit("pcs", "Pieces", "COUNT")


@pytest.fixture
def metre(db):
    return _unit("m", "Metre", "LENGTH")


@pytest.fixture
def order(db, kg):
    return ProductionOrder.objects.create(
        order_code="T-ORD-1",
        product_reference="TEST-STYLE-1",
        order_quantity=Decimal("100"),
        unit=kg,
        planned_start_date=date(2026, 1, 1),
        planned_end_date=date(2026, 1, 31),
    )


@pytest.fixture
def other_order(db, kg):
    return ProductionOrder.objects.create(
        order_code="T-ORD-2",
        product_reference="TEST-STYLE-2",
        order_quantity=Decimal("50"),
        unit=kg,
    )


@pytest.fixture
def batch(db, order, kg):
    return ProductionBatch.objects.create(
        batch_code="T-BAT-1", order=order, planned_quantity=Decimal("40"), unit=kg
    )


@pytest.fixture
def batch2(db, order, kg):
    return ProductionBatch.objects.create(batch_code="T-BAT-2", order=order)


@pytest.fixture
def other_batch(db, other_order):
    return ProductionBatch.objects.create(batch_code="T-BAT-3", order=other_order)
