"""Cross-record integrity rules that do not depend on Django."""


def batch_matches_order(batch_order_id, order_id):
    """A batch may only be linked to its own parent order."""
    return batch_order_id is not None and batch_order_id == order_id
