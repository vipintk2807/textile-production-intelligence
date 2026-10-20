"""Downtime duration, reporting-window attribution and overlap handling.

Documented rules
----------------
* Start and end timestamps are authoritative; both are required and must be
  timezone-aware. The end must be strictly after the start.
* Duration (minutes) = (end - start) in seconds / 60, using real timestamps, so
  events crossing midnight are handled correctly.
* Reporting-period attribution: an event contributes only the portion that
  overlaps the selected window (clipping). An event spanning two days is
  therefore never counted in full in both days.
* Two different totals are provided and must always be labelled:
  - "sum of recorded event durations" (overlapping time counts more than once)
  - "unique elapsed downtime" (union of the intervals; clock time counted once)
* The data model has no machine identifier, so overlapping events may or may
  not describe the same machine. Overlaps are therefore flagged, not blocked.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

SECONDS_PER_MINUTE = Decimal("60")


def _require_aware(value, name):
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime.")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware.")


def validate_interval(start, end):
    """Raise ValueError unless ``end`` is strictly after ``start``."""
    _require_aware(start, "start")
    _require_aware(end, "end")
    if end <= start:
        raise ValueError("The end time must be after the start time.")


def duration_minutes(start, end):
    """Elapsed minutes between two aware timestamps, as a Decimal."""
    validate_interval(start, end)
    return Decimal(str((end - start).total_seconds())) / SECONDS_PER_MINUTE


def window_from_dates(start_date, end_date, tzinfo):
    """Convert inclusive local dates to a half-open aware datetime window.

    ``start_date`` 00:00 (inclusive) to the day after ``end_date`` 00:00
    (exclusive). Either bound may be None for an open-ended window.
    """
    window_start = None
    window_end = None
    if start_date is not None:
        window_start = datetime.combine(start_date, time.min, tzinfo=tzinfo)
    if end_date is not None:
        window_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tzinfo)
    return window_start, window_end


def clip_interval(start, end, window_start=None, window_end=None):
    """Portion of [start, end) inside the window, or None if no overlap."""
    clipped_start = start if window_start is None else max(start, window_start)
    clipped_end = end if window_end is None else min(end, window_end)
    if clipped_end <= clipped_start:
        return None
    return clipped_start, clipped_end


def _clipped(intervals, window_start, window_end):
    for start, end in intervals:
        validate_interval(start, end)
        clipped = clip_interval(start, end, window_start, window_end)
        if clipped is not None:
            yield clipped


def sum_event_minutes(intervals, window_start=None, window_end=None):
    """Sum of (clipped) event durations. Overlaps are counted more than once."""
    total = Decimal("0")
    for start, end in _clipped(intervals, window_start, window_end):
        total += duration_minutes(start, end)
    return total


def unique_elapsed_minutes(intervals, window_start=None, window_end=None):
    """Minutes covered by the union of the (clipped) intervals."""
    merged = []
    for start, end in sorted(_clipped(intervals, window_start, window_end)):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return sum((duration_minutes(s, e) for s, e in merged), Decimal("0"))


def find_overlaps(intervals):
    """Index pairs ``(i, j)`` of intervals that genuinely overlap.

    Intervals that merely touch (one ends exactly when the next starts) do not
    overlap.
    """
    indexed = sorted(enumerate(intervals), key=lambda item: item[1][0])
    pairs = []
    for position, (i, (start_i, end_i)) in enumerate(indexed):
        for j, (start_j, end_j) in indexed[position + 1 :]:
            if start_j >= end_i:
                break
            if start_j < end_i and start_i < end_j:
                pairs.append((min(i, j), max(i, j)))
    return sorted(pairs)
