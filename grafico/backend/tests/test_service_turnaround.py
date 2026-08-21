import pytest

from src import service
from src.db import init_db
from src.errors import StationNotFoundError


def test_set_and_read_station_turnaround(db_session):
    init_db(db_session.get_bind())
    service.set_station_turnaround(db_session, "RGS", 600)

    schedule = service.get_live_schedule(db_session)
    assert schedule.station_turnarounds == {"RGS": 600}


def test_clearing_turnaround_removes_it_from_the_map(db_session):
    init_db(db_session.get_bind())
    service.set_station_turnaround(db_session, "RGS", 600)
    service.set_station_turnaround(db_session, "RGS", None)

    schedule = service.get_live_schedule(db_session)
    assert schedule.station_turnarounds == {}


def test_set_turnaround_on_unknown_station_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(StationNotFoundError):
        service.set_station_turnaround(db_session, "NOT_A_STATION", 600)
