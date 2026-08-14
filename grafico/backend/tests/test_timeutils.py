from src.timeutils import minutes_to_time_str, time_str_to_minutes


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
