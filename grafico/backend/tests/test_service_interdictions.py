from datetime import datetime
import pytest

from src import service, models, interdiction as interdiction_geometry
from src.db import init_db
from src.errors import InterdictionNotFoundError
from src.schemas import TemplateImportStop, TemplateImportTrip
from src.timeutils import time_str_to_minutes


def test_interdiction_models_round_trip(db_session):
    init_db(db_session.get_bind())
    interdiction = models.Interdiction(
        y_top=1000.0, y_bottom=1500.0, start_time="10:00:00", end_time="14:00:00",
        description="Obra de manutenção",
    )
    db_session.add(interdiction)
    db_session.commit()
    db_session.refresh(interdiction)

    snapshot = models.InterdictionStopSnapshot(
        interdiction_id=interdiction.id, trip_id="T1", station_id="SAN",
        arrival_time="10:05:00", departure_time="10:05:00",
    )
    db_session.add(snapshot)
    db_session.commit()

    fetched = db_session.query(models.Interdiction).first()
    assert fetched.description == "Obra de manutenção"
    assert db_session.query(models.InterdictionStopSnapshot).count() == 1


def _seed_two_opposite_trips(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:40:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="TRIP_RGS-BFU_050500", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:10:00"),
                TemplateImportStop(station="BFU", time="05:30:00"),
            ],
        ),
    ])
    service.set_current_schedule_id(1)
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 16, 4, 30, 0))


def _seed_two_opposite_trips_plus_later_departures(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:40:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="TRIP_RGS-BFU_050500", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:10:00"),
                TemplateImportStop(station="BFU", time="05:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="TRIP_RGS-BFU_060000", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="06:00:00"),
                TemplateImportStop(station="SAN", time="06:10:00"),
                TemplateImportStop(station="BFU", time="06:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_070000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="07:00:00"),
                TemplateImportStop(station="SAN", time="07:20:00"),
                TemplateImportStop(station="RGS", time="07:40:00"),
            ],
        ),
        # Well after every arrival in this scenario, and after the interdiction's own
        # 05:00-06:00 window, so it never gets held -- exists only so the FIFO-paired
        # cascade recipient (TRIP_RGS-BFU_060000) has an eligible departure to test against.
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_080000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="08:00:00"),
                TemplateImportStop(station="SAN", time="08:20:00"),
                TemplateImportStop(station="RGS", time="08:40:00"),
            ],
        ),
    ])
    service.set_current_schedule_id(1)
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 16, 4, 30, 0))


