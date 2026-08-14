import pytest
from datetime import datetime

from src import service
from src.db import init_db
from src.errors import ChronologyViolationError, LookbackExceededError, StationNotFoundError, TripNotFoundError
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
