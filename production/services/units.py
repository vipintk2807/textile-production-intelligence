"""Unit compatibility rules.

The initial release performs NO unit conversion. Two quantities are compatible
only when they carry the same, known unit code.
"""


def units_compatible(unit_a, unit_b):
    """Return True only if both unit codes are known and identical."""
    if not unit_a or not unit_b:
        return False
    return str(unit_a).strip().lower() == str(unit_b).strip().lower()
