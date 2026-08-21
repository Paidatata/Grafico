from src.regulation import compute_ramp_deltas


def test_ramp_distributes_evenly_and_anchor_is_exact():
    deltas = compute_ramp_deltas(["D1", "D2", "D3", "D4", "D5"], excess=10.0)
    assert deltas["D1"] == 2.0
    assert deltas["D2"] == 4.0
    assert deltas["D3"] == 6.0
    assert deltas["D4"] == 8.0
    assert deltas["D5"] == 10.0


def test_ramp_handles_non_divisible_excess_without_anchor_drift():
    deltas = compute_ramp_deltas(["D1", "D2", "D3"], excess=10.0)
    assert deltas["D1"] == 3
    assert deltas["D2"] == 7
    assert deltas["D3"] == 10.0


def test_ramp_handles_negative_excess_for_compression():
    deltas = compute_ramp_deltas(["D1", "D2"], excess=-10.0)
    assert deltas["D1"] == -5.0
    assert deltas["D2"] == -10.0


def test_ramp_with_a_single_candidate_is_just_the_anchor():
    deltas = compute_ramp_deltas(["D1"], excess=7.0)
    assert deltas == {"D1": 7.0}
