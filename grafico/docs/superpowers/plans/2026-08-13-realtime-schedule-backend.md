# Real-Time Schedule Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the client-only schedule editing in `frontend/src/app.js` with a FastAPI + SQLite backend that is the sole authority for schedule data and time-propagation math, pushes live updates to every connected dispatcher over WebSocket, and resets the working schedule from an immutable template every day at 03:00.

**Architecture:** A new `backend/src/` FastAPI app (`app.py`) exposes REST endpoints backed by SQLAlchemy models over SQLite, plus a `/ws` WebSocket that broadcasts `trip_updated`/`schedule_reset` events. All propagation math (shifting a dragged stop's time and every downstream stop by the same delta) lives in one place — `backend/src/service.py` — instead of being duplicated per-browser, which is what caused the original drift bug. `frontend/src/app.js` is rewired to fetch/post through this API instead of managing its own copy of the schedule as truth. The FastAPI app also serves `frontend/src/` as static files, so there's one process, one origin, no CORS.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2.x, APScheduler, pytest + httpx (backend tests); unchanged vanilla HTML/CSS/JS frontend.

**Spec:** `docs/superpowers/specs/2026-08-13-realtime-schedule-backend-design.md`

## Global Constraints

- Backend is Python 3.12, stdlib + `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `apscheduler`, `httpx` (test-only), `pytest` (test-only) — see `backend/requirements.txt`.
- SQLite only this phase (no Postgres). Time values are stored and transmitted as `"HH:MM:SS"` strings everywhere, matching the existing `parser.py`/`data-model.md` convention — no datetime objects cross the API boundary.
- No authentication/user accounts this phase. No `edit_log` table this phase.
- The server is the sole authority for propagation math — the frontend never computes a final downstream shift itself; it always renders whatever the server returns.
- Frontend stays vanilla HTML/CSS/JS, no build step, no new frontend framework.
- Default `edit_lookback_minutes` is `15` if never configured.

---

## Task 1: Backend scaffolding — package layout, test harness, time helpers

**Files:**
- Create: `backend/src/__init__.py` (empty)
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/requirements.txt`
- Create: `backend/tests/conftest.py`
- Create: `backend/src/timeutils.py`
- Test: `backend/tests/test_timeutils.py`

**Interfaces:**
- Produces: `time_str_to_minutes(time_str: str) -> float`, `minutes_to_time_str(total_minutes: float) -> str` — used by every later task that touches schedule times.

- [ ] **Step 1: Create the package markers and requirements file**

`backend/src/__init__.py` — empty file.

`backend/tests/__init__.py` — empty file.

`backend/requirements.txt`:
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlalchemy==2.0.35
apscheduler==3.10.4
httpx==0.27.2
pytest==8.3.3
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r backend/requirements.txt`

- [ ] **Step 3: Write the test harness (`backend/tests/conftest.py`)**

This task only needs `sys.path` set up so `from src...` imports resolve — the DB-backed fixtures (`db_session`, `app_client`) are added to this same file in Tasks 2 and 7, once `src.db` and `src.app` actually exist. Adding them now would break this task's own tests: the fixtures below import `src.db`, which doesn't exist until Task 2.

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

Note for Task 2: this file gets *appended to*, not replaced, once `src/db.py` exists — see Task 2 Step 1.

- [ ] **Step 4: Write the failing test for time helpers**

`backend/tests/test_timeutils.py`:
```python
from src.timeutils import minutes_to_time_str, time_str_to_minutes


def test_time_str_to_minutes():
    assert time_str_to_minutes("00:00:00") == 0
    assert time_str_to_minutes("05:10:00") == 310
    assert time_str_to_minutes("05:10:30") == 310.5


def test_minutes_to_time_str():
    assert minutes_to_time_str(0) == "00:00:00"
    assert minutes_to_time_str(310) == "05:10:00"
    assert minutes_to_time_str(310.5) == "05:10:30"


def test_minutes_to_time_str_wraps_past_midnight():
    assert minutes_to_time_str(24 * 60) == "00:00:00"


def test_round_trip_preserves_value():
    for original in ["04:36:00", "23:59:59", "12:00:30"]:
        assert minutes_to_time_str(time_str_to_minutes(original)) == original
```

- [ ] **Step 5: Run it to confirm it fails**

Run: `pytest backend/tests/test_timeutils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.timeutils'` (or similar import error).

- [ ] **Step 6: Implement `backend/src/timeutils.py`**

```python
def time_str_to_minutes(time_str: str) -> float:
    hours, minutes, seconds = (int(part) for part in time_str.split(":"))
    return hours * 60 + minutes + seconds / 60


def minutes_to_time_str(total_minutes: float) -> str:
    total_seconds = round(total_minutes * 60)
    total_seconds %= 24 * 60 * 60
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
```

- [ ] **Step 7: Run the tests to confirm they pass**

Run: `pytest backend/tests/test_timeutils.py -v`
Expected: 4 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/requirements.txt backend/src/__init__.py backend/tests/__init__.py backend/tests/conftest.py backend/src/timeutils.py backend/tests/test_timeutils.py
git commit -m "feat: add backend scaffolding and shared time helpers"
```

---

## Task 2: Database engine and models

**Files:**
- Create: `backend/src/db.py`
- Create: `backend/src/models.py`
- Modify: `backend/tests/conftest.py` (append DB-backed fixtures)
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Base` (SQLAlchemy declarative base), `engine`, `SessionLocal`, `make_session_factory(db_path)`, `init_db(target_engine=None)` from `db.py`. `Station`, `TemplateTrip`, `TemplatePlannedStop`, `Trip`, `PlannedStop`, `RealizedEvent`, `Setting` ORM classes from `models.py`, each used by `service.py` in later tasks.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_db.py`:
```python
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
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest backend/tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.db'`.

- [ ] **Step 3: Implement `backend/src/models.py`**

```python
from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Station(Base):
    __tablename__ = "stations"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    y_coordinate = Column(Float, nullable=False)
    line = Column(String, nullable=False)


class TemplateTrip(Base):
    __tablename__ = "template_trips"
    id = Column(String, primary_key=True)
    train_code = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    line = Column(String, nullable=False)


class TemplatePlannedStop(Base):
    __tablename__ = "template_planned_stops"
    trip_id = Column(String, ForeignKey("template_trips.id", ondelete="CASCADE"), primary_key=True)
    station_id = Column(String, ForeignKey("stations.id"), primary_key=True)
    arrival_time = Column(String, nullable=False)
    departure_time = Column(String, nullable=False)
    sequence_order = Column(Integer, nullable=False)


class Trip(Base):
    __tablename__ = "trips"
    id = Column(String, primary_key=True)
    train_code = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    line = Column(String, nullable=False)


class PlannedStop(Base):
    __tablename__ = "planned_stops"
    trip_id = Column(String, ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True)
    station_id = Column(String, ForeignKey("stations.id"), primary_key=True)
    arrival_time = Column(String, nullable=False)
    departure_time = Column(String, nullable=False)
    sequence_order = Column(Integer, nullable=False)


class RealizedEvent(Base):
    __tablename__ = "realized_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_id = Column(String, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False)
    station_id = Column(String, ForeignKey("stations.id"), nullable=False)
    event_type = Column(String, nullable=False)
    actual_time = Column(String, nullable=False)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
```

Note this reuses exactly the table/column names from `specs/001-railway-traffic-chart/data-model.md` for `stations`/`trips`/`planned_stops`/`realized_events`, plus the two new `template_*` tables and `settings` described in the design doc.

- [ ] **Step 4: Implement `backend/src/db.py`**

```python
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base, Setting, Station

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "railway.db")

STATIONS_METADATA = [
    {"id": "RGS", "name": "Rio Grande da Serra", "y_coordinate": 500.32, "line": "Line 10"},
    {"id": "RPI", "name": "Ribeirão Pires", "y_coordinate": 1100.32, "line": "Line 10"},
    {"id": "GPT", "name": "Guapituba", "y_coordinate": 1660.32, "line": "Line 10"},
    {"id": "MAU", "name": "Mauá", "y_coordinate": 2100.32, "line": "Line 10"},
    {"id": "CPV", "name": "Capuava", "y_coordinate": 2500.32, "line": "Line 10"},
    {"id": "SAN", "name": "Santo André", "y_coordinate": 2980.32, "line": "Line 10"},
    {"id": "PSA", "name": "Prefeito Saladino", "y_coordinate": 3220.32, "line": "Line 10"},
    {"id": "UTG", "name": "Utinga", "y_coordinate": 3420.32, "line": "Line 10"},
    {"id": "SCS", "name": "São Caetano do Sul", "y_coordinate": 3860.32, "line": "Line 10"},
    {"id": "TMD", "name": "Tamanduateí", "y_coordinate": 4180.32, "line": "Line 10"},
    {"id": "IPG", "name": "Ipiranga", "y_coordinate": 4380.32, "line": "Line 10"},
    {"id": "MOC", "name": "Juventus-Mooca", "y_coordinate": 4740.32, "line": "Line 10"},
    {"id": "BAS", "name": "Brás", "y_coordinate": 4980.32, "line": "Line 10"},
    {"id": "LUZ", "name": "Luz", "y_coordinate": 5380.32, "line": "Line 10"},
    {"id": "BFU", "name": "Barra Funda", "y_coordinate": 5860.32, "line": "Line 10"},
    {"id": "LUZ_L7", "name": "Luz (L7)", "y_coordinate": 6180.32, "line": "Line 7"},
    {"id": "ABR", "name": "Água Branca", "y_coordinate": 6420.32, "line": "Line 7"},
    {"id": "LPA", "name": "Lapa", "y_coordinate": 6700.32, "line": "Line 7"},
    {"id": "PQR", "name": "Piqueri", "y_coordinate": 6980.32, "line": "Line 7"},
    {"id": "PRU", "name": "Pirituba", "y_coordinate": 7300.32, "line": "Line 7"},
    {"id": "VCL", "name": "Vila Clarice", "y_coordinate": 7500.32, "line": "Line 7"},
    {"id": "JRG", "name": "Jaraguá", "y_coordinate": 7900.32, "line": "Line 7"},
    {"id": "VPL", "name": "Vila Aurora", "y_coordinate": 8260.32, "line": "Line 7"},
    {"id": "PRT", "name": "Perus", "y_coordinate": 8700.32, "line": "Line 7"},
    {"id": "CAI", "name": "Caieiras", "y_coordinate": 9260.32, "line": "Line 7"},
    {"id": "FMO", "name": "Franco da Rocha", "y_coordinate": 9500.32, "line": "Line 7"},
    {"id": "BFI", "name": "Baltazar Fidélis", "y_coordinate": 9940.32, "line": "Line 7"},
    {"id": "FDR", "name": "Francisco Morato", "y_coordinate": 10300.32, "line": "Line 7"},
    {"id": "BTJ", "name": "Botujuru", "y_coordinate": 10580.32, "line": "Line 7"},
    {"id": "CLP", "name": "Campo Limpo Paulista", "y_coordinate": 10900.32, "line": "Line 7"},
    {"id": "VAU", "name": "Várzea Paulista", "y_coordinate": 11220.32, "line": "Line 7"},
    {"id": "JUN", "name": "Jundiaí", "y_coordinate": 11520.32, "line": "Line 7"},
]

DEFAULT_LOOKBACK_MINUTES = "15"


def make_session_factory(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


DB_PATH = os.environ.get("GRAFICO_DB_PATH", DEFAULT_DB_PATH)
engine, SessionLocal = make_session_factory(DB_PATH)


def init_db(target_engine=None) -> None:
    bind = target_engine or engine
    Base.metadata.create_all(bind)

    Session = sessionmaker(bind=bind)
    db = Session()
    try:
        if db.query(Station).count() == 0:
            for station in STATIONS_METADATA:
                db.add(Station(**station))

        if db.query(Setting).filter(Setting.key == "edit_lookback_minutes").first() is None:
            db.add(Setting(key="edit_lookback_minutes", value=DEFAULT_LOOKBACK_MINUTES))

        db.commit()
    finally:
        db.close()
```

`STATIONS_METADATA` is copied verbatim from the existing `backend/src/database.py` (which this backend replaces — removed in Task 9).

- [ ] **Step 5: Append the DB-backed test fixtures to `backend/tests/conftest.py`**

Now that `src/db.py` exists, add the fixtures that `test_db.py` (and every later test file) rely on. Append to the end of the existing `backend/tests/conftest.py` from Task 1 (don't remove the `sys.path` line already there):

```python
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _use_temp_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("data") / "test_railway.db"
    os.environ["GRAFICO_DB_PATH"] = str(db_path)
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    from src.db import Base, engine

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def db_session():
    from src.db import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

`_use_temp_db` is session-scoped and autouse, so it runs before the first test's imports touch `src.db`, guaranteeing `GRAFICO_DB_PATH` is set before that module's top-level `engine, SessionLocal = make_session_factory(DB_PATH)` line executes for the first time — this is what keeps tests off the real `backend/data/railway.db`. `_clean_tables` wipes every table's rows after each test for isolation, regardless of which fixture (`db_session` or, later, `app_client`) a test uses.

- [ ] **Step 6: Run the tests to confirm they pass**

Run: `pytest backend/tests -v`
Expected: all tests pass (both `test_timeutils.py` from Task 1 and `test_db.py`).

- [ ] **Step 7: Commit**

```bash
git add backend/src/db.py backend/src/models.py backend/tests/test_db.py backend/tests/conftest.py
git commit -m "feat: add SQLAlchemy models, database initialization, and DB test fixtures"
```

---

## Task 3: Schemas, errors, and read-side service functions

**Files:**
- Create: `backend/src/schemas.py`
- Create: `backend/src/errors.py`
- Create: `backend/src/service.py`
- Test: `backend/tests/test_service_schedule.py`

**Interfaces:**
- Consumes: `Base`, `Station`, `TemplateTrip`, `TemplatePlannedStop`, `Trip`, `PlannedStop`, `RealizedEvent`, `Setting` from `models.py` (Task 2).
- Produces: `TripNotFoundError`, `StationNotFoundError`, `ChronologyViolationError`, `LookbackExceededError` from `errors.py`. `StopOut`, `TripOut`, `ScheduleOut`, `TemplateImportStop`, `TemplateImportTrip`, `ShiftRequest`, `LookbackSetting` from `schemas.py`. `import_template(db, trips) -> int`, `perform_daily_reset(db, now=None) -> None`, `get_live_schedule(db) -> ScheduleOut`, `get_trip(db, trip_id) -> TripOut` from `service.py` — consumed by `app.py` (Task 7) and later `service.py` tasks (4-6).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_service_schedule.py`:
```python
from src import service
from src.db import init_db
from src.errors import TripNotFoundError
from src.schemas import TemplateImportStop, TemplateImportTrip

import pytest


def _sample_trips():
    return [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000",
            direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="LUZ", time="05:10:00"),
                TemplateImportStop(station="RGS", time="05:30:00"),
            ],
        )
    ]


def test_import_template_populates_live_schedule(db_session):
    init_db(db_session.get_bind())

    imported = service.import_template(db_session, _sample_trips())
    assert imported == 1

    schedule = service.get_live_schedule(db_session)
    assert len(schedule.trips) == 1
    trip = schedule.trips[0]
    assert trip.trip_id == "TRIP_BFU-RGS_050000"
    assert trip.start_time == "05:00:00"
    assert trip.end_time == "05:30:00"
    assert [s.station for s in trip.stops] == ["BFU", "LUZ", "RGS"]


def test_import_template_replaces_previous_template(db_session):
    init_db(db_session.get_bind())

    service.import_template(db_session, _sample_trips())
    service.import_template(db_session, _sample_trips())  # re-import must not duplicate

    schedule = service.get_live_schedule(db_session)
    assert len(schedule.trips) == 1


def test_get_trip_raises_when_missing(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, _sample_trips())

    with pytest.raises(TripNotFoundError):
        service.get_trip(db_session, "NOT_A_REAL_TRIP")


def test_perform_daily_reset_restores_live_from_template(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, _sample_trips())

    # Simulate a live edit, then reset and confirm it reverts.
    service.shift_stop(db_session, "TRIP_BFU-RGS_050000", "LUZ", "05:20:00")
    service.perform_daily_reset(db_session)

    trip = service.get_trip(db_session, "TRIP_BFU-RGS_050000")
    assert trip.stops[1].time == "05:10:00"  # back to template value
```

Note the last test calls `service.shift_stop`, which doesn't exist yet — that's expected, it's implemented in Task 4. This test will only pass once Task 4 is done; run it now to confirm the *other three* tests pass and this one fails for the *expected* reason (missing `shift_stop`), not for an unrelated bug.

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest backend/tests/test_service_schedule.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'src.service'` (or `src.schemas`/`src.errors`).

- [ ] **Step 3: Implement `backend/src/errors.py`**

```python
class TripNotFoundError(Exception):
    def __init__(self, trip_id: str):
        self.trip_id = trip_id
        super().__init__(f"Trip not found: {trip_id}")


class StationNotFoundError(Exception):
    def __init__(self, station_id: str):
        self.station_id = station_id
        super().__init__(f"Station not found on trip: {station_id}")


class ChronologyViolationError(Exception):
    pass


class LookbackExceededError(Exception):
    pass
```

- [ ] **Step 4: Implement `backend/src/schemas.py`**

```python
from typing import List, Optional

from pydantic import BaseModel


class StopOut(BaseModel):
    station: str
    time: str


class TripOut(BaseModel):
    trip_id: str
    direction: str
    start_time: str
    end_time: str
    stops: List[StopOut]


class ScheduleOut(BaseModel):
    trips: List[TripOut]


class TemplateImportStop(BaseModel):
    station: str
    time: str


class TemplateImportTrip(BaseModel):
    trip_id: str
    direction: str
    stops: List[TemplateImportStop]


class ShiftRequest(BaseModel):
    trip_id: str
    station_id: str
    new_time: str


class LookbackSetting(BaseModel):
    edit_lookback_minutes: int
```

`TemplateImportTrip`/`TemplateImportStop` intentionally don't declare `start_time`/`end_time`/`x_coord`/`y_coord` — Pydantic v2 ignores unknown fields by default, so uploading `parser.py`'s `schedule.json` verbatim (which has those extra fields) still works; the server only needs `station` and `time` per stop.

- [ ] **Step 5: Implement the read-side of `backend/src/service.py`**

```python
from datetime import datetime

from sqlalchemy.orm import Session

from . import models
from .errors import TripNotFoundError
from .schemas import ScheduleOut, StopOut, TemplateImportTrip, TripOut

DEFAULT_LOOKBACK_MINUTES = 15


def import_template(db: Session, trips: list[TemplateImportTrip]) -> int:
    db.query(models.TemplatePlannedStop).delete()
    db.query(models.TemplateTrip).delete()

    for trip in trips:
        train_code = trip.trip_id.split("_")[-1]
        db.add(models.TemplateTrip(
            id=trip.trip_id, train_code=train_code, direction=trip.direction, line="Line 710",
        ))
        for idx, stop in enumerate(trip.stops):
            db.add(models.TemplatePlannedStop(
                trip_id=trip.trip_id, station_id=stop.station,
                arrival_time=stop.time, departure_time=stop.time, sequence_order=idx,
            ))

    db.commit()
    perform_daily_reset(db)
    return len(trips)


def perform_daily_reset(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.now()

    db.query(models.RealizedEvent).delete()
    db.query(models.PlannedStop).delete()
    db.query(models.Trip).delete()
    db.flush()

    for template_trip in db.query(models.TemplateTrip).all():
        db.add(models.Trip(
            id=template_trip.id, train_code=template_trip.train_code,
            direction=template_trip.direction, line=template_trip.line,
        ))

    for template_stop in db.query(models.TemplatePlannedStop).all():
        db.add(models.PlannedStop(
            trip_id=template_stop.trip_id, station_id=template_stop.station_id,
            arrival_time=template_stop.arrival_time, departure_time=template_stop.departure_time,
            sequence_order=template_stop.sequence_order,
        ))

    _set_setting(db, "last_reset_date", now.strftime("%Y-%m-%d"))
    db.commit()


def _trip_stops(db: Session, trip_id: str) -> list[models.PlannedStop]:
    return (
        db.query(models.PlannedStop)
        .filter(models.PlannedStop.trip_id == trip_id)
        .order_by(models.PlannedStop.sequence_order)
        .all()
    )


def get_live_schedule(db: Session) -> ScheduleOut:
    trips_out = []
    for trip in db.query(models.Trip).all():
        stops = _trip_stops(db, trip.id)
        if not stops:
            continue
        trips_out.append(_trip_to_out(trip, stops))
    return ScheduleOut(trips=trips_out)


def get_trip(db: Session, trip_id: str) -> TripOut:
    stops = _trip_stops(db, trip_id)
    if not stops:
        raise TripNotFoundError(trip_id)
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    return _trip_to_out(trip, stops)


def _trip_to_out(trip: models.Trip, stops: list[models.PlannedStop]) -> TripOut:
    return TripOut(
        trip_id=trip.id,
        direction=trip.direction,
        start_time=stops[0].departure_time,
        end_time=stops[-1].departure_time,
        stops=[StopOut(station=s.station_id, time=s.departure_time) for s in stops],
    )


def _set_setting(db: Session, key: str, value: str) -> None:
    setting = db.query(models.Setting).filter(models.Setting.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(models.Setting(key=key, value=value))
```

`shift_stop`, `reset_trip`, and the settings getters/setters referenced by other tasks are added in Tasks 4-6 — this task only needs the read/import/reset-all path to satisfy its own test file.

- [ ] **Step 6: Run the tests**

Run: `pytest backend/tests/test_service_schedule.py -v`
Expected: 3 passed, 1 failed (`test_perform_daily_reset_restores_live_from_template`, with `AttributeError: module 'src.service' has no attribute 'shift_stop'`). This is the expected, documented gap closed by Task 4 — confirm no *other* failures.

- [ ] **Step 7: Commit**

```bash
git add backend/src/schemas.py backend/src/errors.py backend/src/service.py backend/tests/test_service_schedule.py
git commit -m "feat: add schemas, errors, and template import/reset/read service functions"
```

---

## Task 4: Shift propagation — the core bug fix

**Files:**
- Modify: `backend/src/service.py`
- Test: `backend/tests/test_service_shift.py`

**Interfaces:**
- Consumes: `_trip_stops`, `_trip_to_out`, `get_trip`, `get_edit_lookback_minutes` (this task adds the latter as a minimal stub if Task 6 hasn't run yet — see Step 3) from `service.py`; `time_str_to_minutes`/`minutes_to_time_str` from `timeutils.py` (Task 1).
- Produces: `shift_stop(db, trip_id, station_id, new_time, now=None) -> TripOut` — consumed by `app.py` (Task 7) and by `test_service_schedule.py`'s reset test (Task 3).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_service_shift.py`:
```python
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
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest backend/tests/test_service_shift.py -v`
Expected: FAIL with `AttributeError: module 'src.service' has no attribute 'shift_stop'`.

- [ ] **Step 3: Implement `shift_stop` and `get_edit_lookback_minutes` in `backend/src/service.py`**

Add to `backend/src/service.py` (after the existing functions):

```python
from .errors import ChronologyViolationError, LookbackExceededError, StationNotFoundError
from .timeutils import minutes_to_time_str, time_str_to_minutes


def get_edit_lookback_minutes(db: Session) -> int:
    setting = db.query(models.Setting).filter(models.Setting.key == "edit_lookback_minutes").first()
    return int(setting.value) if setting else DEFAULT_LOOKBACK_MINUTES


def shift_stop(
    db: Session, trip_id: str, station_id: str, new_time: str, now: datetime | None = None,
) -> TripOut:
    now = now or datetime.now()
    stops = _trip_stops(db, trip_id)
    if not stops:
        raise TripNotFoundError(trip_id)

    idx = next((i for i, s in enumerate(stops) if s.station_id == station_id), None)
    if idx is None:
        raise StationNotFoundError(station_id)

    target = stops[idx]
    new_minutes = time_str_to_minutes(new_time)

    if idx > 0:
        upstream_minutes = time_str_to_minutes(stops[idx - 1].departure_time)
        if new_minutes < upstream_minutes:
            raise ChronologyViolationError(
                f"{new_time} is earlier than upstream stop departure {stops[idx - 1].departure_time}"
            )

    lookback_minutes = get_edit_lookback_minutes(db)
    current_minutes = time_str_to_minutes(target.departure_time)
    now_minutes = now.hour * 60 + now.minute + now.second / 60
    if (now_minutes - current_minutes) > lookback_minutes:
        raise LookbackExceededError(
            f"Stop at {target.departure_time} is more than {lookback_minutes} minutes in the past"
        )

    delta = new_minutes - current_minutes

    for stop in stops[idx:]:
        stop.arrival_time = minutes_to_time_str(time_str_to_minutes(stop.arrival_time) + delta)
        stop.departure_time = minutes_to_time_str(time_str_to_minutes(stop.departure_time) + delta)

    db.commit()
    return get_trip(db, trip_id)
```

Move the `from .errors import ...` and `from .timeutils import ...` lines up to the top of the file alongside the existing imports rather than inline — inline imports shown here only to make the diff obvious.

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `pytest backend/tests/test_service_shift.py backend/tests/test_service_schedule.py -v`
Expected: all passed, including the previously-blocked `test_perform_daily_reset_restores_live_from_template` from Task 3.

- [ ] **Step 5: Commit**

```bash
git add backend/src/service.py backend/tests/test_service_shift.py
git commit -m "feat: compute schedule shift propagation server-side"
```

---

## Task 5: Per-trip reset

**Files:**
- Modify: `backend/src/service.py`
- Test: `backend/tests/test_service_reset.py`

**Interfaces:**
- Consumes: `_trip_stops`, `get_trip` from `service.py`.
- Produces: `reset_trip(db, trip_id) -> TripOut` — consumed by `app.py` (Task 7).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_service_reset.py`:
```python
import pytest

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
    service.shift_stop(db_session, "TRIP_BFU-RGS_050000", "BFU", "05:05:00")

    trip = service.reset_trip(db_session, "TRIP_BFU-RGS_050000")

    assert trip.stops[0].time == "05:00:00"
    assert trip.stops[1].time == "05:30:00"


def test_reset_unknown_trip_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(TripNotFoundError):
        service.reset_trip(db_session, "NOT_A_TRIP")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest backend/tests/test_service_reset.py -v`
Expected: FAIL with `AttributeError: module 'src.service' has no attribute 'reset_trip'`.

- [ ] **Step 3: Implement `reset_trip` in `backend/src/service.py`**

```python
def reset_trip(db: Session, trip_id: str) -> TripOut:
    template_stops = (
        db.query(models.TemplatePlannedStop)
        .filter(models.TemplatePlannedStop.trip_id == trip_id)
        .order_by(models.TemplatePlannedStop.sequence_order)
        .all()
    )
    if not template_stops:
        raise TripNotFoundError(trip_id)

    live_stops = {stop.station_id: stop for stop in _trip_stops(db, trip_id)}
    for template_stop in template_stops:
        live_stop = live_stops.get(template_stop.station_id)
        if live_stop is not None:
            live_stop.arrival_time = template_stop.arrival_time
            live_stop.departure_time = template_stop.departure_time
            live_stop.sequence_order = template_stop.sequence_order

    db.commit()
    return get_trip(db, trip_id)
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `pytest backend/tests/test_service_reset.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/service.py backend/tests/test_service_reset.py
git commit -m "feat: add per-trip reset to template values"
```

---

## Task 6: Settings read/write

**Files:**
- Modify: `backend/src/service.py`
- Test: `backend/tests/test_service_settings.py`

**Interfaces:**
- Produces: `set_edit_lookback_minutes(db, minutes) -> None`, `get_last_reset_date(db) -> str | None` — `get_edit_lookback_minutes` already exists from Task 4. Consumed by `app.py` (Task 7) and `scheduler.py` (Task 8).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_service_settings.py`:
```python
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
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest backend/tests/test_service_settings.py -v`
Expected: FAIL with `AttributeError: module 'src.service' has no attribute 'set_edit_lookback_minutes'` (the other two/three tests involving only `get_edit_lookback_minutes` and `perform_daily_reset` should already pass since those exist from Tasks 3-4 — confirm that).

- [ ] **Step 3: Implement the remaining setting functions in `backend/src/service.py`**

```python
def set_edit_lookback_minutes(db: Session, minutes: int) -> None:
    _set_setting(db, "edit_lookback_minutes", str(minutes))
    db.commit()


def get_last_reset_date(db: Session) -> str | None:
    setting = db.query(models.Setting).filter(models.Setting.key == "last_reset_date").first()
    return setting.value if setting else None
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `pytest backend/tests/test_service_settings.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/service.py backend/tests/test_service_settings.py
git commit -m "feat: add settings read/write for edit lookback and last reset date"
```

---

## Task 7: FastAPI app — REST endpoints, WebSocket, static frontend

**Files:**
- Create: `backend/src/ws_manager.py`
- Create: `backend/src/app.py`
- Modify: `backend/tests/conftest.py` (append `app_client` fixture)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: everything in `service.py` (Tasks 3-6), `errors.py` (Task 3), `schemas.py` (Task 3), `db.py`'s `SessionLocal`/`init_db` (Task 2).
- Produces: the FastAPI `app` object — consumed by `scheduler.py`'s startup wiring (Task 8) and by running `uvicorn src.app:app` directly.

- [ ] **Step 1: Append the `app_client` fixture to `backend/tests/conftest.py`**

Now that `src/app.py` will exist by the end of this task, add the fixture `test_api.py` needs. Append to `backend/tests/conftest.py`:

```python
@pytest.fixture()
def app_client():
    from fastapi.testclient import TestClient
    from src.app import app

    with TestClient(app) as client:
        yield client
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_api.py`:
```python
def test_get_schedule_empty_when_nothing_imported(app_client):
    response = app_client.get("/api/schedule")
    assert response.status_code == 200
    assert response.json() == {"trips": []}


def test_import_then_get_schedule(app_client):
    payload = [
        {
            "trip_id": "TRIP_BFU-RGS_050000",
            "direction": "BFU-RGS",
            "stops": [
                {"station": "BFU", "time": "05:00:00"},
                {"station": "RGS", "time": "05:30:00"},
            ],
        }
    ]
    import_response = app_client.post("/api/template/import", json=payload)
    assert import_response.status_code == 200
    assert import_response.json() == {"imported_trips": 1}

    schedule_response = app_client.get("/api/schedule")
    trips = schedule_response.json()["trips"]
    assert len(trips) == 1
    assert trips[0]["trip_id"] == "TRIP_BFU-RGS_050000"


def test_shift_stop_endpoint_propagates_downstream(app_client):
    payload = [
        {
            "trip_id": "TRIP_BFU-RGS_050000",
            "direction": "BFU-RGS",
            "stops": [
                {"station": "BFU", "time": "05:00:00"},
                {"station": "RGS", "time": "05:30:00"},
            ],
        }
    ]
    app_client.post("/api/template/import", json=payload)

    response = app_client.post("/api/stops/shift", json={
        "trip_id": "TRIP_BFU-RGS_050000", "station_id": "BFU", "new_time": "05:03:00",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["stops"][0]["time"] == "05:03:00"
    assert body["stops"][1]["time"] == "05:33:00"


def test_shift_stop_unknown_trip_returns_404(app_client):
    response = app_client.post("/api/stops/shift", json={
        "trip_id": "NOT_A_TRIP", "station_id": "BFU", "new_time": "05:03:00",
    })
    assert response.status_code == 404


def test_reset_trip_endpoint(app_client):
    payload = [
        {
            "trip_id": "TRIP_BFU-RGS_050000",
            "direction": "BFU-RGS",
            "stops": [{"station": "BFU", "time": "05:00:00"}],
        }
    ]
    app_client.post("/api/template/import", json=payload)
    app_client.post("/api/stops/shift", json={
        "trip_id": "TRIP_BFU-RGS_050000", "station_id": "BFU", "new_time": "05:05:00",
    })

    response = app_client.post("/api/trips/TRIP_BFU-RGS_050000/reset")
    assert response.status_code == 200
    assert response.json()["stops"][0]["time"] == "05:00:00"


def test_lookback_setting_round_trip(app_client):
    put_response = app_client.put("/api/settings/edit-lookback-minutes", json={"edit_lookback_minutes": 45})
    assert put_response.status_code == 200

    get_response = app_client.get("/api/settings/edit-lookback-minutes")
    assert get_response.json() == {"edit_lookback_minutes": 45}


def test_websocket_receives_trip_updated_broadcast(app_client):
    payload = [
        {
            "trip_id": "TRIP_BFU-RGS_050000",
            "direction": "BFU-RGS",
            "stops": [{"station": "BFU", "time": "05:00:00"}],
        }
    ]
    app_client.post("/api/template/import", json=payload)

    with app_client.websocket_connect("/ws") as websocket:
        app_client.post("/api/stops/shift", json={
            "trip_id": "TRIP_BFU-RGS_050000", "station_id": "BFU", "new_time": "05:05:00",
        })
        message = websocket.receive_json()
        assert message["type"] == "trip_updated"
        assert message["trip"]["stops"][0]["time"] == "05:05:00"
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `pytest backend/tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.app'`.

- [ ] **Step 4: Implement `backend/src/ws_manager.py`**

```python
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for websocket in self.active:
            try:
                await websocket.send_json(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)
```

- [ ] **Step 5: Implement `backend/src/app.py`**

```python
from pathlib import Path

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import service
from .db import SessionLocal, init_db
from .errors import ChronologyViolationError, LookbackExceededError, StationNotFoundError, TripNotFoundError
from .schemas import LookbackSetting, ScheduleOut, ShiftRequest, TemplateImportTrip, TripOut
from .ws_manager import ConnectionManager

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "src"

app = FastAPI(title="Grafico Railway Schedule API")
manager = ConnectionManager()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.exception_handler(TripNotFoundError)
def _trip_not_found(request, exc: TripNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(StationNotFoundError)
def _station_not_found(request, exc: StationNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ChronologyViolationError)
def _chronology_violation(request, exc: ChronologyViolationError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(LookbackExceededError)
def _lookback_exceeded(request, exc: LookbackExceededError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/schedule", response_model=ScheduleOut)
def get_schedule(db: Session = Depends(get_db)):
    return service.get_live_schedule(db)


@app.post("/api/template/import")
async def import_template(trips: list[TemplateImportTrip], db: Session = Depends(get_db)):
    count = service.import_template(db, trips)
    await manager.broadcast({"type": "schedule_reset"})
    return {"imported_trips": count}


@app.post("/api/stops/shift", response_model=TripOut)
async def shift_stop(payload: ShiftRequest, db: Session = Depends(get_db)):
    trip = service.shift_stop(db, payload.trip_id, payload.station_id, payload.new_time)
    await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return trip


@app.post("/api/trips/{trip_id}/reset", response_model=TripOut)
async def reset_trip(trip_id: str, db: Session = Depends(get_db)):
    trip = service.reset_trip(db, trip_id)
    await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return trip


@app.get("/api/settings/edit-lookback-minutes", response_model=LookbackSetting)
def get_lookback(db: Session = Depends(get_db)):
    return LookbackSetting(edit_lookback_minutes=service.get_edit_lookback_minutes(db))


@app.put("/api/settings/edit-lookback-minutes", response_model=LookbackSetting)
def put_lookback(payload: LookbackSetting, db: Session = Depends(get_db)):
    service.set_edit_lookback_minutes(db, payload.edit_lookback_minutes)
    return payload


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
```

The static mount is registered last on purpose — Starlette matches routes in registration order, so `/api/...` and `/ws` must exist before the catch-all `/` mount or they'd be shadowed by it.

- [ ] **Step 6: Run the tests to confirm they pass**

Run: `pytest backend/tests/test_api.py -v`
Expected: 7 passed.

- [ ] **Step 7: Run the full backend test suite**

Run: `pytest backend/tests -v`
Expected: all tests across all files pass.

- [ ] **Step 8: Commit**

```bash
git add backend/src/ws_manager.py backend/src/app.py backend/tests/test_api.py backend/tests/conftest.py
git commit -m "feat: add FastAPI app with REST endpoints, WebSocket broadcast, and static frontend hosting"
```

---

## Task 8: Daily reset scheduler and startup catch-up

**Files:**
- Create: `backend/src/scheduler.py`
- Modify: `backend/src/app.py`
- Test: `backend/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `service.perform_daily_reset`, `service.get_last_reset_date` (Tasks 3, 6).
- Produces: `should_run_catchup(last_reset_date, now) -> bool`, `run_startup_catchup_if_needed(db) -> None`, `start_scheduler() -> AsyncIOScheduler` — wired into `app.py`'s startup event.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_scheduler.py`:
```python
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
    service.shift_stop(db_session, "TRIP_BFU-RGS_050000", "BFU", "05:20:00")

    run_startup_catchup_if_needed(db_session, now=datetime(2026, 8, 14, 9, 0, 0))

    trip = service.get_trip(db_session, "TRIP_BFU-RGS_050000")
    assert trip.stops[0].time == "05:00:00"  # reset back to template, not the 05:20 live edit


def test_startup_catchup_skips_when_already_reset_today(db_session):
    init_db(db_session.get_bind())
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 13, 3, 0, 0))

    # No template/live data to disturb — just confirm this doesn't raise and doesn't re-touch last_reset_date oddly.
    run_startup_catchup_if_needed(db_session, now=datetime(2026, 8, 13, 9, 0, 0))
    assert service.get_last_reset_date(db_session) == "2026-08-13"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest backend/tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.scheduler'`.

- [ ] **Step 3: Implement `backend/src/scheduler.py`**

```python
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from . import service
from .db import SessionLocal


def should_run_catchup(last_reset_date: str | None, now: datetime) -> bool:
    return last_reset_date != now.strftime("%Y-%m-%d")


def run_startup_catchup_if_needed(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.now()
    if should_run_catchup(service.get_last_reset_date(db), now):
        service.perform_daily_reset(db, now=now)


def run_daily_reset_job() -> None:
    db = SessionLocal()
    try:
        service.perform_daily_reset(db)
    finally:
        db.close()


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_daily_reset_job, CronTrigger(hour=3, minute=0))
    scheduler.start()
    return scheduler
```

- [ ] **Step 4: Run the scheduler tests to confirm they pass**

Run: `pytest backend/tests/test_scheduler.py -v`
Expected: 5 passed.

- [ ] **Step 5: Wire the catch-up and scheduler into `backend/src/app.py`'s startup event**

Replace the existing `on_startup` function:

```python
from .scheduler import run_startup_catchup_if_needed, start_scheduler


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        run_startup_catchup_if_needed(db)
    finally:
        db.close()
    app.state.scheduler = start_scheduler()
```

(Add the `from .scheduler import ...` line to the top imports of `app.py` alongside the existing ones.)

- [ ] **Step 6: Run the full backend test suite to confirm nothing broke**

Run: `pytest backend/tests -v`
Expected: all tests pass, including `test_api.py` (the app still starts up correctly with the scheduler wired in — `TestClient`'s context manager triggers the startup event, so this exercises the real code path).

- [ ] **Step 7: Commit**

```bash
git add backend/src/scheduler.py backend/src/app.py backend/tests/test_scheduler.py
git commit -m "feat: add daily 03:00 reset scheduler with startup catch-up"
```

---

## Task 9: Retire the old seeder script and stale database file

**Files:**
- Delete: `backend/src/database.py`
- Delete: `backend/data/railway.db` (stale, pre-dates the template/live schema split)
- Create: `.gitignore`
- Modify: `specs/001-railway-traffic-chart/quickstart.md`

**Interfaces:** None — this task only removes dead code and updates docs.

- [ ] **Step 1: Delete the superseded seeder script**

`backend/src/database.py` is fully replaced by `backend/src/db.py` (station/settings seeding) and `backend/src/service.py` (`import_template`/`perform_daily_reset`, which now do what the old script's `seed_schedule_from_json` did, but against the new template/live split).

```bash
git rm backend/src/database.py
```

- [ ] **Step 2: Remove the stale pre-migration database file**

It was seeded by the now-deleted script against the old flat schema (no `template_*`/`settings` tables) and would otherwise sit alongside the new schema with orphaned data.

```bash
git rm backend/data/railway.db
```

- [ ] **Step 3: Add `.gitignore` so the live database and Python caches stop being tracked**

`.gitignore` (repo root, i.e. `Grafico/grafico/.gitignore`):
```
backend/data/*.db
__pycache__/
*.pyc
```

- [ ] **Step 4: Update `specs/001-railway-traffic-chart/quickstart.md`**

Replace the "Launch Frontend Time-Distance Graphic" section (steps 3 in the existing file) with:

```markdown
## 3. Start the Backend Server

```bash
pip install -r backend/requirements.txt
uvicorn backend.src.app:app --reload --host 0.0.0.0 --port 8000
```

The server creates `backend/data/railway.db` on first run and seeds it with station data.

## 4. Import the Schedule and Open the Chart

1. Open `http://<server-host>:8000/` in a browser (any machine on the network, not just the server itself).
2. Click **"Importar JSON"** and select `backend/data/schedule.json` (generated in step 1). This uploads it as the day's template baseline via `POST /api/template/import`, which also populates today's live schedule.
3. Verify the time-distance grid renders with stations on the vertical axis and times on the horizontal axis, with train lines plotted as dashed lines.
4. Drag a station node — the dragged node and every downstream stop on that trip shift by the same amount, computed and persisted by the backend. Open the page in a second browser tab (or from another machine) to see the edit appear there live over the WebSocket connection.
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore specs/001-railway-traffic-chart/quickstart.md
git commit -m "chore: remove superseded seeder script and stale database, update quickstart"
```

---

## Task 10: Frontend wiring — talk to the backend instead of local state

**Files:**
- Modify: `frontend/src/app.js`
- Modify: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `GET /api/schedule`, `POST /api/template/import`, `POST /api/stops/shift`, `POST /api/trips/{id}/reset`, `GET/PUT /api/settings/edit-lookback-minutes`, `WS /ws` (Task 7).

- [ ] **Step 1: Replace `loadDefaultSchedule` and remove the local-only fallback**

In `frontend/src/app.js`, replace:

```javascript
function loadDefaultSchedule() {
    // Attempt to fetch schedule.json relative to the page location
    fetch("../data/schedule.json")
        .then(response => {
            if (!response.ok) throw new Error("File not found");
            return response.json();
        })
        .then(data => {
            initSchedule(data);
        })
        .catch(err => {
            console.warn("Could not load schedule.json via fetch (normal for local file:// opening). Using fallback mock schedule.", err);
            initSchedule(fallbackSchedule);
        });
}
```

with:

```javascript
function loadDefaultSchedule() {
    fetch("/api/schedule")
        .then(response => {
            if (!response.ok) throw new Error("Server returned " + response.status);
            return response.json();
        })
        .then(data => {
            initSchedule(data.trips);
            connectLiveUpdates();
            loadLookbackSetting();
        })
        .catch(err => {
            console.error("Could not reach the schedule server.", err);
            document.getElementById("chart-container").innerHTML =
                '<p style="padding: 40px; color: var(--text-secondary);">Não foi possível conectar ao servidor. Verifique se o backend está rodando.</p>';
        });
}
```

Delete the `fallbackSchedule` and `mockRealizedData` variable's *use* in `loadDefaultSchedule` only — `mockRealizedData` itself stays (still used by the "Mostrar Realizado" mock toggle, per the design doc's decision to keep that mocked this phase). `fallbackSchedule` is now fully unused; delete its declaration too (lines 134-165 in the original file).

- [ ] **Step 2: Remove the client-side `originalTrips` backup and `resetToOriginal`, replace with a server-backed per-trip reset**

Replace:

```javascript
function resetToOriginal() {
    if (confirm("Deseja reverter todas as alterações e carregar a grade original?")) {
        appState.trips = JSON.parse(JSON.stringify(appState.originalTrips));
        renderApp();
    }
}
```

with:

```javascript
function resetToOriginal() {
    if (!appState.selectedTripId) {
        alert("Selecione um trem para resetar.");
        return;
    }
    if (!confirm("Deseja reverter este trem para a grade padrão?")) return;

    fetch(`/api/trips/${encodeURIComponent(appState.selectedTripId)}/reset`, { method: "POST" })
        .then(response => {
            if (!response.ok) throw new Error("Reset failed: " + response.status);
            return response.json();
        })
        .then(updatedTrip => {
            applyTripUpdate(updatedTrip);
        })
        .catch(err => {
            alert("Não foi possível resetar o trem: " + err.message);
        });
}
```

Also remove `appState.originalTrips = JSON.parse(JSON.stringify(data));` from `initSchedule` and the `originalTrips: []` entry from the `appState` object literal — nothing reads it anymore now that reset is server-backed. Also remove the now-orphaned reference to `originalTrips` inside `onNodeDrag`'s propagation loop, since that whole function is replaced in Step 4 below.

- [ ] **Step 3: Add `applyTripUpdate`, `connectLiveUpdates`, and `loadLookbackSetting` helpers**

Add near `initSchedule`:

```javascript
function applyTripUpdate(updatedTrip) {
    const idx = appState.trips.findIndex(t => t.trip_id === updatedTrip.trip_id);
    if (idx >= 0) {
        appState.trips[idx] = updatedTrip;
    } else {
        appState.trips.push(updatedTrip);
    }
    renderApp();
}

function connectLiveUpdates() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

    socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "trip_updated") {
            if (appState.dragNode && appState.dragNode.tripId === message.trip.trip_id) return;
            applyTripUpdate(message.trip);
        } else if (message.type === "schedule_reset") {
            fetch("/api/schedule")
                .then(response => response.json())
                .then(data => {
                    appState.trips = data.trips;
                    renderApp();
                });
        }
    };

    socket.onclose = () => {
        setTimeout(connectLiveUpdates, 3000);
    };
}

function loadLookbackSetting() {
    fetch("/api/settings/edit-lookback-minutes")
        .then(response => response.json())
        .then(data => {
            appState.editLookbackMinutes = data.edit_lookback_minutes;
        });
}
```

Add `editLookbackMinutes: 15` to the `appState` object literal's initial definition as a sane default before the fetch resolves.

- [ ] **Step 4: Rewrite the drag-end handler to commit through the server, and gate dragging by the lookback window**

Replace `onNodeDragEnd`:

```javascript
function onNodeDragEnd(e) {
    if (!appState.dragNode) return;

    const { tripId, stopIdx, element } = appState.dragNode;
    element.classList.remove("dragging");

    const trip = appState.trips.find(t => t.trip_id === tripId);
    const stationId = trip.stops[stopIdx].station;
    const newTime = trip.stops[stopIdx].time;

    fetch("/api/stops/shift", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trip_id: tripId, station_id: stationId, new_time: newTime }),
    })
        .then(response => {
            if (!response.ok) return response.json().then(body => Promise.reject(new Error(body.detail)));
            return response.json();
        })
        .then(updatedTrip => {
            applyTripUpdate(updatedTrip);
        })
        .catch(err => {
            alert("Edição rejeitada pelo servidor: " + err.message);
            fetch("/api/schedule")
                .then(response => response.json())
                .then(data => {
                    appState.trips = data.trips;
                    renderApp();
                });
        });

    appState.dragNode = null;
    hideTooltip();
}
```

During the drag itself (`onNodeDrag`), the existing client-side preview math stays exactly as-is — it's still valuable for smooth visual feedback while dragging. What changes is that the preview is no longer the final word: on release, the server recomputes the authoritative shift from its own stored state and every client (including this one) renders that response via `applyTripUpdate`. This is what removes the drift between the dragged node and its downstream neighbors, since only one implementation (the server's) ever produces the value that gets persisted and rendered after the gesture ends.

Add a lookback guard where circles are created, inside `drawTrainPaths`'s `if (isSelected)` block — replace:

```javascript
                const circle = document.createElementNS(SVG_NS, "circle");
                circle.setAttribute("cx", px);
                circle.setAttribute("cy", py);
                circle.setAttribute("r", 5);
                circle.className.baseVal = "time-node";

                // Add drag events
                circle.addEventListener("mousedown", (e) => onNodeDragStart(e, trip.trip_id, stopIdx));