def test_create_interdiction_cascades_delay_to_later_same_direction_departures(db_session):
    _seed_two_opposite_trips_plus_later_departures(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    affected_by_trip = {a.trip_id: a for a in result.affected_trips}
    held = affected_by_trip["TRIP_RGS-BFU_050500"]
    delta = time_str_to_minutes(held.entry_time) - time_str_to_minutes(held.original_entry_time)
    assert delta > 0  # sanity: this trip was actually held

    # TRIP_RGS-BFU_050500's S_prev is SAN (see test_create_interdiction_holds_the_train_at_s_prev_only).
    # TRIP_RGS-BFU_060000 (RGS 06:00 -> SAN 06:10 -> BFU 06:30) passes through SAN later than
    # the held trip's *original* SAN departure (05:10) -- it must cascade by the same delta,
    # anchored at ITS OWN SAN stop (its own RGS departure stays untouched).
    later_same_direction = service.get_trip(db_session, "TRIP_RGS-BFU_060000")
    by_station = {s.station: s for s in later_same_direction.stops}
    assert by_station["RGS"].time == "06:00:00"  # before its own S_prev-equivalent: untouched
    assert by_station["SAN"].arrival_time == "06:10:00"
    assert time_str_to_minutes(by_station["SAN"].time) - time_str_to_minutes("06:10:00") == pytest.approx(delta, abs=2 / 60)
    assert time_str_to_minutes(by_station["BFU"].time) - time_str_to_minutes("06:30:00") == pytest.approx(delta, abs=2 / 60)

    # Headway at SAN (the shared station) between the two departures is preserved exactly.
    held_trip = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    held_new_san_departure = next(s.time for s in held_trip.stops if s.station == "SAN")
    original_headway = time_str_to_minutes("06:10:00") - time_str_to_minutes("05:10:00")
    new_headway = time_str_to_minutes(by_station["SAN"].time) - time_str_to_minutes(held_new_san_departure)
    assert new_headway == pytest.approx(original_headway, abs=2 / 60)

    # Opposite direction, later departure: must NOT cascade -- headway preservation is
    # per-direction (a same-track opposite-direction train has no shared headway to keep).
    opposite_later = service.get_trip(db_session, "TRIP_BFU-RGS_070000")
    assert opposite_later.stops[0].time == "07:00:00"


def test_create_interdiction_reports_original_entry_time_separately_from_the_wait(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    affected_by_trip = {a.trip_id: a for a in result.affected_trips}

    # First occupant: no wait, so it resumes exactly at its own unimpeded arrival.
    first = affected_by_trip["TRIP_BFU-RGS_050000"]
    assert first.original_entry_time == first.entry_time

    # Held train: entry_time (post-wait) must differ from original_entry_time (unimpeded
    # arrival at the border) by exactly the wait, and line up with when the segment frees.
    held = affected_by_trip["TRIP_RGS-BFU_050500"]
    assert held.original_entry_time != held.entry_time
    assert held.entry_time == first.exit_time


def test_create_interdiction_holds_the_train_at_s_prev_only(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    affected = {a.trip_id: a for a in result.affected_trips}["TRIP_RGS-BFU_050500"]
    delta = time_str_to_minutes(affected.entry_time) - time_str_to_minutes(affected.original_entry_time)
    assert delta > 0  # sanity: this trip was actually held

    # TRIP_RGS-BFU_050500 is RGS(05:00) -> SAN(05:10) -> BFU(05:30); the interdiction band
    # (y 3500-5000) sits on the SAN->BFU segment, so S_prev is SAN.
    trip = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    by_station = {s.station: s for s in trip.stops}

    # Before S_prev: untouched.
    assert by_station["RGS"].time == "05:00:00"

    # S_prev itself: arrival stays original (the train is on time getting there); only the
    # departure (when it's allowed to leave the platform) receives the delta.
    assert by_station["SAN"].arrival_time == "05:10:00"
    assert time_str_to_minutes(by_station["SAN"].time) - time_str_to_minutes("05:10:00") == pytest.approx(delta, abs=2 / 60)

    # After S_prev: both arrival and departure shift by the same delta, preserving speed.
    assert time_str_to_minutes(by_station["BFU"].arrival_time) - time_str_to_minutes("05:30:00") == pytest.approx(delta, abs=2 / 60)
    assert time_str_to_minutes(by_station["BFU"].time) - time_str_to_minutes("05:30:00") == pytest.approx(delta, abs=2 / 60)


def test_create_interdiction_holds_the_second_train_at_the_edge(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    assert result.interdiction.description == "Obra"
    affected_by_trip = {a.trip_id: a for a in result.affected_trips}
    assert "TRIP_BFU-RGS_050000" in affected_by_trip
    assert "TRIP_RGS-BFU_050500" in affected_by_trip

    rgs_bfu_trip = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    original_bfu_time = "05:30:00"
    bfu_stop = next(s for s in rgs_bfu_trip.stops if s.station == "BFU")
    assert bfu_stop.time != original_bfu_time


def test_create_interdiction_excludes_trip_already_inside_the_band(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Emergência",
        now=datetime(2026, 8, 16, 5, 15, 0),
    )
    affected_ids = {a.trip_id for a in result.affected_trips}
    assert "TRIP_BFU-RGS_050000" not in affected_ids


def test_create_interdiction_ignores_trips_outside_its_time_window(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="20:00:00", end_time="21:00:00", description="Noite",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    assert result.affected_trips == []


def test_delete_interdiction_reverts_affected_stops_within_lookback(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    interdiction_id = result.interdiction.id
    rgs_bfu_before_delete = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    shifted_time = next(s.time for s in rgs_bfu_before_delete.stops if s.station == "BFU")
    assert shifted_time != "05:30:00"

    service.delete_interdiction(db_session, interdiction_id, now=datetime(2026, 8, 16, 4, 30, 0))

    rgs_bfu_after = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    restored_time = next(s.time for s in rgs_bfu_after.stops if s.station == "BFU")
    assert restored_time == "05:30:00"


def test_delete_interdiction_leaves_frozen_stops_untouched(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    interdiction_id = result.interdiction.id

    rgs_bfu_before = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    shifted_time = next(s.time for s in rgs_bfu_before.stops if s.station == "BFU")

    service.delete_interdiction(db_session, interdiction_id, now=datetime(2026, 8, 16, 7, 0, 0))

    rgs_bfu_after = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    frozen_time = next(s.time for s in rgs_bfu_after.stops if s.station == "BFU")
    assert frozen_time == shifted_time


def test_update_interdiction_reverts_then_reapplies_with_new_window(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    interdiction_id = result.interdiction.id

    updated = service.update_interdiction(
        db_session, interdiction_id, y_top=3500.0, y_bottom=5000.0,
        start_time="20:00:00", end_time="21:00:00", description="Obra adiada",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    assert updated.affected_trips == []

    rgs_bfu_after = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    restored_time = next(s.time for s in rgs_bfu_after.stops if s.station == "BFU")
    assert restored_time == "05:30:00"


def test_delete_unknown_interdiction_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(InterdictionNotFoundError):
        service.delete_interdiction(db_session, 999)


def test_live_schedule_reports_crossing_windows_consistent_with_creation(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    created_by_trip = {a.trip_id: a for a in result.affected_trips}
    assert created_by_trip  # sanity: the fixture does produce affected trips

    schedule = service.get_live_schedule(db_session)
    interdiction_out = next(i for i in schedule.interdictions if i.id == result.interdiction.id)
    reported_by_trip = {a.trip_id: a for a in interdiction_out.affected_trips}

    # The GET-time recomputation must reproduce (within HH:MM:SS rounding, since both
    # values round-trip through second-granularity strings) what create-time produced --
    # not a naive re-interpolation over the (asymmetrically shifted) live stop times, which
    # stretches/misplaces the window by whole minutes once a trip has been delayed.
    assert reported_by_trip.keys() == created_by_trip.keys()
    for trip_id, created in created_by_trip.items():
        reported = reported_by_trip[trip_id]
        assert abs(time_str_to_minutes(reported.entry_time) - time_str_to_minutes(created.entry_time)) <= 1 / 60
        assert abs(time_str_to_minutes(reported.exit_time) - time_str_to_minutes(created.exit_time)) <= 1 / 60
        assert abs(
            time_str_to_minutes(reported.original_entry_time) - time_str_to_minutes(created.original_entry_time)
        ) <= 1 / 60


def test_interdiction_delay_triggers_auto_regulation_when_enabled(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:40:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="TRIP_RGS-BFU_050500", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:10:00"),
                TemplateImportStop(station="BFU", time="05:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D0", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="04:00:00"),
                TemplateImportStop(station="RGS", time="04:20:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D1", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="06:05:00"),
                TemplateImportStop(station="RGS", time="06:30:00"),
            ],
        ),
    ])
    service.set_current_schedule_id(1)
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 16, 4, 30, 0))
    service.set_station_turnaround(db_session, "BFU", 5 * 60)
    service.set_auto_regulation_enabled(db_session, True)

    service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )

    rgs_bfu = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    bfu_arrival = next(s.time for s in rgs_bfu.stops if s.station == "BFU")
    assert bfu_arrival == "05:32:47"  # delayed by the interdiction (held at the edge)

    # D0 (BFU 04:00) departed well before "now" (04:30) and before the arrival -- a
    # stabled/recolhimento train, outside both the FIFO pairing window and the ramp's
    # own future-departures set, so it must be left completely untouched.
    d0 = service.get_trip(db_session, "D0")
    assert d0.stops[0].time == "04:00:00"

    d1 = service.get_trip(db_session, "D1")
    # Target = new BFU arrival (05:32:47) + 5min turnaround = 05:37:47; D1 is the first
    # FIFO-eligible departure (D0 and TRIP_BFU-RGS_050000 are both earlier than the
    # arrival) and, as the ramp's anchor, must land exactly on target.
    assert d1.stops[0].time == "05:37:47"


def test_interdiction_delay_does_not_auto_regulate_when_disabled(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:40:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="TRIP_RGS-BFU_050500", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:10:00"),
                TemplateImportStop(station="BFU", time="05:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D1", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="04:55:00"),
                TemplateImportStop(station="RGS", time="05:20:00"),
            ],
        ),
    ])
    service.set_current_schedule_id(1)
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 16, 4, 30, 0))
    service.set_station_turnaround(db_session, "BFU", 5 * 60)
    # auto_regulation_enabled left at its default (False)

    service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )

    d1 = service.get_trip(db_session, "D1")
    assert d1.stops[0].time == "04:55:00"


