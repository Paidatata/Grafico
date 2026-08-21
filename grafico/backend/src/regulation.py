def compute_ramp_deltas(candidate_ids: list[str], excess: float) -> dict[str, float]:
    """candidate_ids: chronologically ordered [D1..DN], DN is the anchor (the paired
    departure the ramp targets). Returns trip_id -> delta_minutes.

    Every entry except the last uses round(k * excess / N); the last always gets
    exactly `excess`, regardless of rounding — this is what keeps the anchor's
    resulting departure time exact even when excess doesn't divide evenly by N.
    """
    n = len(candidate_ids)
    if n == 0:
        return {}
    deltas = {trip_id: round(k * excess / n) for k, trip_id in enumerate(candidate_ids[:-1], start=1)}
    if candidate_ids:
        deltas[candidate_ids[-1]] = excess
    return deltas
