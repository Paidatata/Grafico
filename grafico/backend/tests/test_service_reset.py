import pytest
from datetime import datetime

from src import service
from src.db import init_db
from src.errors import TripNotFoundError
from src.schemas import TemplateImportStop, TemplateImportTrip


def test_reset_trip_restores_template_values(db_session):
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
    service.shift_stop(
        db_session, "TRIP_BFU-RGS_050000", "BFU", "05:05:00",
        now=datetime(2026, 8, 13, 5, 5, 0),
    )

    trip = service.reset_trip(db_session, "TRIP_BFU-RGS_050000")

    assert trip.stops[0].time == "05:00:00"
    assert trip.stops[1].time == "05:30:00"


def test_reset_unknown_trip_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(TripNotFoundError):
        service.reset_trip(db_session, "NOT_A_TRIP")
