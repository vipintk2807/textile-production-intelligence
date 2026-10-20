"""Display formatting helpers (presentation only; never used in calculations)."""

from decimal import Decimal

from .services.kpis import quantize_percent

NOT_AVAILABLE = "Not available"
NOT_RECORDED = "Not recorded"


def format_quantity(value):
    """Format a quantity with thousands separators, trimming trailing zeros.

    ``None`` means 'not recorded'; a genuine zero is shown as ``0``.
    """
    if value is None:
        return NOT_RECORDED
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(number.normalize(), ",f")


def format_percent(value):
    """Format a percentage to 2 decimal places (display rounding only)."""
    if value is None:
        return NOT_AVAILABLE
    return format(quantize_percent(value), ",f") + "%"


def format_minutes(value):
    """Format minutes, trimming trailing zeros."""
    if value is None:
        return NOT_AVAILABLE
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    rounded = number.quantize(Decimal("0.01"))
    return format(rounded.normalize(), ",f") + " min"


def kpi_percent(result):
    return format_percent(result.value) if result is not None and result.ok else NOT_AVAILABLE


def kpi_quantity(result, unit=""):
    if result is None or not result.ok:
        return NOT_AVAILABLE
    text = format_quantity(result.value)
    return f"{text} {unit}".strip()