```

with:

```javascript
                const circle = document.createElementNS(SVG_NS, "circle");
                circle.setAttribute("cx", px);
                circle.setAttribute("cy", py);
                circle.setAttribute("r", 5);

                const nowMinutes = new Date().getHours() * 60 + new Date().getMinutes();
                const stopMinutes = timeStrToMinutes(stop.time);
                const isLocked = (nowMinutes - stopMinutes) > appState.editLookbackMinutes;

                circle.className.baseVal = isLocked ? "time-node locked" : "time-node";
                if (!isLocked) {
                    circle.addEventListener("mousedown", (e) => onNodeDragStart(e, trip.trip_id, stopIdx));
                }
```

- [ ] **Step 5: Add the `.time-node.locked` style to `frontend/src/index.css`**

Add after the existing `.time-node.dragging` rule:

```css
.time-node.locked {
    fill: var(--text-muted);
    stroke: rgba(107, 114, 128, 0.4);
    cursor: not-allowed;
}
```

- [ ] **Step 6: Repurpose `handleFileUpload` to upload to the template-import endpoint**

Replace:

```javascript
function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const data = JSON.parse(e.target.result);
            initSchedule(data);
        } catch (err) {
            alert("Erro ao ler JSON: Formato inválido.");
        }
    };
    reader.readAsText(file);
}
```

with:

```javascript
function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        let data;
        try {
            data = JSON.parse(e.target.result);
        } catch (err) {
            alert("Erro ao ler JSON: Formato inválido.");
            return;
        }

        fetch("/api/template/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        })
            .then(response => {
                if (!response.ok) throw new Error("Import failed: " + response.status);
                return response.json();
            })
            .then(() => fetch("/api/schedule"))
            .then(response => response.json())
            .then(scheduleData => {
                initSchedule(scheduleData.trips);
                alert(`Grade padrão importada com sucesso.`);
            })
            .catch(err => {
                alert("Não foi possível importar a grade: " + err.message);
            });
    };
    reader.readAsText(file);
}
```

- [ ] **Step 7: Manually verify against a running backend**

Run: `uvicorn backend.src.app:app --reload` (from `backend/`, or `uvicorn backend.src.app:app --reload --app-dir ..` from repo root — match whichever matches your Task 9 quickstart wording), then open `http://localhost:8000/` in two browser tabs.
Expected: both tabs load the same schedule; importing `backend/data/schedule.json` in one tab populates both; dragging a node in one tab updates the other tab within roughly a second; dragging a node older than the lookback window (default 15 minutes in the past) renders it non-draggable (grey, `cursor: not-allowed`).