def _seed_two_holds_in_the_same_direction(db_session):
    """Four trips whose FCFS order at the band flips occupancy twice: T0 -> A -> C -> B.

    T0 (BFU-RGS) takes the band first; A (RGS-BFU) waits behind it; C (BFU-RGS) then waits
    behind A; B (RGS-BFU) waits behind C. So A and B are BOTH directly held, share the same
    direction and the same S_prev (SAN), and B's original SAN departure (05:25) is later than
    A's (05:10) -- which is exactly the shape that used to make B receive A's delta as a
    cascade *on top of* its own hold (double-shift + duplicate snapshot PK crash).
    """
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="T0", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:40:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="A", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:10:00"),
                TemplateImportStop(station="BFU", time="05:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="C", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:15:00"),
                TemplateImportStop(station="SAN", time="05:35:00"),
                TemplateImportStop(station="RGS", time="05:55:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="B", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="05:15:00"),
                TemplateImportStop(station="SAN", time="05:25:00"),
                TemplateImportStop(station="BFU", time="05:45:00"),
            ],
        ),
    ])
    service.set_current_schedule_id(1)
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 16, 4, 30, 0))


def test_a_trip_held_behind_another_hold_is_shifted_only_once(db_session):
    _seed_two_holds_in_the_same_direction(db_session)

    # Must not raise: the old code applied B's delta twice (own hold + cascade from A) and
    # re-inserted B's InterdictionStopSnapshot rows, blowing up the commit with
    # "UNIQUE constraint failed: interdiction_stop_snapshots".
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    affected_by_trip = {a.trip_id: a for a in result.affected_trips}
    delta_a = (
        time_str_to_minutes(affected_by_trip["A"].entry_time)
        - time_str_to_minutes(affected_by_trip["A"].original_entry_time)
    )
    delta_b = (
        time_str_to_minutes(affected_by_trip["B"].entry_time)
        - time_str_to_minutes(affected_by_trip["B"].original_entry_time)
    )
    assert delta_a > 0  # sanity: A is directly held behind T0
    assert delta_b > 0  # sanity: B is directly held behind C, independently of A

    # B's own sequence_crossings delta already contains every upstream retention at this
    # crossing (free_at is threaded forward), so B must move by exactly delta_b -- never by
    # delta_a + delta_b.
    b_trip = service.get_trip(db_session, "B")
    b_by_station = {s.station: s for s in b_trip.stops}
    assert b_by_station["RGS"].time == "05:15:00"  # upstream of S_prev: untouched
    assert b_by_station["SAN"].arrival_time == "05:25:00"
    b_shift = time_str_to_minutes(b_by_station["SAN"].time) - time_str_to_minutes("05:25:00")
    assert b_shift == pytest.approx(delta_b, abs=2 / 60)
    assert b_shift != pytest.approx(delta_a + delta_b, abs=2 / 60)
    assert time_str_to_minutes(b_by_station["BFU"].time) - time_str_to_minutes("05:45:00") == pytest.approx(
        delta_b, abs=2 / 60
    )

    # And exactly one snapshot row per (trip, station) -- one write, one baseline to revert.
    snapshot_keys = [
        (s.trip_id, s.station_id)
        for s in db_session.query(models.InterdictionStopSnapshot)
        .filter(models.InterdictionStopSnapshot.interdiction_id == result.interdiction.id)
        .all()
    ]
    assert len(snapshot_keys) == len(set(snapshot_keys))
    assert ("B", "SAN") in snapshot_keys


