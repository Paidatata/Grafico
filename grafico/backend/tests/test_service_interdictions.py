from datetime import datetime
import pytest

from src import service, models
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
    service.set_auto_regulation_enabled(db_session, True)

    service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )

    rgs_bfu = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    bfu_arrival = next(s.time for s in rgs_bfu.stops if s.station == "BFU")
    assert bfu_arrival == "05:32:47"  # delayed by the interdiction (held at the edge)

    d1 = service.get_trip(db_session, "D1")
    # Target = new BFU arrival (05:32:47) + 5min turnaround = 05:37:47; D1 was the only
    # BFU-RGS departure paired with this arrival and must be ramped to hit it exactly.
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
