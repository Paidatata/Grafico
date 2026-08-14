from datetime import datetime

from src.timeutils import (
    SERVICE_DAY_START_HOUR,
    effective_reset_date,
    minutes_to_time_str,
    time_str_to_minutes,
    time_str_to_service_minutes,
)


def test_time_str_to_minutes():
    assert time_str_to_minutes("00:00:00") == 0
    assert time_str_to_minutes("05:10:00") == 310
    assert time_str_to_minutes("05:10:30") == 310.5


def test_minutes_to_time_str():
    assert minutes_to_time_str(0) == "00:00:00"
    assert minutes_to_time_str(310) == "05:10:00"
    assert minutes_to_time_str(310.5) == "05:10:30"


def test_minutes_to_time_str_wraps_past_midnight():
    assert minutes_to_time_str(24 * 60) == "00:00:00"


def test_round_trip_preserves_value():
    for original in ["04:36:00", "23:59:59", "12:00:30"]:
        assert minutes_to_time_str(time_str_to_minutes(original)) == original


def test_service_minutes_start_at_the_service_day_boundary():
    assert SERVICE_DAY_START_HOUR == 4
    assert time_str_to_service_minutes("04:00:00") == 0
    assert time_str_to_service_minutes("05:00:00") == 60


def test_service_minutes_keep_midnight_crossings_monotonic():
    """23:55 and 00:10 belong to the same service day; 00:10 must sort *after* 23:55."""
    late = time_str_to_service_minutes("23:55:00")
    after_midnight = time_str_to_service_minutes("00:10:00")
    assert after_midnight > late
    assert after_midnight - late == 15

    # Raw time-of-day minutes get this backwards, which is the bug being fixed.
    assert time_str_to_minutes("00:10:00") < time_str_to_minutes("23:55:00")


def test_service_minutes_wrap_range():
    assert time_str_to_service_minutes("03:59:00") == 24 * 60 - 1  # last minute of the service day


def test_effective_reset_date_before_3am_belongs_to_previous_day():
    assert effective_reset_date(datetime(2026, 8, 14, 2, 0, 0)) == "2026-08-13"
    assert effective_reset_date(datetime(2026, 8, 14, 0, 30, 0)) == "2026-08-13"


def test_effective_reset_date_from_3am_belongs_to_current_day():
    assert effective_reset_date(datetime(2026, 8, 14, 3, 0, 0)) == "2026-08-14"
    assert effective_reset_date(datetime(2026, 8, 14, 4, 0, 0)) == "2026-08-14"
    assert effective_reset_date(datetime(2026, 8, 14, 23, 59, 0)) == "2026-08-14"
