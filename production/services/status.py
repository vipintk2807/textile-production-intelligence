"""Status values and permitted transitions for orders and batches.

These are an initial, deliberately small set. They are application rules, not
a claim about any factory's workflow.
"""

PLANNED = "PLANNED"
IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"
CANCELLED = "CANCELLED"

ALL_STATUSES = (PLANNED, IN_PROGRESS, COMPLETED, CANCELLED)

ALLOWED_TRANSITIONS = {
    PLANNED: {IN_PROGRESS, CANCELLED},
    IN_PROGRESS: {COMPLETED, CANCELLED, PLANNED},
    COMPLETED: {IN_PROGRESS},
    CANCELLED: {PLANNED},
}


def allowed_next(status):
    """Statuses reachable from ``status`` (excluding staying in place)."""
    return ALLOWED_TRANSITIONS.get(status, set())


def can_transition(old_status, new_status):
    """True if the status is unchanged or the move is permitted."""
    if old_status == new_status:
        return True
    return new_status in allowed_next(old_status)
