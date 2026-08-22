from datetime import datetime

from src import models, service
from src.db import init_db
from src.schemas import TemplateImportStop, TemplateImportTrip


def test_auto_regulation_defaults_to_disabled(db_session):
    init_db(db_session.get_bind())
    assert service.get_auto_regulation_enabled(db_session) is False


def test_set_and_read_auto_regulation(db_session):
    init_db(db_session.get_bind())
    service.set_auto_regulation_enabled(db_session, True)
    assert service.get_auto_regulation_enabled(db_session) is True


def _seed_turnaround_scenario(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="A1", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="RGS", time="05:00:00"),
                TemplateImportStop(station="BFU", time="05:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="ARRIVAL", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="RGS", time="05:20:00"),
                TemplateImportStop(station="BFU", time="05:50:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D1", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="BFU", time="06:00:00"),
                TemplateImportStop(station="RGS", time="06:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D2", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="BFU", time="06:15:00"),
                TemplateImportStop(station="RGS", time="06:45:00"),
            ],
        ),
    ])
    service.set_station_turnaround(db_session, "BFU", 20 * 60)


def _test_shift_single_trip(db_session, trip_id, station_id, new_time):
    stops = service._trip_stops(db_session, trip_id)
    idx = next(i for i, s in enumerate(stops) if s.station_id == station_id)
    delta = service.time_str_to_minutes(new_time) - service.time_str_to_minutes(stops[idx].departure_time)
    for stop in stops[idx:]:
        stop.arrival_time = service.minutes_to_time_str(service.time_str_to_minutes(stop.arrival_time) + delta)
        stop.departure_time = service.minutes_to_time_str(service.time_str_to_minutes(stop.departure_time) + delta)
    db_session.commit()

def test_apply_regulation_ramps_intermediate_departures(db_session):
    _seed_turnaround_scenario(db_session)
    now = datetime(2026, 8, 16, 4, 30, 0)
    _test_shift_single_trip(db_session, "ARRIVAL", "BFU", "06:05:00")

    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)
    updated_by_id = {t.trip_id: t for t in updated}

    assert updated_by_id["D2"].stops[0].time == "06:25:00"
    assert updated_by_id["D1"].stops[0].time == "06:05:00"


def test_apply_regulation_mirrors_anchor_delta_onto_later_departures(db_session):
    """Departures scheduled after the ramp's anchor (the turnaround-paired departure)
    must shift by the anchor's exact delta too -- otherwise a late-running terminal
    silently breaks the headway/order between the anchor and whatever comes after it."""
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="A1", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="RGS", time="05:00:00"),
                TemplateImportStop(station="BFU", time="05:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="ARRIVAL", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="RGS", time="05:20:00"),
                TemplateImportStop(station="BFU", time="05:50:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D1", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="BFU", time="06:00:00"),
                TemplateImportStop(station="RGS", time="06:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D2", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="BFU", time="06:15:00"),
                TemplateImportStop(station="RGS", time="06:45:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D3", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="BFU", time="07:00:00"),
                TemplateImportStop(station="RGS", time="07:30:00"),
            ],
        ),
    ])
    service.set_station_turnaround(db_session, "BFU", 20 * 60)
    now = datetime(2026, 8, 16, 4, 30, 0)
    _test_shift_single_trip(db_session, "ARRIVAL", "BFU", "06:05:00")

    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)
    updated_by_id = {t.trip_id: t for t in updated}

    # Anchor (D2) still lands exactly on target; D1 still tapers as before.
    assert updated_by_id["D2"].stops[0].time == "06:25:00"
    assert updated_by_id["D1"].stops[0].time == "06:05:00"
    # D3 is after the anchor, so it must mirror the anchor's +10min delta exactly
    # (not taper), preserving its planned spacing behind D2.
    assert "D3" in updated_by_id
    assert updated_by_id["D3"].stops[0].time == "07:10:00"
    d3 = service.get_trip(db_session, "D3")
    assert d3.stops[1].time == "07:40:00"  # whole downstream route mirrors too


def test_apply_regulation_is_noop_when_no_violation(db_session):
    _seed_turnaround_scenario(db_session)
    now = datetime(2026, 8, 16, 4, 30, 0)
    updated = service.apply_regulation(db_session, "ARRIVAL", "RGS", now=now)
    assert updated == []


def test_apply_regulation_never_compresses_a_departure_into_the_past(db_session):
    _seed_turnaround_scenario(db_session)
    now = datetime(2026, 8, 16, 6, 1, 0)
    _test_shift_single_trip(db_session, "ARRIVAL", "BFU", "06:05:00")

    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)
    updated_by_id = {t.trip_id: t for t in updated}
    assert "D1" not in updated_by_id
    assert updated_by_id["D2"].stops[0].time == "06:25:00"


def test_shift_stop_auto_regulates_when_enabled(db_session):
    _seed_turnaround_scenario(db_session)
    service.set_auto_regulation_enabled(db_session, True)
    now = datetime(2026, 8, 16, 4, 30, 0)

    service.shift_stop(db_session, "ARRIVAL", "BFU", "06:05:00", now=now)

    d2 = service.get_trip(db_session, "D2")
    assert d2.stops[0].time == "06:25:00"


def test_shift_stop_performs_manual_cascade_when_auto_regulation_disabled(db_session):
    _seed_turnaround_scenario(db_session)
    now = datetime(2026, 8, 16, 4, 30, 0)

    service.shift_stop(db_session, "ARRIVAL", "BFU", "06:05:00", now=now)

    d2 = service.get_trip(db_session, "D2")
    # Manual cascade logic applies +15 min delta to D2
    assert d2.stops[0].time == "06:30:00"


