import pytest
from datetime import datetime

from src import service
from src.db import init_db
from src.errors import (
    ChronologyViolationError,
    InvalidTimeError,
    LookbackExceededError,
    StationNotFoundError,
    TripNotFoundError,
)
from src.schemas import TemplateImportStop, TemplateImportTrip


def _seed(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000",
            direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="LUZ", time="05:10:00"),
                TemplateImportStop(station="BAS", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:30:00"),
            ],
        )
    ])


def _seed_midnight_crossing(db_session):
    """A trip that departs before midnight and arrives after it — ~10 of the 251 real trips do."""
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_234500",
            direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="23:45:00"),
                TemplateImportStop(station="LUZ", time="23:55:00"),
                TemplateImportStop(station="BAS", time="00:10:00"),
                TemplateImportStop(station="RGS", time="00:25:00"),
            ],
        )
    ])


def test_shift_after_midnight_stop_is_allowed(db_session):
    """00:10 is *after* 23:55 within the service day; raw-minute comparison says otherwise."""
    _seed_midnight_crossing(db_session)

    trip = service.shift_stop(
        db_session, "TRIP_BFU-RGS_234500", "BAS", "00:15:00",
        now=datetime(2026, 8, 14, 0, 12, 0),
    )

    times = {stop.station: stop.time for stop in trip.stops}
    assert times["LUZ"] == "23:55:00"  # upstream, untouched
    assert times["BAS"] == "00:15:00"  # dragged, +5 min
    assert times["RGS"] == "00:30:00"  # downstream, also +5 min


def test_shift_before_the_pre_midnight_upstream_stop_is_still_rejected(db_session):
    """Dragging the 00:10 stop back to 23:50 puts it before its 23:55 upstream neighbour."""
    _seed_midnight_crossing(db_session)

    with pytest.raises(ChronologyViolationError):
        service.shift_stop(
            db_session, "TRIP_BFU-RGS_234500", "BAS", "23:50:00",
            now=datetime(2026, 8, 14, 0, 12, 0),
        )


def test_shift_across_midnight_still_honours_the_lookback_window(db_session):
    """At 00:40 the 23:45 BFU stop is 55 real minutes in the past — beyond the 15-min window."""
    _seed_midnight_crossing(db_session)

    with pytest.raises(LookbackExceededError):
        service.shift_stop(
            db_session, "TRIP_BFU-RGS_234500", "BFU", "23:50:00",
            now=datetime(2026, 8, 14, 0, 40, 0),
        )


def test_shift_just_after_midnight_is_inside_the_lookback_window(db_session):
    """At 00:02 the 23:55 LUZ stop is only 7 minutes old and must remain editable."""
    _seed_midnight_crossing(db_session)

    trip = service.shift_stop(
        db_session, "TRIP_BFU-RGS_234500", "LUZ", "23:58:00",
        now=datetime(2026, 8, 14, 0, 2, 0),
    )
    assert trip.stops[1].time == "23:58:00"


def test_shift_moves_dragged_and_every_downstream_stop_by_the_same_delta(db_session):
    _seed(db_session)

    trip = service.shift_stop(
        db_session, "TRIP_BFU-RGS_050000", "LUZ", "05:14:00",
        now=datetime(2026, 8, 13, 5, 14, 0),
    )

    times = {stop.station: stop.time for stop in trip.stops}
    assert times["BFU"] == "05:00:00"  # upstream of the dragged node: untouched
    assert times["LUZ"] == "05:14:00"  # dragged node: +4 min
    assert times["BAS"] == "05:24:00"  # downstream: also +4 min
    assert times["RGS"] == "05:34:00"  # downstream: also +4 min


def test_shift_with_invalid_time_raises_a_domain_error(db_session):
    _seed(db_session)
    for bad_time in ["not-a-time", "25:00:00", "12:60:00", "12:00:60", "5:00:00", "", "05:00"]:
        with pytest.raises(InvalidTimeError):
            service.shift_stop(
                db_session, "TRIP_BFU-RGS_050000", "LUZ", bad_time,
                now=datetime(2026, 8, 13, 5, 10, 0),
            )


def test_shift_unknown_trip_raises(db_session):
    _seed(db_session)
    with pytest.raises(TripNotFoundError):
        service.shift_stop(db_session, "NOT_A_TRIP", "LUZ", "05:14:00")


def test_shift_unknown_station_raises(db_session):
    _seed(db_session)
    with pytest.raises(StationNotFoundError):
        service.shift_stop(db_session, "TRIP_BFU-RGS_050000", "NOT_A_STATION", "05:14:00")


def test_shift_earlier_than_upstream_departure_is_rejected(db_session):
    _seed(db_session)
    with pytest.raises(ChronologyViolationError):
        service.shift_stop(
            db_session, "TRIP_BFU-RGS_050000", "LUZ", "04:59:00",
            now=datetime(2026, 8, 13, 4, 59, 0),
        )


def test_shift_beyond_lookback_window_is_rejected(db_session):
    _seed(db_session)
    # BFU is scheduled for 05:00; "now" is 06:00, 60 minutes later, beyond the 15-minute default lookback.
    with pytest.raises(LookbackExceededError):
        service.shift_stop(
            db_session, "TRIP_BFU-RGS_050000", "BFU", "05:05:00",
            now=datetime(2026, 8, 13, 6, 0, 0),
        )


def test_shift_within_lookback_window_is_allowed(db_session):
    _seed(db_session)
    # BFU is scheduled for 05:00; "now" is 05:10, 10 minutes later, within the 15-minute default lookback.
    trip = service.shift_stop(
        db_session, "TRIP_BFU-RGS_050000", "BFU", "05:05:00",
        now=datetime(2026, 8, 13, 5, 10, 0),
    )
    assert trip.stops[0].time == "05:05:00"
