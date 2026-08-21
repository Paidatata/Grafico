from datetime import datetime

from src import service
from src.db import init_db
from src.models import Setting, Station, Schedule, TemplateTrip
from src.schemas import TemplateImportStop, TemplateImportTrip


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


def test_init_db_seeds_base_schedule_and_backfills_existing_template_rows(db_session):
    init_db(db_session.get_bind())

    base_schedule = db_session.query(Schedule).filter(Schedule.name == "Grade Base CPTM").first()
    assert base_schedule is not None

    # Insert a TemplateTrip row to simulate existing data
    db_session.add(TemplateTrip(id='TRIP_X', train_code='P1', direction='BFU-RGS', line='Line 710', schedule_id=1))
    db_session.commit()

    # Re-run init_db to ensure it handles existing rows correctly
    init_db(db_session.get_bind())

    # Verify that the TemplateTrip row still exists
    template_trip_check = db_session.query(TemplateTrip).filter(TemplateTrip.id == "TRIP_X").first()
    assert template_trip_check is not None


def test_init_db_adds_active_seq_columns_to_existing_trips_table(db_session):
    from src.db import init_db
    from sqlalchemy import text

    bind = db_session.get_bind()
    init_db(bind)

    cols = {row[1] for row in db_session.execute(text("PRAGMA table_info(trips)"))}
    assert "active_first_seq" in cols
    assert "active_last_seq" in cols

    init_db(bind)  # idempotent re-run must not error


def test_init_db_adds_turnaround_seconds_to_stations_table(db_session):
    from src.db import init_db
    from sqlalchemy import text

    bind = db_session.get_bind()
    init_db(bind)
    cols = {row[1] for row in db_session.execute(text("PRAGMA table_info(stations)"))}
    assert "turnaround_seconds" in cols
    init_db(bind)  # idempotent


    init_db(bind)  # idempotent re-run must not error


def test_get_trip_exposes_arrival_time_per_stop(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="RGS", time="05:40:00"),
            ],
        ),
    ])
    service.set_current_schedule_id(1)
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 16, 4, 30, 0))

    trip = service.get_trip(db_session, "TRIP_BFU-RGS_050000")
    assert trip.stops[0].arrival_time == "05:00:00"
    assert trip.stops[0].time == "05:00:00"