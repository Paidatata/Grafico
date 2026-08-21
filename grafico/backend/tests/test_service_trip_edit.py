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
            trip_id="TRIP_BFU-RGS_050000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="LUZ", time="05:10:00"),
                TemplateImportStop(station="BAS", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:30:00"),
            ],
        )
    ])


def test_suppress_from_sets_active_last_seq_to_the_stop_before(db_session):
    _seed(db_session)
    trip = service.suppress_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 4, 30, 0))
    assert trip.active_last_seq == 1  # LUZ (index 1) stays active; BAS (2) and RGS (3) suppressed


def test_suppress_from_the_first_stop_is_a_full_cancellation(db_session):
    _seed(db_session)
    trip = service.suppress_from(db_session, "TRIP_BFU-RGS_050000", "BFU", now=datetime(2026, 8, 13, 4, 30, 0))
    assert trip.active_last_seq == -1


def test_suppress_from_beyond_lookback_raises(db_session):
    _seed(db_session)
    with pytest.raises(LookbackExceededError):
        service.suppress_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 6, 0, 0))


def test_suppress_from_unknown_station_raises(db_session):
    _seed(db_session)
    with pytest.raises(StationNotFoundError):
        service.suppress_from(db_session, "TRIP_BFU-RGS_050000", "NOT_A_STATION", now=datetime(2026, 8, 13, 4, 30, 0))


def test_suppress_from_unknown_trip_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(TripNotFoundError):
        service.suppress_from(db_session, "NOT_A_TRIP", "BFU")


def test_depart_from_sets_active_first_seq(db_session):
    _seed(db_session)
    trip = service.depart_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 4, 30, 0))
    assert trip.active_first_seq == 2
    assert trip.stops[0].station == "BFU"


def test_depart_from_backward_is_rejected(db_session):
    _seed(db_session)
    service.depart_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 4, 30, 0))
    with pytest.raises(ChronologyViolationError):
        service.depart_from(db_session, "TRIP_BFU-RGS_050000", "LUZ", now=datetime(2026, 8, 13, 4, 30, 0))


def test_depart_from_beyond_active_last_seq_is_rejected(db_session):
    _seed(db_session)
    service.suppress_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 4, 30, 0))
    with pytest.raises(ChronologyViolationError):
        service.depart_from(db_session, "TRIP_BFU-RGS_050000", "RGS", now=datetime(2026, 8, 13, 4, 30, 0))


def test_depart_from_beyond_lookback_raises(db_session):
    _seed(db_session)
    with pytest.raises(LookbackExceededError):
        service.depart_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 6, 0, 0))