def test_apply_regulation_is_noop_when_station_turnaround_not_configured(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="ARRIVAL", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="RGS", time="05:20:00"),
                TemplateImportStop(station="BFU", time="05:50:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D1", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="BFU", time="06:00:00"),
                TemplateImportStop(station="RGS", time="06:30:00"),
            ],
        ),
    ])
    # Every station defaults to 180s (init_db backfill); explicitly clear BFU to simulate
    # an operator excluding it from turnaround pairing/validation.
    service.set_station_turnaround(db_session, "BFU", None)
    now = datetime(2026, 8, 16, 4, 30, 0)
    _test_shift_single_trip(db_session, "ARRIVAL", "BFU", "06:05:00")

    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)

    assert updated == []
    d1 = service.get_trip(db_session, "D1")
    assert d1.stops[0].time == "06:00:00"


def test_apply_regulation_targets_arrival_time_not_departure_time(db_session):
    _seed_turnaround_scenario(db_session)
    now = datetime(2026, 8, 16, 4, 30, 0)
    _test_shift_single_trip(db_session, "ARRIVAL", "BFU", "06:05:00")

    # Simulate arrival_time and departure_time diverging at the arrival stop (e.g. a future
    # dwell-time feature). The ramp's target must be anchored on arrival_time; this drift
    # in departure_time must not change the computed target.
    stop = (
        db_session.query(models.PlannedStop)
        .filter(models.PlannedStop.trip_id == "ARRIVAL", models.PlannedStop.station_id == "BFU")
        .first()
    )
    stop.departure_time = "06:20:00"
    db_session.commit()

    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)
    updated_by_id = {t.trip_id: t for t in updated}

    assert updated_by_id["D2"].stops[0].time == "06:25:00"


def test_apply_regulation_sorts_arrivals_by_arrival_time_not_departure_time(db_session):
    _seed_turnaround_scenario(db_session)
    now = datetime(2026, 8, 16, 4, 30, 0)
    _test_shift_single_trip(db_session, "ARRIVAL", "BFU", "06:05:00")

    # Corrupt A1's stored departure_time only (arrival_time stays 05:30:00) so that sorting
    # arrivals by departure_time would rank A1 after ARRIVAL, flipping which departure gets
    # paired with ARRIVAL.
    a1_stop = (
        db_session.query(models.PlannedStop)
        .filter(models.PlannedStop.trip_id == "A1", models.PlannedStop.station_id == "BFU")
        .first()
    )
    a1_stop.departure_time = "06:10:00"
    db_session.commit()

    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)
    updated_by_id = {t.trip_id: t for t in updated}

    assert updated_by_id["D2"].stops[0].time == "06:25:00"
    assert updated_by_id["D1"].stops[0].time == "06:05:00"


def test_apply_regulation_compresses_departures_when_excess_becomes_negative(db_session):
    _seed_turnaround_scenario(db_session)
    now = datetime(2026, 8, 16, 4, 30, 0)
    _test_shift_single_trip(db_session, "ARRIVAL", "BFU", "06:05:00")
    service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)  # prior ramp: D1->06:05, D2->06:25

    # Arrival recovers (less delay): the required target shrinks below D2's already-ramped
    # departure, so re-running regulation must compress D1/D2 back down, anchor still exact.
    _test_shift_single_trip(db_session, "ARRIVAL", "BFU", "05:57:00")
    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)
    updated_by_id = {t.trip_id: t for t in updated}

    assert updated_by_id["D2"].stops[0].time == "06:17:00"
    assert updated_by_id["D1"].stops[0].time == "06:01:00"


def test_apply_regulation_skips_early_departures_from_stabled_trains(db_session):
    """A train that departs before any arrival that morning (stabled/recolhimento) must
    not be positionally paired with the first arrival of the day."""
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="D0", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="BFU", time="04:00:00"),
                TemplateImportStop(station="RGS", time="04:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="ARRIVAL", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="RGS", time="05:20:00"),
                TemplateImportStop(station="BFU", time="05:50:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D1", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="BFU", time="06:00:00"),
                TemplateImportStop(station="RGS", time="06:30:00"),
            ],
        ),
    ])
    service.set_station_turnaround(db_session, "BFU", 20 * 60)
    now = datetime(2026, 8, 16, 4, 30, 0)

    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)
    updated_by_id = {t.trip_id: t for t in updated}

    # ARRIVAL (05:50) must pair with D1 (06:00, the first departure at/after its arrival),
    # never with D0 (04:00, already gone before ARRIVAL got there).
    assert "D0" not in updated_by_id
    assert updated_by_id["D1"].stops[0].time == "06:10:00"


def test_apply_regulation_redistributes_compression_when_a_departure_cannot_recede(db_session):
    _seed_turnaround_scenario(db_session)
    now1 = datetime(2026, 8, 16, 4, 30, 0)
    _test_shift_single_trip(db_session, "ARRIVAL", "BFU", "06:05:00")
    service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now1)  # prior ramp: D1->06:05, D2->06:25

    now2 = datetime(2026, 8, 16, 6, 4, 0)
    _test_shift_single_trip(db_session, "ARRIVAL", "BFU", "05:31:00")

    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now2)
    updated_by_id = {t.trip_id: t for t in updated}

    # D1 would need to recede to 05:48, more than the 15-minute lookback grace before
    # 06:04 (floor 05:49) allows -- it must stay put, with the full compression
    # redistributed onto D2 alone, which still lands exactly on the anchor target.
    assert "D1" not in updated_by_id
    d1 = service.get_trip(db_session, "D1")
    assert d1.stops[0].time == "06:05:00"
    assert updated_by_id["D2"].stops[0].time == "05:51:00"
