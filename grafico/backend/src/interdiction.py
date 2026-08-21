from .timeutils import time_str_to_service_minutes


def crossing_window(stops, y_top: float, y_bottom: float):
    """stops: list of (y_coordinate, arrival_time, departure_time), in trip order.

    Returns (entry_service_minutes, exit_service_minutes, first_affected_stop_index)
    for the first stop-to-stop segment whose y-range overlaps [y_top, y_bottom], using
    each stop's departure_time (matching how the chart itself draws straight lines
    between consecutive stops — arrival/departure are not distinguished for geometry).
    Returns None if the trip's polyline never enters the band.
    """
    for i in range(len(stops) - 1):
        y_a, _, dep_a = stops[i]
        y_b, _, dep_b = stops[i + 1]
        seg_low, seg_high = min(y_a, y_b), max(y_a, y_b)
        if seg_high < y_top or seg_low > y_bottom or y_a == y_b:
            continue

        t_a = time_str_to_service_minutes(dep_a)
        t_b = time_str_to_service_minutes(dep_b)

        def time_at_y(y):
            frac = (y - y_a) / (y_b - y_a)
            return t_a + frac * (t_b - t_a)

        t_top = time_at_y(max(seg_low, y_top))
        t_bottom = time_at_y(min(seg_high, y_bottom))
        return min(t_top, t_bottom), max(t_top, t_bottom), i + 1
    return None


def sequence_crossings(candidates):
    """candidates: list of (key, direction_sign, entry_minutes, exit_minutes), any order.

    Returns a list of (key, delta_minutes, new_entry_minutes, new_exit_minutes), one per
    candidate, processed in ascending entry_minutes order (FCFS by natural entry time —
    never re-sorted after a delay is applied). Same-direction candidates never wait;
    opposite-direction candidates wait if they would enter before the segment frees up.
    """
    ordered = sorted(candidates, key=lambda c: c[2])
    occupant_direction = None
    free_at = None
    results = []

    for key, direction, entry, exit_ in ordered:
        delta = 0.0
        if occupant_direction is not None and direction != occupant_direction and entry < free_at:
            delta = free_at - entry

        new_entry = entry + delta
        new_exit = exit_ + delta

        if occupant_direction is None or direction != occupant_direction:
            occupant_direction = direction
            free_at = new_exit
        else:
            free_at = max(free_at, new_exit)

        results.append((key, delta, new_entry, new_exit))

    return results
