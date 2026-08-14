import logging
from datetime import datetime

import pytest

from src import service
from src.db import init_db
from src.scheduler import run_daily_reset_job, run_startup_catchup_if_needed, should_run_catchup


def test_should_run_catchup_when_never_reset():
    assert should_run_catchup(None, datetime(2026, 8, 13, 9, 0, 0)) is True


def test_should_run_catchup_when_reset_today():
    assert should_run_catchup("2026-08-13", datetime(2026, 8, 13, 9, 0, 0)) is False


def test_should_run_catchup_when_reset_yesterday():
    assert should_run_catchup("2026-08-12", datetime(2026, 8, 13, 9, 0, 0)) is True


def test_no_catchup_on_restart_before_3am_after_yesterdays_reset():
    """A 02:00 restart is still inside the 2026-08-13 service day.

    Yesterday's 03:00 job already ran (last_reset_date == "2026-08-13"), so no
    reset may fire an hour early and wipe live edits on overnight trips.
    """
    assert should_run_catchup("2026-08-13", datetime(2026, 8, 14, 2, 0, 0)) is False


def test_catchup_on_restart_at_4am_without_a_reset_for_the_new_day():
    assert should_run_catchup("2026-08-13", datetime(2026, 8, 14, 4, 0, 0)) is True


def test_catchup_agrees_with_the_date_perform_daily_reset_writes(db_session):
    """should_run_catchup and perform_daily_reset must share one definition of "day"."""
    init_db(db_session.get_bind())
    reset_at = datetime(2026, 8, 14, 3, 0, 0)
    service.perform_daily_reset(db_session, now=reset_at)

    stored = service.get_last_reset_date(db_session)
    assert stored == "2026-08-14"
    # Later the same service day (including past midnight into 2026-08-15 02:00): no re-run.
    assert should_run_catchup(stored, datetime(2026, 8, 14, 23, 0, 0)) is False
    assert should_run_catchup(stored, datetime(2026, 8, 15, 1, 30, 0)) is False
    assert should_run_catchup(stored, datetime(2026, 8, 15, 3, 30, 0)) is True


def test_daily_reset_job_logs_and_reraises_on_failure(monkeypatch, caplog):
    """APScheduler swallows job exceptions, so the failure must at least reach the log."""
    def _boom(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("src.service.perform_daily_reset", _boom)

    with caplog.at_level(logging.ERROR, logger="src.scheduler"):
        with pytest.raises(RuntimeError):
            run_daily_reset_job()

    assert "Daily schedule reset failed" in caplog.text
    assert "database is locked" in caplog.text  # traceback captured via logger.exception


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
