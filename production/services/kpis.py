"""Central KPI calculation engine.

Every dashboard card, detail page, report and CSV export obtains its numbers
from these functions. Templates and views contain no KPI formulas.

Conventions
-----------
* All arithmetic uses ``decimal.Decimal`` on the stored, unrounded quantities.
* Rounding happens only for display/export via :func:`quantize_percent` and
  :func:`quantize_quantity`; rounded values are never fed back into
  calculations.
* A calculation that cannot be performed reliably returns a
  :class:`KpiResult` with status ``UNAVAILABLE`` and a human-readable reason.
  It never returns an arbitrary zero.
* No unit conversion is performed. Quantities are compared only when their
  unit codes are identical.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum

from .units import units_compatible

PERCENT_PLACES = Decimal("0.01")
QUANTITY_PLACES = Decimal("0.001")
HUNDRED = Decimal("100")


class Status(str, Enum):
    OK = "ok"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class KpiResult:
    """A calculated value or an explicit 'unavailable' state with a reason."""

    value: Decimal | None
    status: Status
    reason: str = ""

    @property
    def ok(self):
        return self.status is Status.OK

    @classmethod
    def available(cls, value):
        return cls(value=value, status=Status.OK)

    @classmethod
    def unavailable(cls, reason):
        return cls(value=None, status=Status.UNAVAILABLE, reason=reason)


def to_decimal(value):
    """Convert input to a finite Decimal, or return None if impossible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, int):
            result = Decimal(value)
        else:
            result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite():
        return None
    return result


def quantize_percent(value):
    """Round a percentage for display/export only (2 decimal places)."""
    return value.quantize(PERCENT_PLACES, rounding=ROUND_HALF_UP)


def quantize_quantity(value):
    """Round a quantity to the storage precision (3 decimal places)."""
    return value.quantize(QUANTITY_PLACES, rounding=ROUND_HALF_UP)


def _check_pair(actual, target, actual_unit, target_unit):
    """Validate a target/actual pair. Returns (actual, target, error_reason)."""
    if target is None:
        return None, None, "The target is missing."
    if actual is None:
        return None, None, "The actual output is missing."
    actual_d = to_decimal(actual)
    target_d = to_decimal(target)
    if actual_d is None or target_d is None:
        return None, None, "A quantity is not a valid number."
    if actual_d < 0 or target_d < 0:
        return None, None, "Negative quantities are invalid."
    if (actual_unit is not None or target_unit is not None) and not units_compatible(
        actual_unit, target_unit
    ):
        return None, None, "Target and actual output use incompatible or unknown units."
    return actual_d, target_d, ""


def target_achievement(actual, target, actual_unit=None, target_unit=None):
    """Target Achievement (%) = actual / target x 100, for a positive target."""
    actual_d, target_d, error = _check_pair(actual, target, actual_unit, target_unit)
    if error:
        return KpiResult.unavailable(error)
    if target_d == 0:
        return KpiResult.unavailable("The target is zero, so a percentage is undefined.")
    return KpiResult.available((actual_d * HUNDRED) / target_d)


def production_variance(actual, target, actual_unit=None, target_unit=None):
    """Variance = actual - target (same unit). A zero target is allowed."""
    actual_d, target_d, error = _check_pair(actual, target, actual_unit, target_unit)
    if error:
        return KpiResult.unavailable(error)
    return KpiResult.available(actual_d - target_d)


@dataclass(frozen=True)
class ProductionFigure:
    """One production record's quantities (target may be missing)."""

    actual: Decimal | None
    target: Decimal | None
    unit: str | None


@dataclass(frozen=True)
class ProductionTotals:
    """Aggregate quantities for ONE unit.

    ``actual_total`` covers every record. Achievement and variance use only
    records that carry a target (``actual_with_target`` vs ``target_total``) so
    that output without a target never inflates the percentage.
    """

    unit: str | None
    records: int = 0
    actual_total: Decimal = Decimal("0")
    records_with_target: int = 0
    target_total: Decimal | None = None
    actual_with_target: Decimal = Decimal("0")
    records_missing_actual: int = 0

    @property
    def records_without_target(self):
        return self.records - self.records_with_target - self.records_missing_actual


