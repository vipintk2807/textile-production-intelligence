"""Downtime service tests using explicit, timezone-aware synthetic timestamps."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from production.services import downtime

IST = timezone(timedelta(hours=5, minutes=30))
D = Decimal


def at(day, hour, minute=0):
    return datetime(2026, 1, day, hour, minute, tzinfo=IST)


def test_duration_within_one_day():
    assert downtime.duration_minutes(at(5, 10, 0), at(5, 11, 30)) == D("90")


def test_duration_crossing_midnight_is_45_minutes():
    # Domain-rules example: 23:30 -> 00:15 next day
    assert downtime.duration_minutes(at(5, 23, 30), at(6, 0, 15)) == D("45")


def test_end_before_start_is_rejected():
    with pytest.raises(ValueError):
        downtime.duration_minutes(at(5, 11), at(5, 10))


def test_equal_start_and_end_is_rejected():
    with pytest.raises(ValueError):
        downtime.duration_minutes(at(5, 10), at(5, 10))


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError):
        downtime.duration_minutes(datetime(2026, 1, 5, 10), datetime(2026, 1, 5, 11))


def test_missing_timestamps_are_rejected():
    with pytest.raises(ValueError):
        downtime.duration_minutes(None, at(5, 11))


def test_window_from_dates_is_inclusive_of_end_date():
    start, end = downtime.window_from_dates(date(2026, 1, 5), date(2026, 1, 5), IST)
    assert start == at(5, 0)
    assert end == at(6, 0)


def test_window_open_ended():
    assert downtime.window_from_dates(None, None, IST) == (None, None)


def test_cross_midnight_event_split_between_days_not_double_counted():
    events = [(at(5, 23, 30), at(6, 0, 15))]
    day5 = downtime.window_from_dates(date(2026, 1, 5), date(2026, 1, 5), IST)
    day6 = downtime.window_from_dates(date(2026, 1, 6), date(2026, 1, 6), IST)
    assert downtime.sum_event_minutes(events, *day5) == D("30")
    assert downtime.sum_event_minutes(events, *day6) == D("15")
    assert downtime.sum_event_minutes(events) == D("45")  # whole event, no window


def test_event_outside_window_contributes_nothing():
    events = [(at(5, 10), at(5, 11))]
    window = downtime.window_from_dates(date(2026, 1, 6), date(2026, 1, 6), IST)
    assert downtime.sum_event_minutes(events, *window) == D("0")


def test_event_ending_exactly_at_window_start_is_excluded():
    events = [(at(5, 22), at(6, 0))]
    window = downtime.window_from_dates(date(2026, 1, 6), date(2026, 1, 6), IST)
    assert downtime.sum_event_minutes(events, *window) == D("0")


def test_overlapping_events_sum_vs_unique():
    events = [(at(6, 10, 0), at(6, 11, 0)), (at(6, 10, 30), at(6, 11, 30))]
    assert downtime.sum_event_minutes(events) == D("120")  # double counts 30 min
    assert downtime.unique_elapsed_minutes(events) == D("90")


def test_unique_elapsed_with_nested_and_disjoint_events():
    events = [
        (at(6, 8, 0), at(6, 12, 0)),  # 240
        (at(6, 9, 0), at(6, 10, 0)),  # nested -> adds nothing
        (at(6, 14, 0), at(6, 14, 30)),  # disjoint 30
    ]
    assert downtime.unique_elapsed_minutes(events) == D("270")


def test_unique_elapsed_touching_events_are_merged_without_gap_or_overlap():
    events = [(at(6, 8, 0), at(6, 9, 0)), (at(6, 9, 0), at(6, 10, 0))]
    assert downtime.unique_elapsed_minutes(events) == D("120")


def test_find_overlaps_detects_real_overlap_only():
    events = [
        (at(6, 10, 0), at(6, 11, 0)),
        (at(6, 10, 30), at(6, 11, 30)),
        (at(6, 11, 30), at(6, 12, 0)),  # touches second, no overlap
        (at(6, 15, 0), at(6, 16, 0)),
    ]
    assert downtime.find_overlaps(events) == [(0, 1)]


def test_find_overlaps_none():
    assert downtime.find_overlaps([(at(6, 8), at(6, 9)), (at(6, 9), at(6, 10))]) == []


def test_find_overlaps_empty():
    assert downtime.find_overlaps([]) == []


def test_clip_interval_none_when_disjoint():
    assert downtime.clip_interval(at(5, 8), at(5, 9), at(6, 0), at(7, 0)) is None


def test_unique_elapsed_respects_window_clipping():
    events = [(at(5, 23, 0), at(6, 1, 0)), (at(6, 0, 30), at(6, 2, 0))]
    window = downtime.window_from_dates(date(2026, 1, 6), date(2026, 1, 6), IST)
    # inside Jan 6: 00:00-01:00 and 00:30-02:00 -> union 00:00-02:00 = 120
    assert downtime.unique_elapsed_minutes(events, *window) == D("120")
