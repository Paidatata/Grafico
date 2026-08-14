from src import service
from src.db import init_db


def test_default_lookback_is_fifteen_minutes(db_session):
    init_db(db_session.get_bind())
    assert service.get_edit_lookback_minutes(db_session) == 15


def test_set_lookback_persists(db_session):
    init_db(db_session.get_bind())
    service.set_edit_lookback_minutes(db_session, 30)
    assert service.get_edit_lookback_minutes(db_session) == 30


def test_last_reset_date_starts_unset(db_session):
    init_db(db_session.get_bind())
    assert service.get_last_reset_date(db_session) is None


def test_last_reset_date_set_by_daily_reset(db_session):
    from datetime import datetime

    init_db(db_session.get_bind())
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 13, 3, 0, 0))
    assert service.get_last_reset_date(db_session) == "2026-08-13"
