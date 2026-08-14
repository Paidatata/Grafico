from datetime import datetime

from src import service
from src.db import init_db
from src.errors import TripNotFoundError
from src.schemas import TemplateImportStop, TemplateImportTrip

import pytest


def _sample_trips():
    return [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000",
            direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="LUZ", time="05:10:00"),
                TemplateImportStop(station="RGS", time="05:30:00"),
            ],
        )
    ]


def test_import_template_populates_live_schedule(db_session):
    init_db(db_session.get_bind())

    imported = service.import_template(db_session, _sample_trips())
    assert imported == 1

    schedule = service.get_live_schedule(db_session)
    assert len(schedule.trips) == 1
    trip = schedule.trips[0]
    assert trip.trip_id == "TRIP_BFU-RGS_050000"
    assert trip.start_time == "05:00:00"
    assert trip.end_time == "05:30:00"
    assert [s.station for s in trip.stops] == ["BFU", "LUZ", "RGS"]


def test_import_template_replaces_previous_template(db_session):
    init_db(db_session.get_bind())

    service.import_template(db_session, _sample_trips())
    service.import_template(db_session, _sample_trips())  # re-import must not duplicate

    schedule = service.get_live_schedule(db_session)
    assert len(schedule.trips) == 1


def test_get_trip_raises_when_missing(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, _sample_trips())

    with pytest.raises(TripNotFoundError):
        service.get_trip(db_session, "NOT_A_REAL_TRIP")


def test_perform_daily_reset_restores_live_from_template(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, _sample_trips())

    # Simulate a live edit, then reset and confirm it reverts. `now` is pinned close to
    # the stop's scheduled 05:10 time so the shift falls inside the default lookback
    # window regardless of the real wall-clock time the test suite happens to run at.
    service.shift_stop(
        db_session, "TRIP_BFU-RGS_050000", "LUZ", "05:20:00",
        now=datetime(2026, 8, 13, 5, 15, 0),
    )
    service.perform_daily_reset(db_session)

    trip = service.get_trip(db_session, "TRIP_BFU-RGS_050000")
    assert trip.stops[1].time == "05:10:00"  # back to template value
