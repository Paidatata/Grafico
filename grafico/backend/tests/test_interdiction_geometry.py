from src.interdiction import crossing_window, sequence_crossings


def test_crossing_window_finds_the_segment_that_enters_the_band():
    stops = [(1000.0, "10:00:00", "10:00:00"), (2000.0, "10:20:00", "10:20:00")]
    result = crossing_window(stops, y_top=1200.0, y_bottom=1400.0)
    assert result is not None
    entry, exit_, idx = result
    assert round(entry) == 364
    assert round(exit_) == 368
    assert idx == 1


def test_crossing_window_returns_none_when_band_is_never_touched():
    stops = [(1000.0, "10:00:00", "10:00:00"), (2000.0, "10:20:00", "10:20:00")]
    assert crossing_window(stops, y_top=3000.0, y_bottom=3500.0) is None


def test_crossing_window_handles_descending_direction():
    stops = [(2000.0, "10:00:00", "10:00:00"), (1000.0, "10:20:00", "10:20:00")]
    result = crossing_window(stops, y_top=1200.0, y_bottom=1400.0)
    assert result is not None
    entry, exit_, idx = result
    assert entry < exit_


def test_sequence_crossings_holds_opposite_direction_when_it_would_arrive_early():
    candidates = [
        ("A", 1, 0.0, 20.0),
        ("B", -1, 10.0, 15.0),
    ]
    result = sequence_crossings(candidates)
    by_key = {key: (delta, entry, exit_) for key, delta, entry, exit_ in result}
    assert by_key["A"] == (0.0, 0.0, 20.0)
    assert by_key["B"][0] == 10.0
    assert by_key["B"][1] == 20.0
    assert by_key["B"][2] == 25.0


def test_sequence_crossings_same_direction_never_waits():
    candidates = [
        ("A", 1, 0.0, 10.0),
        ("B", 1, 5.0, 15.0),
    ]
    result = sequence_crossings(candidates)
    by_key = {key: delta for key, delta, _, _ in result}
    assert by_key["A"] == 0.0
    assert by_key["B"] == 0.0


def test_sequence_crossings_opposite_direction_after_segment_clears_does_not_wait():
    candidates = [
        ("A", 1, 0.0, 10.0),
        ("B", -1, 15.0, 20.0),
    ]
    result = sequence_crossings(candidates)
    by_key = {key: delta for key, delta, _, _ in result}
    assert by_key["B"] == 0.0