def test_cascade_recipients_do_not_trigger_auto_regulation(db_session):
    _seed_two_opposite_trips_plus_later_departures(db_session)
    service.set_station_turnaround(db_session, "BFU", 5 * 60)
    service.set_auto_regulation_enabled(db_session, True)

    service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )

    # The directly held trip still regulates its own paired departure (Spec 4 behaviour
    # that must not regress). FIFO pairing skips TRIP_BFU-RGS_050000 (05:00, already
    # departed before this arrival's original 05:30 -- a stabled/recolhimento train) and
    # pairs TRIP_RGS-BFU_050500's BFU arrival with the next eligible departure,
    # TRIP_BFU-RGS_070000, which -- as the ramp's anchor -- must land exactly on target
    # (the ramp still tapers TRIP_BFU-RGS_050000 a little on the way there; that taper is
    # pre-existing Spec 4 behaviour, not something this fix changes or needs to assert).
    held = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    held_bfu_arrival = next(s.arrival_time for s in held.stops if s.station == "BFU")
    paired_with_held = service.get_trip(db_session, "TRIP_BFU-RGS_070000")
    assert time_str_to_minutes(paired_with_held.stops[0].time) == pytest.approx(
        time_str_to_minutes(held_bfu_arrival) + 5, abs=2 / 60
    )

    # TRIP_RGS-BFU_060000 is only a *cascade* recipient (headway preservation), never a
    # directly held trip -- it must never independently trigger its own tapering
    # regulation ramp. TRIP_BFU-RGS_080000 (070000 is already taken by the directly-held
    # trip above) does still move, but only because apply_regulation mirrors the anchor's
    # exact delta onto every later departure at the station -- if 060000 had instead
    # triggered its own regulation, 080000 would land on a different target (060000's own,
    # cascade-shifted arrival + turnaround), not the anchor's delta mirrored verbatim.
    cascade_recipient = service.get_trip(db_session, "TRIP_RGS-BFU_060000")
    assert next(s.time for s in cascade_recipient.stops if s.station == "SAN") != "06:10:00"  # sanity
    paired_with_cascade = service.get_trip(db_session, "TRIP_BFU-RGS_080000")
    held_delta = time_str_to_minutes(paired_with_held.stops[0].time) - time_str_to_minutes("07:00:00")
    cascade_shift = time_str_to_minutes(paired_with_cascade.stops[0].time) - time_str_to_minutes("08:00:00")
    assert cascade_shift == pytest.approx(held_delta, abs=2 / 60)


