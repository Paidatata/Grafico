import pytest
from datetime import datetime

from src import service
from src.db import init_db
from src.errors import TripNotFoundError
from src.schemas import TemplateImportStop, TemplateImportTrip


def _seed(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000",
            direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="RGS", time="05:30:00"),
            ],
        )
    ])


def test_reset_trip_restores_template_values_within_lookback(db_session):
    _seed(db_session)
    service.shift_stop(
        db_session, "TRIP_BFU-RGS_050000", "BFU", "05:05:00",
        now=datetime(2026, 8, 13, 5, 5, 0),
    )

    # "now" stays at 05:05:00 — the shifted stop (05:05:00) is 0 minutes old, well
    # within the default 15-minute lookback, so it must fully revert.
    trip = service.reset_trip(db_session, "TRIP_BFU-RGS_050000", now=datetime(2026, 8, 13, 5, 5, 0))

    assert trip.stops[0].time == "05:00:00"
    assert trip.stops[1].time == "05:30:00"


def test_reset_trip_leaves_stops_older_than_the_lookback_window_untouched(db_session):
    _seed(db_session)
    service.shift_stop(
        db_session, "TRIP_BFU-RGS_050000", "BFU", "05:05:00",
        now=datetime(2026, 8, 13, 5, 5, 0),
    )

    # "now" has moved to 06:00 — 55 minutes past the shifted 05:05:00 stop, beyond the
    # default 15-minute lookback. reset_trip must leave it exactly as shifted.
    trip = service.reset_trip(db_session, "TRIP_BFU-RGS_050000", now=datetime(2026, 8, 13, 6, 0, 0))

    assert trip.stops[0].time == "05:05:00"  # frozen, not reverted to 05:00:00


def test_reset_trip_undoes_a_recent_suppress_from_boundary(db_session):

    _seed(db_session)
    service.suppress_from(
        db_session, "TRIP_BFU-RGS_050000", "RGS",
        now=datetime(2026, 8, 13, 4, 30, 0),
    )
    trip = service.reset_trip(db_session, "TRIP_BFU-RGS_050000", now=datetime(2026, 8, 13, 4, 30, 0))
    assert trip.active_last_seq is None


def test_reset_trip_leaves_an_old_suppress_from_boundary_in_place(db_session):

    _seed(db_session)
    service.suppress_from(
        db_session, "TRIP_BFU-RGS_050000", "RGS",
        now=datetime(2026, 8, 13, 4, 30, 0),
    )
    trip = service.reset_trip(db_session, "TRIP_BFU-RGS_050000", now=datetime(2026, 8, 13, 6, 0, 0))
    assert trip.active_last_seq == 0  # still suppressed from RGS onward


def test_reset_unknown_trip_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(TripNotFoundError):
        service.reset_trip(db_session, "NOT_A_TRIP")