@dataclass(frozen=True)
class ProductionSummary:
    totals: ProductionTotals
    achievement: KpiResult
    variance: KpiResult
    notes: tuple = field(default_factory=tuple)


def evaluate_production(totals):
    """Compute achievement and variance from aggregate totals (single unit)."""
    notes = []
    if totals.records_without_target:
        notes.append(
            f"{totals.records_without_target} record(s) have no target and are "
            "excluded from achievement and variance."
        )
    if totals.records_with_target == 0 or totals.target_total is None:
        reason = "No records with a target are in scope."
        return ProductionSummary(
            totals,
            KpiResult.unavailable(reason),
            KpiResult.unavailable(reason),
            tuple(notes),
        )
    return ProductionSummary(
        totals,
        target_achievement(totals.actual_with_target, totals.target_total),
        production_variance(totals.actual_with_target, totals.target_total),
        tuple(notes),
    )


def summarize_figures(figures):
    """Group in-memory figures by unit and evaluate each group separately.

    Different units are never summed together. Returns ``{unit: summary}``.
    """
    grouped = {}
    for figure in figures:
        grouped.setdefault(figure.unit, []).append(figure)
    summaries = {}
    for unit, items in grouped.items():
        records = len(items)
        actual_total = Decimal("0")
        missing_actual = 0
        with_target = 0
        target_total = None
        actual_with_target = Decimal("0")
        for item in items:
            actual = to_decimal(item.actual)
            if actual is None:
                missing_actual += 1
                continue
            actual_total += actual
            target = to_decimal(item.target)
            if target is not None:
                with_target += 1
                target_total = (target_total or Decimal("0")) + target
                actual_with_target += actual
        totals = ProductionTotals(
            unit=unit,
            records=records,
            actual_total=actual_total,
            records_with_target=with_target,
            target_total=target_total,
            actual_with_target=actual_with_target,
            records_missing_actual=missing_actual,
        )
        summaries[unit] = evaluate_production(totals)
    return summaries


@dataclass(frozen=True)
class RemainingResult:
    """Remaining order quantity with an over-production flag.

    ASSUMPTION (documented in docs/DOMAIN_RULES.md): "completed quantity" is the
    sum of recorded actual output, in the order's own unit. This is a
    provisional definition, not an authoritative textile-industry measure.
    """

    result: KpiResult
    completed: Decimal | None = None
    over_produced: bool = False
    excluded_other_unit_records: int = 0


def remaining_quantity(order_quantity, order_unit, outputs):
    """Order quantity minus recorded output in the order's unit.

    ``outputs`` is an iterable of ``(unit_code, actual_quantity)`` or
    ``(unit_code, actual_quantity, record_count)`` where the optional third
    element says how many records a pre-aggregated entry represents. Outputs in
    other units are excluded (and counted), never silently added. A negative
    result is preserved and flagged, never clamped to zero.
    """
    quantity = to_decimal(order_quantity)
    if quantity is None or quantity <= 0 or not order_unit:
        return RemainingResult(
            KpiResult.unavailable("The order quantity or unit is missing or invalid.")
        )
    completed = Decimal("0")
    excluded = 0
    for entry in outputs:
        unit_code, actual = entry[0], entry[1]
        record_count = entry[2] if len(entry) > 2 else 1
        actual_d = to_decimal(actual)
        if actual_d is None or actual_d < 0:
            return RemainingResult(
                KpiResult.unavailable("A recorded output quantity is invalid."),
                excluded_other_unit_records=excluded,
            )
        if units_compatible(unit_code, order_unit):
            completed += actual_d
        else:
            excluded += record_count
    remaining = quantity - completed
    return RemainingResult(
        KpiResult.available(remaining),
        completed=completed,
        over_produced=remaining < 0,
        excluded_other_unit_records=excluded,
    )