def _seed_hold_plus_cascade_recipient(db_session):
    """T0 occupies the band, A (RGS-BFU) is held behind it, R (RGS-BFU) only cascades.

    R crosses after A in the same direction, so sequence_crossings gives it delta 0 (same
    direction never waits) -- it is purely a cascade recipient at SAN, A's S_prev.
    """
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="T0", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:40:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="A", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:10:00"),
                TemplateImportStop(station="BFU", time="05:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="R", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="05:05:00"),
                TemplateImportStop(station="SAN", time="05:15:00"),
                TemplateImportStop(station="BFU", time="05:35:00"),
            ],
        ),
    ])
    service.set_current_schedule_id(1)
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 16, 4, 30, 0))


def test_interdiction_writes_respect_the_edit_lookback_floor(db_session):
    _seed_hold_plus_cascade_recipient(db_session)
    service.set_edit_lookback_minutes(db_session, 5)

    # now = 05:30, lookback 5min => any stop currently departing before 05:25 is frozen.
    # A's SAN departure (05:10) and R's SAN departure (05:15) are both past that floor;
    # A's BFU stop (05:30) and R's BFU stop (05:35) are not.
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 5, 30, 0),
    )
    affected_by_trip = {a.trip_id: a for a in result.affected_trips}
    delta = (
        time_str_to_minutes(affected_by_trip["A"].entry_time)
        - time_str_to_minutes(affected_by_trip["A"].original_entry_time)
    )
    assert delta > 0  # sanity: A is held

    held = {s.station: s for s in service.get_trip(db_session, "A").stops}
    recipient = {s.station: s for s in service.get_trip(db_session, "R").stops}

    # Frozen (older than the lookback floor): neither the direct hold nor the cascade may
    # rewrite these -- _revert_interdiction would refuse to undo them, so writing them would
    # be permanent, unrecoverable drift.
    assert held["SAN"].time == "05:10:00"
    assert recipient["SAN"].time == "05:15:00"

    # Still inside the window: written normally.
    assert time_str_to_minutes(held["BFU"].time) - time_str_to_minutes("05:30:00") == pytest.approx(delta, abs=2 / 60)
    assert time_str_to_minutes(recipient["BFU"].time) - time_str_to_minutes("05:35:00") == pytest.approx(
        delta, abs=2 / 60
    )

    # No snapshot for a stop that was never written (nothing to revert), one for each write.
    snapshot_keys = {
        (s.trip_id, s.station_id)
        for s in db_session.query(models.InterdictionStopSnapshot)
        .filter(models.InterdictionStopSnapshot.interdiction_id == result.interdiction.id)
        .all()
    }
    assert ("A", "SAN") not in snapshot_keys
    assert ("R", "SAN") not in snapshot_keys
    assert ("A", "BFU") in snapshot_keys
    assert ("R", "BFU") in snapshot_keys


