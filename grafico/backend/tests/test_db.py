from src.db import init_db
from src.models import Setting, Station


def test_init_db_creates_tables_and_seeds_stations(db_session):
    init_db(db_session.get_bind())

    stations = db_session.query(Station).all()
    assert len(stations) == 32  # 15 on Line 10 + 17 on Line 7, per parser.py's station tables

    bfu = db_session.query(Station).filter(Station.id == "BFU").first()
    assert bfu.name == "Barra Funda"
    assert bfu.line == "Line 10"


def test_init_db_seeds_default_lookback_setting(db_session):
    init_db(db_session.get_bind())

    setting = db_session.query(Setting).filter(Setting.key == "edit_lookback_minutes").first()
    assert setting is not None
    assert setting.value == "15"


def test_init_db_is_idempotent(db_session):
    init_db(db_session.get_bind())
    init_db(db_session.get_bind())  # must not raise or duplicate stations

    stations = db_session.query(Station).all()
    assert len(stations) == 32
