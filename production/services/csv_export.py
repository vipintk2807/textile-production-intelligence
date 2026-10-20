"""CSV helpers with spreadsheet formula-injection protection."""

import csv
import io
from decimal import Decimal

# A cell starting with any of these (after leading whitespace/control chars are
# skipped) can be interpreted as a formula by spreadsheet software.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def sanitize_cell(value):
    """Return a CSV-safe cell.

    Only free text (``str``) is neutralised, by prefixing a single quote.
    Numbers (Decimal/int) are written as-is so that negative values such as a
    variance of -15 stay machine-readable.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    stripped = text.lstrip(" \t\r\n\x00\x0b\x0c")
    if stripped.startswith(_FORMULA_PREFIXES) or text.startswith(("\t", "\r")):
        return "'" + text
    return text


def to_csv(header, rows):
    """Serialise ``header`` and ``rows`` to a CSV string using the csv module."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([sanitize_cell(cell) for cell in header])
    for row in rows:
        writer.writerow([sanitize_cell(cell) for cell in row])
    return buffer.getvalue()