- [ ] **Step 8: Update `frontend/tests/manual_test.md` with the new scenarios**

Add a new section at the end of the file:

```markdown
## Cenário 5: Sincronização em Tempo Real Entre Despachantes

1. Abra `http://<servidor>:8000/` em duas abas (ou dois navegadores/máquinas diferentes).
2. Na aba A, arraste um nó de horário e solte.
3. Confirme que a aba B reflete a mesma alteração em até poucos segundos, sem precisar recarregar a página.

## Cenário 6: Janela de Retroação (Lookback)

1. Localize um trem com uma parada cujo horário já passou há mais tempo que o valor configurado em "edit_lookback_minutes" (15 minutos por padrão).
2. Confirme que o nó dessa parada aparece acinzentado e não é arrastável (cursor "not-allowed").
3. Confirme que paradas dentro da janela permitida continuam arrastáveis normalmente.

## Cenário 7: Servidor Indisponível

1. Pare o processo do backend (`uvicorn`).
2. Recarregue a página do gráfico.
3. Confirme que uma mensagem clara de erro de conexão aparece, em vez de silenciosamente carregar dados fictícios.
```

- [ ] **Step 9: Commit**

```bash
git add frontend/src/app.js frontend/src/index.css frontend/tests/manual_test.md
git commit -m "feat: wire frontend to backend API and WebSocket, add lookback-gated dragging"
```

---

## Task 11: Update CLAUDE.md for the new architecture

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the Commands and Architecture sections**

The current `CLAUDE.md` states "the frontend is entirely client-side and does not talk to `database.py` or SQLite" and describes running `frontend/src/index.html` directly. Both are now false. Update:

- The **Commands** section: add `pip install -r backend/requirements.txt` and `uvicorn backend.src.app:app --reload` as the way to run the app; note the frontend is now served by the backend at `http://localhost:8000/`, not opened as a local file; add `pytest backend/tests -v` alongside the existing parser test command.
- The **Architecture** section: replace the "frontend is entirely client-side" paragraph with a description of the FastAPI backend as the source of truth (`backend/src/app.py`, `service.py`, `models.py`, `db.py`, `scheduler.py`, `ws_manager.py`), the template/live schedule split, the WebSocket-based live sync, and the fact that `database.py` no longer exists (superseded).
- Remove the "Repo layout quirk" note's implication that nothing reads `backend/data/railway.db` — it's now the live database.

Write the updated file directly (no fixed snippet given here — read the current `CLAUDE.md`, and edit the two sections in place following the guidance above; keep the rest, including the DXF/station-table duplication note and the nested-path note, since those remain accurate).

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for the FastAPI backend architecture"
```

---

## Plan Self-Review Notes

- **Spec coverage:** data model (Task 2), template import (Task 3), shift propagation + validation (Task 4), per-trip reset (Task 5), settings (Task 6), REST + WebSocket API (Task 7), daily reset + startup catch-up (Task 8), old-code retirement (Task 9), frontend wiring incl. lookback-gated dragging and live sync (Task 10), docs (Task 11). All spec sections are covered.
- **Type consistency:** `TripOut`/`StopOut` (Task 3) are used identically by `service.py` (Tasks 3-6), `app.py` (Task 7), and the frontend's expectation of `{trip_id, direction, start_time, end_time, stops: [{station, time}]}` (Task 10) — verified consistent across all tasks.
- **Fixed during self-review:** Task 4's test file originally had a duplicate/malformed test around the chronology-violation case; it now contains exactly one correct version (`test_shift_earlier_than_upstream_departure_is_rejected`).
