"""Rework / rejection totals and the (currently undefined) quality rates.

Event-level records: every quality record is a newly identified quantity for
one event; totals are plain sums per unit and per type. Rework and rejection
are never added to, or subtracted from, production output.

Rework and rejection RATES need an approved denominator. None has been
approved (see docs/DOMAIN_RULES.md), so the application always calls
:func:`quality_rate` with ``denominator=None`` and displays "Not available".
The function exists so that a future approved denominator can be supplied in
one place, with the missing/zero/incompatible handling already tested.
"""

from decimal import Decimal

from .kpis import HUNDRED, KpiResult, to_decimal
from .units import units_compatible

REWORK = "REWORK"
REJECTION = "REJECTION"


def quality_rate(numerator, denominator, numerator_unit=None, denominator_unit=None):
    """Rate (%) = numerator / denominator x 100, only for a valid denominator."""
    num = to_decimal(numerator)
    if num is None:
        return KpiResult.unavailable("No quality quantity is recorded for this scope.")
    if num < 0:
        return KpiResult.unavailable("The quality quantity is invalid.")
    if denominator is None:
        return KpiResult.unavailable(
            "No approved denominator is defined for this rate, so it cannot be calculated."
        )
    den = to_decimal(denominator)
    if den is None or den < 0:
        return KpiResult.unavailable("The denominator is not a valid quantity.")
    if den == 0:
        return KpiResult.unavailable("The denominator is zero, so the rate is undefined.")
    if (numerator_unit is not None or denominator_unit is not None) and not units_compatible(
        numerator_unit, denominator_unit
    ):
        return KpiResult.unavailable("Numerator and denominator use incompatible units.")
    return KpiResult.available((num * HUNDRED) / den)


def total_by_type(records):
    """Sum ``(record_type, unit, quantity)`` rows into ``{(type, unit): total}``.

    Different units are kept apart; no total mixes units.
    """
    totals = {}
    for record_type, unit, quantity in records:
        value = to_decimal(quantity)
        if value is None or value < 0:
            raise ValueError("Quality quantities must be valid, non-negative numbers.")
        key = (record_type, unit)
        totals[key] = totals.get(key, Decimal("0")) + value
    return totals
