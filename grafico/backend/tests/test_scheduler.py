from datetime import datetime

from src import service
from src.db import init_db
from src.scheduler import run_startup_catchup_if_needed, should_run_catchup


def test_should_run_catchup_when_never_reset():
    assert should_run_catchup(None, datetime(2026, 8, 13, 9, 0, 0)) is True


def test_should_run_catchup_when_reset_today():
    assert should_run_catchup("2026-08-13", datetime(2026, 8, 13, 9, 0, 0)) is False


def test_should_run_catchup_when_reset_yesterday():
    assert should_run_catchup("2026-08-12", datetime(2026, 8, 13, 9, 0, 0)) is True


def test_startup_catchup_resets_when_stale(db_session):
    from src.schemas import TemplateImportStop, TemplateImportTrip

    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000", direction="BFU-RGS",
            stops=[TemplateImportStop(station="BFU", time="05:00:00")],
        )
    ])
    # Explicitly set last_reset_date to yesterday to simulate server was down through yesterday's 03:00
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 13, 3, 0, 0))

    service.shift_stop(
        db_session, "TRIP_BFU-RGS_050000", "BFU", "05:20:00",
        now=datetime(2026, 8, 13, 5, 10, 0),
    )

    run_startup_catchup_if_needed(db_session, now=datetime(2026, 8, 14, 9, 0, 0))

    trip = service.get_trip(db_session, "TRIP_BFU-RGS_050000")
    assert trip.stops[0].time == "05:00:00"  # reset back to template, not the 05:20 live edit


def test_startup_catchup_skips_when_already_reset_today(db_session):
    init_db(db_session.get_bind())
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 13, 3, 0, 0))

    # No template/live data to disturb — just confirm this doesn't raise and doesn't re-touch last_reset_date oddly.
    run_startup_catchup_if_needed(db_session, now=datetime(2026, 8, 13, 9, 0, 0))
    assert service.get_last_reset_date(db_session) == "2026-08-13"
