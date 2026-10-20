"""Template filters. They only format values calculated elsewhere."""

from django import template

from .. import formatting

register = template.Library()


@register.filter
def qty(value):
    return formatting.format_quantity(value)


@register.filter
def pct(value):
    return formatting.format_percent(value)


@register.filter
def minutes(value):
    return formatting.format_minutes(value)


@register.filter
def kpi_pct(result):
    return formatting.kpi_percent(result)


@register.filter
def kpi_qty(result):
    return formatting.kpi_quantity(result)


@register.filter
def kpi_reason(result):
    if result is None or result.ok:
        return ""
    return result.reason


@register.filter
def kpi_ok(result):
    return bool(result is not None and result.ok)


@register.filter
def negative(value):
    """True when a Decimal is below zero (used to add a textual flag)."""
    return value is not None and value < 0


@register.filter
def qty_or(value, fallback):
    """Quantity, or a custom text when no value exists (None != zero)."""
    if value is None:
        return fallback
    return formatting.format_quantity(value)


@register.filter
def kpi_na(result):
    """True when a KPI result is unavailable."""
    return result is None or not result.ok
