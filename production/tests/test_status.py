"""Status transition rule tests."""

import pytest

from production.services import integrity, status, units


def test_unchanged_status_is_allowed():
    for value in status.ALL_STATUSES:
        assert status.can_transition(value, value)


@pytest.mark.parametrize(
    "old,new,allowed",
    [
        ("PLANNED", "IN_PROGRESS", True),
        ("PLANNED", "COMPLETED", False),
        ("IN_PROGRESS", "COMPLETED", True),
        ("COMPLETED", "PLANNED", False),
        ("COMPLETED", "IN_PROGRESS", True),
        ("CANCELLED", "COMPLETED", False),
        ("PLANNED", "NOT_A_STATUS", False),
    ],
)
def test_transitions(old, new, allowed):
    assert status.can_transition(old, new) is allowed


def test_batch_must_match_order():
    assert integrity.batch_matches_order(1, 1)
    assert not integrity.batch_matches_order(2, 1)
    assert not integrity.batch_matches_order(None, 1)


def test_units_compatible_rules():
    assert units.units_compatible("kg", "kg")
    assert units.units_compatible("kg", "KG")
    assert not units.units_compatible("kg", "m")
    assert not units.units_compatible("kg", None)
    assert not units.units_compatible("", "")