def _crossing_window_for(db_session, trip_id, y_top, y_bottom):
    stops = service._trip_stops(db_session, trip_id)
    station_y = service._station_y_lookup(db_session)
    geometry_stops = [(station_y.get(s.station_id, 0.0), s.arrival_time, s.departure_time) for s in stops]
    return interdiction_geometry.crossing_window(geometry_stops, y_top, y_bottom)


def test_shift_stop_reconciles_active_interdictions_to_prevent_new_conflicts(db_session):
    _seed_two_opposite_trips(db_session)
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:40:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="TRIP_RGS-BFU_050500", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:10:00"),
                TemplateImportStop(station="BFU", time="05:30:00"),
            ],
        ),
        # Initially departs at 08:00 -- well outside the 05:00-06:00 interdiction window
        # below, so create_interdiction never touches it.
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_080000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="08:00:00"),
                TemplateImportStop(station="SAN", time="08:20:00"),
                TemplateImportStop(station="RGS", time="08:40:00"),
            ],
        ),
    ])
    service.set_current_schedule_id(1)
    now = datetime(2026, 8, 16, 4, 30, 0)
    service.perform_daily_reset(db_session, now=now)

    service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=now,
    )

    # A dispatcher drags TRIP_BFU-RGS_080000's origin from 08:00 to 05:10 -- same shape as
    # TRIP_BFU-RGS_050000's original (unregulated) schedule, so if the interdiction is never
    # re-evaluated, this reintroduces the exact conflict the queue algorithm exists to
    # prevent: two opposite-direction trains crossing the same interdicted band at once.
    service.shift_stop(db_session, "TRIP_BFU-RGS_080000", "BFU", "05:10:00", now=now)

    dragged = {s.station: s for s in service.get_trip(db_session, "TRIP_BFU-RGS_080000").stops}
    # If the drag had been left unregulated, BFU would still read exactly "05:10:00".
    assert dragged["BFU"].time != "05:10:00", (
        "shift_stop must re-run the active interdiction's queue so a manually-dragged trip "
        "that now conflicts with it gets held too, not left crossing unregulated"
    )

    held_window = _crossing_window_for(db_session, "TRIP_RGS-BFU_050500", 3500.0, 5000.0)
    dragged_window = _crossing_window_for(db_session, "TRIP_BFU-RGS_080000", 3500.0, 5000.0)
    assert held_window is not None and dragged_window is not None

    held_entry, held_exit, _ = held_window
    dragged_entry, dragged_exit, _ = dragged_window
    # No two opposite-direction trains may occupy the single-track band at the same time --
    # touching exactly at the border (within a couple seconds' rounding) is fine, same
    # tolerance the rest of this file uses for time-string round-tripping.
    tolerance = 2 / 60
    assert dragged_entry >= held_exit - tolerance or held_entry >= dragged_exit - tolerance
