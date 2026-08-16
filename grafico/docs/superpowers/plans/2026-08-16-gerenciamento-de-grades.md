# Gerenciamento de Grades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a dispatcher create horário grades from scratch, store multiple named grades in the database, and load any of them into today's live operation — replacing the single hardcoded "Base CPTM" template with a first-class, manageable concept.

**Architecture:** A new `schedules` table becomes the parent of `template_trips`/`template_planned_stops` (via a new `schedule_id` column on both). The server tracks which schedule is "loaded for today" as an in-process module-level variable (`service.get_current_schedule_id()`), not persisted — a restart requires the operator to reload a schedule, and the 03:00 reset becomes a no-op until they do. The frontend gains a second top-level view ("Grades") alongside the existing "Operacional" view, sharing the same SVG chart-rendering code in read-only mode, plus two new reusable UI primitives (a generic dialog and a generic right-click context menu) that later specs (2a, 2b, 3, 4) also depend on.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), vanilla JS/SVG single-file frontend (no framework, no bundler), pytest + FastAPI TestClient (backend tests only — this repo has no frontend test runner; frontend tasks are verified manually against `frontend/tests/manual_test.md` conventions).

**Spec:** `docs/superpowers/specs/2026-08-15-gerenciamento-de-grades-design.md`

## Global Constraints

- `current_schedule_id` lives in memory only (a module-level variable), never in the DB — a server restart clears it and the daily reset becomes a no-op until an operator reloads a schedule.
- `trips`/`planned_stops` (live tables) never get a `schedule_id` column — they always represent "today", sourced from whichever schedule was last loaded.
- The migration must not destroy the existing single implicit grade: on first run against an existing DB, create `schedules.id=1, name='Grade Base CPTM'` and backfill every existing `template_trips`/`template_planned_stops` row to `schedule_id=1`.
- `POST /api/template/import` (the existing DXF-import endpoint) keeps writing to `schedule_id=1` specifically — it is the "Grade Base CPTM" regeneration path and this spec does not change that contract.
- Renumbering groups trips by destination side, matching the app's existing odd/even convention (`frontend/src/app.js` `getOddTrips`/`getEvenTrips`, header labels "Sentido BFU (Ímpares)" / "Sentido RGS/Mauá (Pares)"): a trip whose **last stop** is `BFU` is in the odd group (`P1, P3, P5…`); any other last stop is in the even group (`R2, R4, R6…`). The letter used for each individual trip is whatever prefix that trip's own `train_code` already carries (parsed via `^([A-Za-z]+)(\d+)$`), not hardcoded to P/R — only the numeric suffix is reassigned. A batch-created trip's prefix comes from the mandatory "Prefixo" field the operator typed at creation time.

---

## File Structure

**Backend (all under `backend/src/`):**
- `models.py` — modify: add `Schedule`, add `schedule_id` to `TemplateTrip` and `TemplatePlannedStop`
- `db.py` — modify: migrate existing DBs (create schedule 1, backfill `schedule_id`)
- `errors.py` — modify: add `ScheduleNotFoundError`, `DuplicateScheduleNameError`, `LastScheduleDeletionError`
- `schemas.py` — modify: add `ScheduleOut`, `ScheduleCreate`, `ScheduleRename`, `TripBatchCreate`, `StopOffset`, `TripPrefixUpdate`
- `service.py` — modify: add schedule CRUD, batch creation, renumbering, prefix update, load-to-today, current-schedule-id accessors; modify `perform_daily_reset` to filter by current schedule and no-op when unset; modify `import_template` to target `schedule_id=1`
- `app.py` — modify: register the new endpoints and exception handlers
- `scheduler.py` — modify: startup catch-up also respects "no schedule loaded → no-op"

**Backend tests (all under `backend/tests/`):**
- `test_service_schedules.py` — new: CRUD, clone, rename, delete-guard, renumber, batch-create, load
- `test_api_schedules.py` — new: the same behaviors through the HTTP layer
- `test_scheduler.py` — modify: add the "no schedule loaded → no-op" case
- `test_db.py` — modify: add migration/backfill assertions

**Frontend (all under `frontend/src/`):**
- `app.js` — modify: mode switching, generic dialog, generic context menu, Grades view rendering, batch-creation flow, prefix editing, load-to-today
- `index.html` — modify: mode tab buttons, Grades view container, dialog/context-menu root elements
- `index.css` — modify: styles for mode tabs, Grades view, dialog, context menu

**Frontend manual tests:**
- `frontend/tests/manual_test.md` — modify: add scenarios for every new interaction

---

### Task 1: `Schedule` model, migration, and in-memory current-schedule state

**Files:**
- Modify: `backend/src/models.py`
- Modify: `backend/src/db.py`
- Modify: `backend/src/service.py`
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Produces: `models.Schedule` (`id`, `name`, `created_at`, `last_loaded_at`), `TemplateTrip.schedule_id`, `TemplatePlannedStop.schedule_id`
- Produces: `service.get_current_schedule_id() -> int | None`, `service.set_current_schedule_id(schedule_id: int | None) -> None`

- [ ] **Step 1: Write the failing migration test**

```python
# backend/tests/test_db.py — add to the existing file
def test_init_db_seeds_base_schedule_and_backfills_existing_template_rows(db_session):
    from src.db import init_db
    from src import models

    bind = db_session.get_bind()
    init_db(bind)

    base = db_session.query(models.Schedule).filter(models.Schedule.name == "Grade Base CPTM").first()
    assert base is not None
    assert base.id == 1

    # Insert a template row the old way (as if migrating from a pre-schedule DB) and
    # re-run init_db — it must backfill schedule_id instead of erroring.
    db_session.add(models.TemplateTrip(
        id="TRIP_X", train_code="P1", direction="BFU-RGS", line="Line 710", schedule_id=1,
    ))
    db_session.commit()

    init_db(bind)  # idempotent: re-running must not duplicate the base schedule
    assert db_session.query(models.Schedule).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_db.py::test_init_db_seeds_base_schedule_and_backfills_existing_template_rows -v`
Expected: FAIL with `AttributeError: module 'src.models' has no attribute 'Schedule'`

- [ ] **Step 3: Add the `Schedule` model and `schedule_id` columns**

In `backend/src/models.py`, add near the top (after `Base = declarative_base()`):

```python
from sqlalchemy import DateTime
from datetime import datetime


class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    last_loaded_at = Column(DateTime, nullable=True)
```

Modify `TemplateTrip` and `TemplatePlannedStop` to add:

```python
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
```

(add this line to both classes, after their existing columns).

- [ ] **Step 4: Add the migration/backfill logic to `init_db`**

In `backend/src/db.py`, modify `init_db` — after `Base.metadata.create_all(bind)` and before the existing `Station`/`Setting` seeding block, insert:

```python
        from sqlalchemy import text

        if db.query(Schedule).filter(Schedule.name == "Grade Base CPTM").first() is None:
            db.add(Schedule(id=1, name="Grade Base CPTM"))
            db.flush()

        # SQLite ADD COLUMN is a no-op error if the column already exists — guard with
        # a pragma check so this migration step is safe to run on every startup.
        existing_cols = {row[1] for row in db.execute(text("PRAGMA table_info(template_trips)"))}
        if "schedule_id" not in existing_cols:
            db.execute(text("ALTER TABLE template_trips ADD COLUMN schedule_id INTEGER"))
        existing_cols = {row[1] for row in db.execute(text("PRAGMA table_info(template_planned_stops)"))}
        if "schedule_id" not in existing_cols:
            db.execute(text("ALTER TABLE template_planned_stops ADD COLUMN schedule_id INTEGER"))

        db.execute(text("UPDATE template_trips SET schedule_id = 1 WHERE schedule_id IS NULL"))
        db.execute(text("UPDATE template_planned_stops SET schedule_id = 1 WHERE schedule_id IS NULL"))
```

Add `from .models import Base, Schedule, Setting, Station` (add `Schedule` to the existing import line at the top of `db.py`).

Note: `Base.metadata.create_all` already creates `schedule_id` as a column with the model's `nullable=False` constraint for a **brand-new** database (fresh `create_all` sees the model as already having the column, so the `ALTER TABLE` branch above only fires for a database that existed before this migration — the `PRAGMA table_info` guard makes both cases safe).

- [ ] **Step 5: Add in-memory current-schedule accessors**

In `backend/src/service.py`, add near the top (module-level, after imports):

```python
_current_schedule_id: int | None = None


def get_current_schedule_id() -> int | None:
    return _current_schedule_id


def set_current_schedule_id(schedule_id: int | None) -> None:
    global _current_schedule_id
    _current_schedule_id = schedule_id
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest backend/tests/test_db.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/models.py backend/src/db.py backend/src/service.py backend/tests/test_db.py
git commit -m "feat: add Schedule model, migrate existing template rows to a default schedule"
```

---

### Task 2: List and create schedules

**Files:**
- Modify: `backend/src/schemas.py`
- Modify: `backend/src/service.py`
- Modify: `backend/src/app.py`
- Test: `backend/tests/test_service_schedules.py` (new)
- Test: `backend/tests/test_api_schedules.py` (new)

**Interfaces:**
- Consumes: `models.Schedule` (Task 1)
- Produces: `service.list_schedules(db) -> list[ScheduleOut]`, `service.create_schedule(db, name: str) -> ScheduleOut`
- Produces: `GET /api/schedules`, `POST /api/schedules`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_schedules.py — new file
import pytest
from datetime import datetime

from src import service
from src.db import init_db
from src.errors import DuplicateScheduleNameError


def test_list_schedules_includes_the_seeded_base_schedule(db_session):
    init_db(db_session.get_bind())
    schedules = service.list_schedules(db_session)
    assert len(schedules) == 1
    assert schedules[0].name == "Grade Base CPTM"


def test_create_schedule_adds_a_new_empty_schedule(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    assert created.name == "Grade Pico"

    names = {s.name for s in service.list_schedules(db_session)}
    assert names == {"Grade Base CPTM", "Grade Pico"}


def test_create_schedule_with_duplicate_name_raises(db_session):
    init_db(db_session.get_bind())
    service.create_schedule(db_session, "Grade Pico")
    with pytest.raises(DuplicateScheduleNameError):
        service.create_schedule(db_session, "Grade Pico")
```

```python
# backend/tests/test_api_schedules.py — new file
def test_get_schedules_lists_base_schedule(app_client):
    response = app_client.get("/api/schedules")
    assert response.status_code == 200
    names = {s["name"] for s in response.json()}
    assert "Grade Base CPTM" in names


def test_post_schedules_creates_new_schedule(app_client):
    response = app_client.post("/api/schedules", json={"name": "Grade Pico"})
    assert response.status_code == 200
    assert response.json()["name"] == "Grade Pico"


def test_post_schedules_duplicate_name_returns_400(app_client):
    app_client.post("/api/schedules", json={"name": "Grade Pico"})
    response = app_client.post("/api/schedules", json={"name": "Grade Pico"})
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_schedules.py backend/tests/test_api_schedules.py -v`
Expected: FAIL — `service.list_schedules` does not exist.

- [ ] **Step 3: Add the error type**

In `backend/src/errors.py`, add:

```python
class DuplicateScheduleNameError(Exception):
    """A schedule name is not unique (maps to 400)."""


class ScheduleNotFoundError(Exception):
    def __init__(self, schedule_id: int):
        self.schedule_id = schedule_id
        super().__init__(f"Schedule not found: {schedule_id}")


class LastScheduleDeletionError(Exception):
    """Refuses to delete the only remaining schedule (maps to 400)."""
```

- [ ] **Step 4: Add the schema**

In `backend/src/schemas.py`, add:

```python
from datetime import datetime as _datetime


class ScheduleOut(BaseModel):
    id: int
    name: str
    created_at: _datetime
    last_loaded_at: Optional[_datetime] = None

    class Config:
        from_attributes = True


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1)
```

- [ ] **Step 5: Implement the service functions**

In `backend/src/service.py`, add:

```python
from sqlalchemy.exc import IntegrityError

from .schemas import ScheduleCreate, ScheduleOut  # add to existing schemas import


def list_schedules(db: Session) -> list[ScheduleOut]:
    return [
        ScheduleOut.model_validate(s)
        for s in db.query(models.Schedule).order_by(models.Schedule.id).all()
    ]


def create_schedule(db: Session, name: str) -> ScheduleOut:
    schedule = models.Schedule(name=name)
    db.add(schedule)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateScheduleNameError(f"Schedule name already exists: {name!r}")
    db.refresh(schedule)
    return ScheduleOut.model_validate(schedule)
```

Add `DuplicateScheduleNameError` to the existing `from .errors import (...)` block in `service.py`.

- [ ] **Step 6: Wire the endpoints**

In `backend/src/app.py`, add the exception handler and endpoints:

```python
@app.exception_handler(DuplicateScheduleNameError)
def _duplicate_schedule_name(request, exc: DuplicateScheduleNameError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/schedules", response_model=list[ScheduleOut])
def get_schedules(db: Session = Depends(get_db)):
    return service.list_schedules(db)


@app.post("/api/schedules", response_model=ScheduleOut)
def post_schedule(payload: ScheduleCreate, db: Session = Depends(get_db)):
    return service.create_schedule(db, payload.name)
```

Add `DuplicateScheduleNameError` and `ScheduleOut`/`ScheduleCreate` to the existing import blocks at the top of `app.py`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_schedules.py backend/tests/test_api_schedules.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/schemas.py backend/src/service.py backend/src/app.py backend/src/errors.py backend/tests/test_service_schedules.py backend/tests/test_api_schedules.py
git commit -m "feat: list and create schedules"
```

---

### Task 3: Get a schedule's trips

**Files:**
- Modify: `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_schedules.py`, `backend/tests/test_api_schedules.py`

**Interfaces:**
- Consumes: `models.TemplateTrip.schedule_id`, `models.TemplatePlannedStop.schedule_id` (Task 1)
- Produces: `service.get_schedule_trips(db, schedule_id: int) -> ScheduleOut` (reuses the existing `schemas.ScheduleOut` shape from `TripOut`/`ScheduleOut` used by `/api/schedule` — **note this is a different `ScheduleOut`** than Task 2's; see Step 3)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_schedules.py — append
from src.schemas import TemplateImportStop, TemplateImportTrip


def _seed_named_schedule(db_session, name="Grade Pico"):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, name)
    db_session.add(models.TemplateTrip(
        id="TRIP_X", train_code="P1", direction="BFU-RGS", line="Line 710",
        schedule_id=created.id,
    ))
    db_session.add(models.TemplatePlannedStop(
        trip_id="TRIP_X", station_id="BFU", arrival_time="05:00:00",
        departure_time="05:00:00", sequence_order=0, schedule_id=created.id,
    ))
    db_session.add(models.TemplatePlannedStop(
        trip_id="TRIP_X", station_id="RGS", arrival_time="05:30:00",
        departure_time="05:30:00", sequence_order=1, schedule_id=created.id,
    ))
    db_session.commit()
    return created.id


def test_get_schedule_trips_returns_only_that_schedules_trips(db_session):
    from src import models
    schedule_id = _seed_named_schedule(db_session)

    result = service.get_schedule_trips(db_session, schedule_id)
    assert len(result.trips) == 1
    assert result.trips[0].trip_id == "TRIP_X"

    base_result = service.get_schedule_trips(db_session, 1)
    assert base_result.trips == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_service_schedules.py::test_get_schedule_trips_returns_only_that_schedules_trips -v`
Expected: FAIL — `AttributeError: module 'src.service' has no attribute 'get_schedule_trips'`

- [ ] **Step 3: Implement `get_schedule_trips`**

In `backend/src/service.py`, add (reuses the existing `_trip_to_out`/`_station_y_lookup` helpers, but reads from the template tables instead of the live ones — factor the shared shape out):

```python
def get_schedule_trips(db: Session, schedule_id: int) -> ScheduleOut:
    station_y = _station_y_lookup(db)
    trips_out = []
    for trip in db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == schedule_id).all():
        stops = (
            db.query(models.TemplatePlannedStop)
            .filter(models.TemplatePlannedStop.trip_id == trip.id)
            .order_by(models.TemplatePlannedStop.sequence_order)
            .all()
        )
        if not stops:
            continue
        trips_out.append(TripOut(
            trip_id=trip.id,
            direction=trip.direction,
            train_code=trip.train_code,
            start_time=stops[0].departure_time,
            end_time=stops[-1].departure_time,
            stops=[
                StopOut(station=s.station_id, time=s.departure_time, y_coord=station_y.get(s.station_id, 0.0))
                for s in stops
            ],
        ))
    return ScheduleOut(trips=trips_out)
```

This reuses `schemas.ScheduleOut`/`TripOut`/`StopOut` — the **same** classes `/api/schedule` already returns, distinct from Task 2's new `schemas.ScheduleOut` for the schedules list. Rename Task 2's response schema to avoid the collision: in `schemas.py`, rename Task 2's class to `ScheduleMetaOut` and update every reference (Task 2's `service.py`/`app.py` code above, and its tests) accordingly.

- [ ] **Step 4: Wire the endpoint**

In `backend/src/app.py`:

```python
@app.get("/api/schedules/{schedule_id}/trips", response_model=ScheduleOut)
def get_schedule_trips(schedule_id: int, db: Session = Depends(get_db)):
    return service.get_schedule_trips(db, schedule_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_schedules.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/schemas.py backend/src/service.py backend/src/app.py backend/tests/test_service_schedules.py
git commit -m "feat: fetch a single schedule's template trips"
```

---

### Task 4: Rename and delete schedules

**Files:**
- Modify: `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_schedules.py`, `backend/tests/test_api_schedules.py`

**Interfaces:**
- Produces: `service.rename_schedule(db, schedule_id: int, name: str) -> ScheduleMetaOut`, `service.delete_schedule(db, schedule_id: int) -> None`
- Produces: `PATCH /api/schedules/{id}`, `DELETE /api/schedules/{id}`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_schedules.py — append
from src.errors import LastScheduleDeletionError, ScheduleNotFoundError


def test_rename_schedule(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    renamed = service.rename_schedule(db_session, created.id, "Grade Pico Renomeada")
    assert renamed.name == "Grade Pico Renomeada"


def test_rename_unknown_schedule_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(ScheduleNotFoundError):
        service.rename_schedule(db_session, 999, "X")


def test_delete_schedule(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    service.delete_schedule(db_session, created.id)
    assert [s.name for s in service.list_schedules(db_session)] == ["Grade Base CPTM"]


def test_delete_the_only_remaining_schedule_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(LastScheduleDeletionError):
        service.delete_schedule(db_session, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_schedules.py -k "rename or delete" -v`
Expected: FAIL — functions don't exist.

- [ ] **Step 3: Implement**

In `backend/src/service.py`:

```python
def _get_schedule_or_raise(db: Session, schedule_id: int) -> models.Schedule:
    schedule = db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
    if schedule is None:
        raise ScheduleNotFoundError(schedule_id)
    return schedule


def rename_schedule(db: Session, schedule_id: int, name: str) -> ScheduleMetaOut:
    schedule = _get_schedule_or_raise(db, schedule_id)
    schedule.name = name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateScheduleNameError(f"Schedule name already exists: {name!r}")
    db.refresh(schedule)
    return ScheduleMetaOut.model_validate(schedule)


def delete_schedule(db: Session, schedule_id: int) -> None:
    _get_schedule_or_raise(db, schedule_id)
    if db.query(models.Schedule).count() <= 1:
        raise LastScheduleDeletionError("Cannot delete the only remaining schedule")
    db.query(models.TemplatePlannedStop).filter(models.TemplatePlannedStop.schedule_id == schedule_id).delete()
    db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == schedule_id).delete()
    db.query(models.Schedule).filter(models.Schedule.id == schedule_id).delete()
    db.commit()
```

Add `ScheduleNotFoundError`, `LastScheduleDeletionError` to `service.py`'s error imports.

- [ ] **Step 4: Wire the endpoints**

In `backend/src/app.py`:

```python
@app.exception_handler(ScheduleNotFoundError)
def _schedule_not_found(request, exc: ScheduleNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(LastScheduleDeletionError)
def _last_schedule_deletion(request, exc: LastScheduleDeletionError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.patch("/api/schedules/{schedule_id}", response_model=ScheduleMetaOut)
def patch_schedule(schedule_id: int, payload: ScheduleCreate, db: Session = Depends(get_db)):
    return service.rename_schedule(db, schedule_id, payload.name)


@app.delete("/api/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    service.delete_schedule(db, schedule_id)
    return {"deleted": schedule_id}
```

(`ScheduleCreate`'s `{"name": ...}` shape is reused for rename — same payload shape, no need for a separate `ScheduleRename` schema; drop that class from the plan's File Structure list.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_schedules.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/service.py backend/src/app.py backend/src/errors.py backend/tests/test_service_schedules.py
git commit -m "feat: rename and delete schedules"
```

---

### Task 5: Clone schedule ("Salvar Como")

**Files:**
- Modify: `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_schedules.py`

**Interfaces:**
- Produces: `service.clone_schedule(db, schedule_id: int, new_name: str) -> ScheduleMetaOut`
- Produces: `POST /api/schedules/{id}/clone`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_service_schedules.py — append
def test_clone_schedule_copies_trips_and_stops(db_session):
    from src import models
    schedule_id = _seed_named_schedule(db_session, "Grade Pico")

    cloned = service.clone_schedule(db_session, schedule_id, "Grade Pico Copia")
    assert cloned.name == "Grade Pico Copia"

    cloned_trips = service.get_schedule_trips(db_session, cloned.id)
    assert len(cloned_trips.trips) == 1
    assert cloned_trips.trips[0].trip_id == "TRIP_X"  # same trip_id, different schedule_id
    assert len(cloned_trips.trips[0].stops) == 2

    # Original schedule's trips are untouched
    original_trips = service.get_schedule_trips(db_session, schedule_id)
    assert len(original_trips.trips) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_service_schedules.py::test_clone_schedule_copies_trips_and_stops -v`
Expected: FAIL — `clone_schedule` does not exist.

- [ ] **Step 3: Implement**

In `backend/src/service.py`:

```python
def clone_schedule(db: Session, schedule_id: int, new_name: str) -> ScheduleMetaOut:
    _get_schedule_or_raise(db, schedule_id)
    new_schedule = models.Schedule(name=new_name)
    db.add(new_schedule)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise DuplicateScheduleNameError(f"Schedule name already exists: {new_name!r}")

    for trip in db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == schedule_id).all():
        db.add(models.TemplateTrip(
            id=trip.id, train_code=trip.train_code, direction=trip.direction,
            line=trip.line, schedule_id=new_schedule.id,
        ))
    for stop in db.query(models.TemplatePlannedStop).filter(models.TemplatePlannedStop.schedule_id == schedule_id).all():
        db.add(models.TemplatePlannedStop(
            trip_id=stop.trip_id, station_id=stop.station_id, arrival_time=stop.arrival_time,
            departure_time=stop.departure_time, sequence_order=stop.sequence_order,
            schedule_id=new_schedule.id,
        ))
    db.commit()
    db.refresh(new_schedule)
    return ScheduleMetaOut.model_validate(new_schedule)
```

- [ ] **Step 4: Wire the endpoint**

In `backend/src/app.py`:

```python
@app.post("/api/schedules/{schedule_id}/clone", response_model=ScheduleMetaOut)
def clone_schedule(schedule_id: int, payload: ScheduleCreate, db: Session = Depends(get_db)):
    return service.clone_schedule(db, schedule_id, payload.name)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_service_schedules.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/service.py backend/src/app.py backend/tests/test_service_schedules.py
git commit -m "feat: clone a schedule (Salvar Como)"
```

---

### Task 6: Renumber schedule

**Files:**
- Modify: `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_schedules.py`

**Interfaces:**
- Produces: `service.renumber_schedule(db, schedule_id: int) -> ScheduleOut` (the trips-shape `ScheduleOut`, so the frontend can redraw immediately)
- Produces: `POST /api/schedules/{id}/renumber`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_schedules.py — append
def _add_template_trip(db_session, schedule_id, trip_id, train_code, direction, first_station, first_time):
    from src import models
    db_session.add(models.TemplateTrip(
        id=trip_id, train_code=train_code, direction=direction, line="Line 710", schedule_id=schedule_id,
    ))
    db_session.add(models.TemplatePlannedStop(
        trip_id=trip_id, station_id=first_station, arrival_time=first_time,
        departure_time=first_time, sequence_order=0, schedule_id=schedule_id,
    ))
    db_session.commit()


def test_renumber_assigns_sequential_odd_numbers_to_bfu_terminating_trips(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    # Both trips end at BFU (direction RGS-BFU) => odd group. Later departure gets the higher number.
    _add_template_trip(db_session, created.id, "T2", "P99", "RGS-BFU", "SAN", "06:00:00")
    _add_template_trip(db_session, created.id, "T1", "P1", "RGS-BFU", "SAN", "05:00:00")

    result = service.renumber_schedule(db_session, created.id)
    codes_by_trip = {t.trip_id: t.train_code for t in result.trips}
    assert codes_by_trip["T1"] == "P1"   # earlier departure -> smaller odd number
    assert codes_by_trip["T2"] == "P3"


def test_renumber_uses_each_trips_own_prefix_letter(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    # Custom prefix "X" on a BFU-terminating (odd) trip must be preserved.
    _add_template_trip(db_session, created.id, "T1", "X7", "RGS-BFU", "SAN", "05:00:00")

    result = service.renumber_schedule(db_session, created.id)
    assert result.trips[0].train_code == "X1"


def test_renumber_ties_break_by_terminal_proximity(db_session):
    """Same departure_time, same direction (RGS-BFU) — closer-to-BFU origin wins the smaller number."""
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    _add_template_trip(db_session, created.id, "FAR", "P1", "RGS-BFU", "RGS", "05:00:00")   # far from BFU
    _add_template_trip(db_session, created.id, "NEAR", "P1", "RGS-BFU", "LUZ", "05:00:00")  # close to BFU

    result = service.renumber_schedule(db_session, created.id)
    codes_by_trip = {t.trip_id: t.train_code for t in result.trips}
    assert codes_by_trip["NEAR"] == "P1"
    assert codes_by_trip["FAR"] == "P3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_schedules.py -k renumber -v`
Expected: FAIL — `renumber_schedule` does not exist.

- [ ] **Step 3: Implement**

In `backend/src/service.py`, add (uses `db.py`'s `STATIONS_METADATA` order as the terminal-proximity index, matching the spec's "índice da estação na lista `stations` de `db.py`"):

```python
import re

from .db import STATIONS_METADATA

_TRAIN_CODE_RE = re.compile(r"^([A-Za-z]+)(\d+)$")
_STATION_ORDER = {s["id"]: i for i, s in enumerate(STATIONS_METADATA)}


def _split_prefix(train_code: str) -> tuple[str, int]:
    match = _TRAIN_CODE_RE.match(train_code)
    if not match:
        return train_code, 0
    return match.group(1), int(match.group(2))


def renumber_schedule(db: Session, schedule_id: int) -> ScheduleOut:
    trips = db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == schedule_id).all()

    def first_stop_and_last_stop(trip_id):
        stops = (
            db.query(models.TemplatePlannedStop)
            .filter(models.TemplatePlannedStop.trip_id == trip_id)
            .order_by(models.TemplatePlannedStop.sequence_order)
            .all()
        )
        return stops[0], stops[-1]

    odd_group, even_group = [], []
    for trip in trips:
        first_stop, last_stop = first_stop_and_last_stop(trip.id)
        entry = (trip, first_stop, last_stop)
        (odd_group if last_stop.station_id == "BFU" else even_group).append(entry)

    def sort_key(entry):
        trip, first_stop, _ = entry
        return (
            time_str_to_service_minutes(first_stop.departure_time),
            _STATION_ORDER.get(first_stop.station_id, len(_STATION_ORDER)),
        )

    for group, start_number in ((odd_group, 1), (even_group, 2)):
        group.sort(key=sort_key)
        for i, (trip, _, _) in enumerate(group):
            prefix, _ = _split_prefix(trip.train_code)
            trip.train_code = f"{prefix}{start_number + 2 * i}"

    db.commit()
    return get_schedule_trips(db, schedule_id)
```

- [ ] **Step 4: Wire the endpoint**

In `backend/src/app.py`:

```python
@app.post("/api/schedules/{schedule_id}/renumber", response_model=ScheduleOut)
def renumber_schedule(schedule_id: int, db: Session = Depends(get_db)):
    return service.renumber_schedule(db, schedule_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_schedules.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/service.py backend/src/app.py backend/tests/test_service_schedules.py
git commit -m "feat: renumber a schedule's trips by direction, time, and terminal proximity"
```

---

### Task 7: Batch-create trips with headway

**Files:**
- Modify: `backend/src/schemas.py`, `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_schedules.py`

**Interfaces:**
- Consumes: `service.renumber_schedule` (Task 6)
- Produces: `service.create_trips_batch(db, schedule_id: int, payload: TripBatchCreate) -> ScheduleOut`
- Produces: `POST /api/schedules/{id}/trips/batch`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_service_schedules.py — append
from src.schemas import StopOffset, TripBatchCreate


def test_create_trips_batch_expands_headway_and_offsets(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")

    payload = TripBatchCreate(
        direction="RGS-BFU",
        first_departure="05:00:00",
        last_station="BFU",
        count=2,
        headway_seconds=900,  # 15 min
        prefix="X",
        stop_offsets=[
            StopOffset(station="SAN", offset_seconds=0),
            StopOffset(station="BFU", offset_seconds=1800),  # +30 min
        ],
    )
    result = service.create_trips_batch(db_session, created.id, payload)

    assert len(result.trips) == 2
    first, second = sorted(result.trips, key=lambda t: t.start_time)
    assert first.start_time == "05:00:00"
    assert first.stops[-1].time == "05:30:00"
    assert second.start_time == "05:15:00"
    assert second.stops[-1].time == "05:45:00"
    # Renumbering ran automatically: both trips end at BFU => odd group, custom prefix X.
    assert {first.train_code, second.train_code} == {"X1", "X3"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_service_schedules.py::test_create_trips_batch_expands_headway_and_offsets -v`
Expected: FAIL — `TripBatchCreate` does not exist.

- [ ] **Step 3: Add the schema**

In `backend/src/schemas.py`:

```python
class StopOffset(BaseModel):
    station: str
    offset_seconds: int = Field(ge=0)


class TripBatchCreate(BaseModel):
    direction: str
    first_departure: str = Field(pattern=TIME_PATTERN)
    last_station: str
    count: int = Field(ge=1)
    headway_seconds: int = Field(ge=1)
    prefix: str = Field(min_length=1, max_length=3)
    stop_offsets: List[StopOffset] = Field(min_length=1)
```

- [ ] **Step 4: Implement**

In `backend/src/service.py`:

```python
def create_trips_batch(db: Session, schedule_id: int, payload: TripBatchCreate) -> ScheduleOut:
    _get_schedule_or_raise(db, schedule_id)
    first_departure_minutes = time_str_to_minutes(payload.first_departure)

    for i in range(payload.count):
        trip_departure_minutes = first_departure_minutes + (payload.headway_seconds / 60) * i
        trip_id = f"BATCH_{schedule_id}_{payload.direction}_{minutes_to_time_str(trip_departure_minutes).replace(':', '')}_{i}"
        db.add(models.TemplateTrip(
            id=trip_id, train_code=f"{payload.prefix}1", direction=payload.direction,
            line="Line 710", schedule_id=schedule_id,
        ))
        for seq, offset in enumerate(payload.stop_offsets):
            stop_time = minutes_to_time_str(trip_departure_minutes + offset.offset_seconds / 60)
            db.add(models.TemplatePlannedStop(
                trip_id=trip_id, station_id=offset.station, arrival_time=stop_time,
                departure_time=stop_time, sequence_order=seq, schedule_id=schedule_id,
            ))
    db.commit()

    renumber_schedule(db, schedule_id)
    return get_schedule_trips(db, schedule_id)
```

Add `TripBatchCreate` to `service.py`'s schemas import block.

- [ ] **Step 5: Wire the endpoint**

In `backend/src/app.py`:

```python
@app.post("/api/schedules/{schedule_id}/trips/batch", response_model=ScheduleOut)
def post_trips_batch(schedule_id: int, payload: TripBatchCreate, db: Session = Depends(get_db)):
    return service.create_trips_batch(db, schedule_id, payload)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest backend/tests/test_service_schedules.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/schemas.py backend/src/service.py backend/src/app.py backend/tests/test_service_schedules.py
git commit -m "feat: batch-create trips with headway and per-station offsets"
```

---

### Task 8: Edit a trip's prefix

**Files:**
- Modify: `backend/src/schemas.py`, `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_schedules.py`

**Interfaces:**
- Consumes: `service.renumber_schedule` (Task 6), `_split_prefix` (Task 6)
- Produces: `service.update_trip_prefix(db, schedule_id: int, trip_id: str, prefix: str) -> ScheduleOut`
- Produces: `PATCH /api/schedules/{id}/trips/{trip_id}`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_service_schedules.py — append
from src.schemas import TripPrefixUpdate


def test_update_trip_prefix_then_renumbers(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    _add_template_trip(db_session, created.id, "T1", "P1", "RGS-BFU", "SAN", "05:00:00")

    result = service.update_trip_prefix(db_session, created.id, "T1", "X")
    assert result.trips[0].train_code == "X1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_service_schedules.py::test_update_trip_prefix_then_renumbers -v`
Expected: FAIL — `update_trip_prefix` does not exist.

- [ ] **Step 3: Add the schema**

In `backend/src/schemas.py`:

```python
class TripPrefixUpdate(BaseModel):
    prefix: str = Field(min_length=1, max_length=3)
```

- [ ] **Step 4: Implement**

In `backend/src/service.py`:

```python
def update_trip_prefix(db: Session, schedule_id: int, trip_id: str, prefix: str) -> ScheduleOut:
    trip = (
        db.query(models.TemplateTrip)
        .filter(models.TemplateTrip.schedule_id == schedule_id, models.TemplateTrip.id == trip_id)
        .first()
    )
    if trip is None:
        raise TripNotFoundError(trip_id)
    _, number = _split_prefix(trip.train_code)
    trip.train_code = f"{prefix}{number}"
    db.commit()
    return renumber_schedule(db, schedule_id)
```

- [ ] **Step 5: Wire the endpoint**

In `backend/src/app.py`:

```python
@app.patch("/api/schedules/{schedule_id}/trips/{trip_id}", response_model=ScheduleOut)
def patch_trip_prefix(schedule_id: int, trip_id: str, payload: TripPrefixUpdate, db: Session = Depends(get_db)):
    return service.update_trip_prefix(db, schedule_id, trip_id, payload.prefix)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest backend/tests/test_service_schedules.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/schemas.py backend/src/service.py backend/src/app.py backend/tests/test_service_schedules.py
git commit -m "feat: edit a trip's prefix and renumber"
```

---

### Task 9: Load schedule to today, and make the daily reset schedule-aware

**Files:**
- Modify: `backend/src/service.py`, `backend/src/app.py`, `backend/src/scheduler.py`
- Test: `backend/tests/test_service_schedules.py`, `backend/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `service.get_current_schedule_id`/`set_current_schedule_id` (Task 1)
- Produces: `service.load_schedule(db, schedule_id: int, now: datetime | None = None) -> ScheduleOut` (live schedule shape)
- Modifies: `service.perform_daily_reset` — now a no-op when `get_current_schedule_id()` is `None`, and filters template rows by the current schedule when it is set

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_schedules.py — append
def test_load_schedule_copies_template_to_live_and_sets_current(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    _add_template_trip(db_session, created.id, "T1", "P1", "RGS-BFU", "SAN", "05:00:00")

    result = service.load_schedule(db_session, created.id)
    assert len(result.trips) == 1
    assert service.get_current_schedule_id() == created.id

    live = service.get_live_schedule(db_session)
    assert len(live.trips) == 1
    assert live.trips[0].trip_id == "T1"
```

```python
# backend/tests/test_scheduler.py — append (see existing file for should_run_catchup patterns)
def test_perform_daily_reset_is_noop_when_no_schedule_loaded(db_session):
    from datetime import datetime
    from src import service
    from src.db import init_db

    init_db(db_session.get_bind())
    service.set_current_schedule_id(None)
    # Must not raise even with no live data and nothing loaded.
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 17, 3, 0, 0))
    assert service.get_live_schedule(db_session).trips == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_schedules.py::test_load_schedule_copies_template_to_live_and_sets_current backend/tests/test_scheduler.py::test_perform_daily_reset_is_noop_when_no_schedule_loaded -v`
Expected: FAIL — `load_schedule` does not exist; `perform_daily_reset` still copies from `TemplateTrip` unconditionally (harmless-but-wrong until Step 3 lands, then it must explicitly no-op).

- [ ] **Step 3: Implement `load_schedule` and update `perform_daily_reset`**

In `backend/src/service.py`, replace the body of `perform_daily_reset` to guard on the current schedule and filter by it:

```python
def perform_daily_reset(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.now()
    schedule_id = get_current_schedule_id()
    if schedule_id is None:
        return

    db.query(models.RealizedEvent).delete()
    db.query(models.PlannedStop).delete()
    db.query(models.Trip).delete()
    db.flush()

    for template_trip in db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == schedule_id).all():
        db.add(models.Trip(
            id=template_trip.id, train_code=template_trip.train_code,
            direction=template_trip.direction, line=template_trip.line,
        ))

    for template_stop in db.query(models.TemplatePlannedStop).filter(models.TemplatePlannedStop.schedule_id == schedule_id).all():
        db.add(models.PlannedStop(
            trip_id=template_stop.trip_id, station_id=template_stop.station_id,
            arrival_time=template_stop.arrival_time, departure_time=template_stop.departure_time,
            sequence_order=template_stop.sequence_order,
        ))

    _set_setting(db, "last_reset_date", effective_reset_date(now))
    db.commit()


def load_schedule(db: Session, schedule_id: int, now: datetime | None = None) -> ScheduleOut:
    _get_schedule_or_raise(db, schedule_id)
    set_current_schedule_id(schedule_id)
    perform_daily_reset(db, now=now)

    schedule = db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
    schedule.last_loaded_at = now or datetime.now()
    db.commit()

    return get_live_schedule(db)
```

Note: `import_template` (existing) calls `perform_daily_reset(db)` right after writing to `schedule_id=1` — that call now no-ops unless schedule 1 is already the current one. Update `import_template`'s docstring/behavior is unchanged in contract (still writes to schedule 1) but reviewers should note the reset-after-import only actually refreshes live data if schedule 1 was already loaded; this matches the spec (loading is now an explicit, separate action).

- [ ] **Step 4: Update `import_template` to target schedule 1 explicitly**

In `backend/src/service.py`, modify `import_template`'s two `db.add(models.TemplateTrip(...))`/`db.add(models.TemplatePlannedStop(...))` calls to include `schedule_id=1`, and its two `db.query(...).delete()` calls to filter `.filter(models.TemplateTrip.schedule_id == 1)` / `.filter(models.TemplatePlannedStop.schedule_id == 1)` (so importing a fresh DXF only ever touches the Base CPTM schedule, never a differently-named one).

- [ ] **Step 5: Update `run_startup_catchup_if_needed`**

In `backend/src/scheduler.py`, `run_startup_catchup_if_needed` already delegates to `perform_daily_reset`, which now self-guards on `get_current_schedule_id()` — no code change needed there, but add a regression test:

```python
# backend/tests/test_scheduler.py — append
def test_startup_catchup_is_noop_when_no_schedule_loaded(db_session):
    from datetime import datetime
    from src import service
    from src.db import init_db
    from src.scheduler import run_startup_catchup_if_needed

    init_db(db_session.get_bind())
    service.set_current_schedule_id(None)
    run_startup_catchup_if_needed(db_session, now=datetime(2026, 8, 17, 3, 30, 0))
    assert service.get_live_schedule(db_session).trips == []
```

- [ ] **Step 6: Wire the endpoint**

In `backend/src/app.py`:

```python
@app.post("/api/schedules/{schedule_id}/load", response_model=ScheduleOut)
async def load_schedule(schedule_id: int, db: Session = Depends(get_db)):
    result = service.load_schedule(db, schedule_id)
    await manager.broadcast({"type": "schedule_reset"})
    return result
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_schedules.py backend/tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 8: Run the full backend suite to check for regressions**

Run: `pytest backend/tests -v`
Expected: PASS — in particular `test_scheduler.py`'s pre-existing tests, which import a template and expect a reset to follow; they must now explicitly call `service.set_current_schedule_id(1)` before expecting `perform_daily_reset` to do anything. Update any pre-existing test that assumed reset always ran, adding that call.

- [ ] **Step 9: Commit**

```bash
git add backend/src/service.py backend/src/app.py backend/src/scheduler.py backend/tests/test_service_schedules.py backend/tests/test_scheduler.py
git commit -m "feat: load a schedule into today's live operation; make the daily reset schedule-aware"
```

---

### Task 10: Generic dialog component (frontend primitive)

**Files:**
- Modify: `frontend/src/app.js`, `frontend/src/index.html`, `frontend/src/index.css`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Produces: `showDialog({ title, fields, onConfirm, confirmLabel = "Confirmar" })` where `fields` is an array of `{ name, label, type: "text"|"number"|"time", value, required }`. Calls `onConfirm(values)` with `values` keyed by `field.name` when the operator confirms; does nothing on cancel.
- This is the primitive Task 15 (batch-creation dialog), Task 16 (prefix-edit dialog), and later Specs 2a/2b/3/4 build on — keep its contract generic and stable.

- [ ] **Step 1: Add the dialog root element**

In `frontend/src/index.html`, add just before the closing `</div>` of `.app-container` (sibling of `#tooltip`):

```html
<div id="dialog-overlay" class="dialog-overlay hidden">
    <div class="dialog-box" id="dialog-box"></div>
</div>
```

- [ ] **Step 2: Add the CSS**

In `frontend/src/index.css`, append (reusing existing `--bg-*`/`--text-*`/`--border-*` custom properties already defined for theme support elsewhere in the file — check the top of `index.css` for the exact token names in use and match them):

```css
.dialog-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}
.dialog-overlay.hidden { display: none; }
.dialog-box {
    background: var(--bg-panel, #fff);
    color: var(--text-primary, #111);
    border-radius: 8px;
    padding: 24px;
    min-width: 320px;
    max-width: 480px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
}
.dialog-box h3 { margin: 0 0 16px; }
.dialog-field { margin-bottom: 12px; display: flex; flex-direction: column; gap: 4px; }
.dialog-field label { font-size: 0.85em; color: var(--text-secondary, #666); }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
```

(If `--bg-panel`/`--text-primary`/`--text-secondary` don't exist under those exact names, grep `index.css` for the theme tokens the existing `.tooltip`/`.glass-panel` rules use and substitute the real names — do not invent new tokens.)

- [ ] **Step 3: Implement `showDialog`**

In `frontend/src/app.js`, add a new section:

```javascript
// ==========================================================================
// Generic Dialog (shared primitive — used by Grades, Edição de Viagem, etc.)
// ==========================================================================
function showDialog({ title, fields, onConfirm, confirmLabel = "Confirmar" }) {
    const overlay = document.getElementById("dialog-overlay");
    const box = document.getElementById("dialog-box");

    const fieldsHtml = fields.map(f => `
        <div class="dialog-field">
            <label for="dialog-field-${f.name}">${f.label}</label>
            <input
                id="dialog-field-${f.name}"
                type="${f.type || 'text'}"
                value="${f.value !== undefined ? f.value : ''}"
                ${f.required ? 'required' : ''}
            >
        </div>
    `).join("");

    box.innerHTML = `
        <h3>${title}</h3>
        ${fieldsHtml}
        <div class="dialog-actions">
            <button class="btn btn-secondary btn-sm" id="dialog-cancel">Cancelar</button>
            <button class="btn btn-primary btn-sm" id="dialog-confirm">${confirmLabel}</button>
        </div>
    `;

    overlay.classList.remove("hidden");

    const close = () => overlay.classList.add("hidden");

    document.getElementById("dialog-cancel").onclick = close;
    document.getElementById("dialog-confirm").onclick = () => {
        const values = {};
        for (const f of fields) {
            const input = document.getElementById(`dialog-field-${f.name}`);
            if (f.required && !input.value) {
                input.focus();
                return;
            }
            values[f.name] = input.value;
        }
        close();
        onConfirm(values);
    };
}
```

- [ ] **Step 4: Manually verify**

Add a temporary call `showDialog({title: "Teste", fields: [{name: "x", label: "X", required: true}], onConfirm: v => console.log(v)})` to the browser console after loading the app (`uvicorn backend.src.app:app --reload` from `grafico/`, open `http://localhost:8000/`). Confirm: the dialog appears centered with a backdrop, the required field blocks confirm when empty, Cancelar closes without calling the callback, Confirmar with a value logs `{x: "..."}` to the console. Remove the temporary call.

- [ ] **Step 5: Add manual test scenario**

Append to `frontend/tests/manual_test.md` (match its existing scenario format):

```markdown
## Diálogo genérico

1. Abra qualquer fluxo que use `showDialog` (após as próximas tasks, ex.: "Nova Viagem" na view Grades).
2. Confirme que o campo obrigatório vazio impede o "Confirmar" (foco volta ao campo).
3. Confirme que "Cancelar" fecha o diálogo sem aplicar nenhuma mudança.
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app.js frontend/src/index.html frontend/src/index.css frontend/tests/manual_test.md
git commit -m "feat: add generic dialog component"
```

---

### Task 11: Generic context menu component (frontend primitive)

**Files:**
- Modify: `frontend/src/app.js`, `frontend/src/index.html`, `frontend/src/index.css`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Produces: `showContextMenu(clientX, clientY, items)` where `items` is an array of `{ label, onClick }`. Closes itself on any outside click or item click.
- Reused by Task 13 (Editar prefixo) and by later Specs 2b/4.

- [ ] **Step 1: Add the root element**

In `frontend/src/index.html`, add next to the dialog overlay:

```html
<ul id="context-menu" class="context-menu hidden"></ul>
```

- [ ] **Step 2: Add the CSS**

In `frontend/src/index.css`:

```css
.context-menu {
    position: fixed;
    z-index: 1001;
    background: var(--bg-panel, #fff);
    color: var(--text-primary, #111);
    border-radius: 6px;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.25);
    list-style: none;
    margin: 0;
    padding: 4px 0;
    min-width: 180px;
}
.context-menu.hidden { display: none; }
.context-menu li {
    padding: 8px 16px;
    cursor: pointer;
    font-size: 0.9em;
}
.context-menu li:hover { background: var(--bg-hover, rgba(0,0,0,0.06)); }
```

- [ ] **Step 3: Implement `showContextMenu`**

In `frontend/src/app.js`:

```javascript
// ==========================================================================
// Generic Context Menu (shared primitive)
// ==========================================================================
let _contextMenuOutsideClickHandler = null;

function showContextMenu(clientX, clientY, items) {
    const menu = document.getElementById("context-menu");
    menu.innerHTML = items.map((item, i) => `<li data-idx="${i}">${item.label}</li>`).join("");
    menu.style.left = `${clientX}px`;
    menu.style.top = `${clientY}px`;
    menu.classList.remove("hidden");

    menu.querySelectorAll("li").forEach((li, i) => {
        li.onclick = () => {
            hideContextMenu();
            items[i].onClick();
        };
    });

    if (_contextMenuOutsideClickHandler) {
        document.removeEventListener("click", _contextMenuOutsideClickHandler);
    }
    _contextMenuOutsideClickHandler = (e) => {
        if (!menu.contains(e.target)) hideContextMenu();
    };
    // Deferred so the same click that opened the menu (a `contextmenu` event,
    // separate from `click`) doesn't immediately trigger this outside-click check.
    setTimeout(() => document.addEventListener("click", _contextMenuOutsideClickHandler), 0);
}

function hideContextMenu() {
    document.getElementById("context-menu").classList.add("hidden");
    if (_contextMenuOutsideClickHandler) {
        document.removeEventListener("click", _contextMenuOutsideClickHandler);
        _contextMenuOutsideClickHandler = null;
    }
}
```

- [ ] **Step 4: Manually verify**

Temporarily wire a `contextmenu` listener on the chart SVG (e.g. in `renderChart()`, `svg.addEventListener("contextmenu", e => { e.preventDefault(); showContextMenu(e.clientX, e.clientY, [{label: "Teste", onClick: () => console.log("clicked")}]); })`), reload, right-click the chart, confirm the menu appears at the cursor, clicking the item logs and closes it, clicking outside closes it without side effects. Remove the temporary listener (Task 13 adds the real one).

- [ ] **Step 5: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Menu de contexto genérico

1. Após a Task 13 estar implementada, clique com o botão direito num nó de viagem na view Grades.
2. Confirme que o menu aparece na posição do cursor.
3. Confirme que clicar fora do menu o fecha sem executar nenhuma ação.
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app.js frontend/src/index.html frontend/src/index.css frontend/tests/manual_test.md
git commit -m "feat: add generic context menu component"
```

---

### Task 12: Mode tabs (Operacional / Grades)

**Files:**
- Modify: `frontend/src/index.html`, `frontend/src/app.js`, `frontend/src/index.css`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Produces: `switchMode(mode: "operational" | "schedules")`, `appState.mode`
- Produces: view containers `#operational-view`, `#schedules-view` in the DOM

- [ ] **Step 1: Add the tab buttons and view containers**

In `frontend/src/index.html`, inside `.logo-area`'s sibling position in `.app-header` (right after the closing `</div>` of `.logo-area`, before `.header-controls`), add:

```html
<div class="mode-tabs">
    <button class="tab-btn active" id="btn-mode-operational" onclick="switchMode('operational')">Operacional</button>
    <button class="tab-btn" id="btn-mode-schedules" onclick="switchMode('schedules')">Grades</button>
</div>
```

Wrap the existing `<main class="main-content">...</main>` block's inner contents in a new `<div id="operational-view">...</div>`, and add a sibling `<div id="schedules-view" class="hidden"></div>` right after it (still inside `<main>`). The `schedules-view` div stays empty here — Task 14 populates it.

- [ ] **Step 2: Add CSS**

In `frontend/src/index.css`:

```css
.mode-tabs { display: flex; gap: 4px; }
#schedules-view.hidden, #operational-view.hidden { display: none; }
```

- [ ] **Step 3: Implement `switchMode`**

In `frontend/src/app.js`:

```javascript
// ==========================================================================
// Mode Switching (Operacional / Grades)
// ==========================================================================
function switchMode(mode) {
    appState.mode = mode;

    document.getElementById("btn-mode-operational").classList.toggle("active", mode === "operational");
    document.getElementById("btn-mode-schedules").classList.toggle("active", mode === "schedules");
    document.getElementById("operational-view").classList.toggle("hidden", mode !== "operational");
    document.getElementById("schedules-view").classList.toggle("hidden", mode !== "schedules");

    if (mode === "schedules") renderSchedulesView();
}
```

Add `mode: "operational"` to the `appState` object's initial definition. `renderSchedulesView()` is a stub for now (`function renderSchedulesView() {}`), implemented fully in Task 14.

- [ ] **Step 4: Manually verify**

Reload the app, confirm the "Operacional" tab is active by default and shows the existing chart, click "Grades" and confirm the operational view hides and the (still-empty) schedules view shows, click back and confirm the chart is still intact (not re-fetched, `appState.trips` preserved).

- [ ] **Step 5: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Alternância de modo (Operacional / Grades)

1. Ao carregar a página, confirme que a aba "Operacional" está ativa e o gráfico do dia aparece.
2. Clique em "Grades" — confirme que a área operacional some (sem perder o estado do gráfico) e a view de grades aparece.
3. Clique de volta em "Operacional" — confirme que o gráfico volta exatamente como estava (mesmo scroll, mesma seleção).
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/index.html frontend/src/app.js frontend/src/index.css frontend/tests/manual_test.md
git commit -m "feat: add Operacional/Grades mode tabs"
```

---

### Task 13: Grades view — schedule list and CRUD actions

**Files:**
- Modify: `frontend/src/app.js`, `frontend/src/index.html`, `frontend/src/index.css`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `showDialog` (Task 10), `GET/POST/PATCH/DELETE /api/schedules`, `POST /api/schedules/{id}/clone`, `POST /api/schedules/{id}/load` (Tasks 2, 4, 5, 9)
- Produces: `renderSchedulesView()` (replaces the Task 12 stub), `appState.editorScheduleId`

- [ ] **Step 1: Build the two-pane layout markup generator**

In `frontend/src/index.html`, leave `#schedules-view` empty (it's built dynamically, matching how `#chart-container` is already populated at runtime rather than statically).

In `frontend/src/app.js`:

```javascript
// ==========================================================================
// Grades View
// ==========================================================================
function renderSchedulesView() {
    const container = document.getElementById("schedules-view");
    container.innerHTML = `
        <aside class="sidebar sidebar-left glass-panel" id="schedules-list-panel">
            <div class="panel-header"><h2>Grades</h2></div>
            <ul class="train-list" id="schedules-list"></ul>
            <div class="schedules-actions">
                <button class="btn btn-secondary btn-sm" onclick="promptCreateSchedule()">Nova Grade</button>
                <button class="btn btn-secondary btn-sm" onclick="promptCloneSchedule()">Salvar Como</button>
                <button class="btn btn-secondary btn-sm" onclick="promptRenameSchedule()">Renomear</button>
                <button class="btn btn-secondary btn-sm" onclick="promptDeleteSchedule()">Excluir</button>
                <button class="btn btn-primary btn-sm" onclick="promptLoadSchedule()">Carregar p/ Hoje</button>
            </div>
        </aside>
        <section class="graphic-area glass-panel">
            <div class="panel-header"><h2>Editor de Grade</h2></div>
            <div class="chart-scroll-container" id="schedule-editor-container"></div>
        </section>
    `;
    loadSchedulesList();
}

function loadSchedulesList() {
    fetch("/api/schedules")
        .then(r => r.json())
        .then(schedules => {
            appState.schedules = schedules;
            if (appState.editorScheduleId === undefined || appState.editorScheduleId === null) {
                appState.editorScheduleId = schedules[0] ? schedules[0].id : null;
            }
            renderSchedulesList(schedules);
            renderScheduleEditor();
        });
}

function renderSchedulesList(schedules) {
    const list = document.getElementById("schedules-list");
    list.innerHTML = schedules.map(s => `
        <li class="train-item ${appState.editorScheduleId === s.id ? 'selected' : ''}" onclick="selectEditorSchedule(${s.id})">
            <div class="train-info"><span class="train-code-label">${s.name}</span></div>
        </li>
    `).join("");
}

function selectEditorSchedule(scheduleId) {
    appState.editorScheduleId = scheduleId;
    loadSchedulesList();
}
```

- [ ] **Step 2: Wire the CRUD prompts**

In `frontend/src/app.js`:

```javascript
function promptCreateSchedule() {
    showDialog({
        title: "Nova Grade",
        fields: [{ name: "name", label: "Nome", required: true }],
        onConfirm: (values) => {
            fetch("/api/schedules", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: values.name }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                .then(created => { appState.editorScheduleId = created.id; loadSchedulesList(); })
                .catch(err => alert("Não foi possível criar a grade: " + err.message));
        },
    });
}

function promptCloneSchedule() {
    if (!appState.editorScheduleId) return;
    showDialog({
        title: "Salvar Como",
        fields: [{ name: "name", label: "Novo nome", required: true }],
        onConfirm: (values) => {
            fetch(`/api/schedules/${appState.editorScheduleId}/clone`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: values.name }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                .then(created => { appState.editorScheduleId = created.id; loadSchedulesList(); })
                .catch(err => alert("Não foi possível salvar como: " + err.message));
        },
    });
}

function promptRenameSchedule() {
    if (!appState.editorScheduleId) return;
    const current = appState.schedules.find(s => s.id === appState.editorScheduleId);
    showDialog({
        title: "Renomear Grade",
        fields: [{ name: "name", label: "Nome", required: true, value: current ? current.name : "" }],
        onConfirm: (values) => {
            fetch(`/api/schedules/${appState.editorScheduleId}`, {
                method: "PATCH", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: values.name }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                .then(() => loadSchedulesList())
                .catch(err => alert("Não foi possível renomear: " + err.message));
        },
    });
}

function promptDeleteSchedule() {
    if (!appState.editorScheduleId) return;
    if (!confirm("Excluir esta grade? Esta ação não pode ser desfeita.")) return;
    fetch(`/api/schedules/${appState.editorScheduleId}`, { method: "DELETE" })
        .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
        .then(() => { appState.editorScheduleId = null; loadSchedulesList(); })
        .catch(err => alert("Não foi possível excluir: " + err.message));
}

function promptLoadSchedule() {
    if (!appState.editorScheduleId) return;
    const current = appState.schedules.find(s => s.id === appState.editorScheduleId);
    if (!confirm(`Carregar "${current ? current.name : ''}" para operação hoje? As viagens em curso serão substituídas.`)) return;
    fetch(`/api/schedules/${appState.editorScheduleId}/load`, { method: "POST" })
        .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
        .then(data => {
            initSchedule(data.trips);
            switchMode("operational");
        })
        .catch(err => alert("Não foi possível carregar a grade: " + err.message));
}
```

`renderScheduleEditor()` is a stub here (`function renderScheduleEditor() {}`); Task 14 implements it.

- [ ] **Step 3: Add CSS for the actions row**

In `frontend/src/index.css`:

```css
.schedules-actions { display: flex; flex-direction: column; gap: 6px; padding: 12px; }
```

- [ ] **Step 4: Manually verify**

Reload, go to "Grades", confirm "Grade Base CPTM" appears in the list. Create a new grade via "Nova Grade", confirm it appears and gets auto-selected. Rename it, confirm the list updates. "Salvar Como" it, confirm a second copy appears. "Excluir" the copy, confirm it's gone. Try deleting down to the last remaining schedule and confirm the server's 400 shows as an alert instead of silently failing. "Carregar p/ Hoje" a grade with at least one trip (create one via direct API call with curl for now, since batch-creation UI is Task 15) and confirm it switches back to "Operacional" showing that trip.

- [ ] **Step 5: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Grades — lista e CRUD

1. Abra "Grades" — confirme "Grade Base CPTM" na lista.
2. "Nova Grade" com um nome — confirme que aparece selecionada na lista.
3. "Renomear" — confirme que o nome muda na lista.
4. "Salvar Como" — confirme uma cópia com o novo nome, com as mesmas viagens.
5. "Excluir" — confirme que some da lista; tentar excluir a única grade restante deve mostrar um erro, não excluir.
6. "Carregar p/ Hoje" — confirme o diálogo de confirmação, e que a tela volta para "Operacional" mostrando as viagens carregadas.
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app.js frontend/src/index.html frontend/src/index.css frontend/tests/manual_test.md
git commit -m "feat: Grades view — list schedules and wire CRUD actions"
```

---

### Task 14: Schedule editor canvas (read-only render)

**Files:**
- Modify: `frontend/src/app.js`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `GET /api/schedules/{id}/trips` (Task 3), `dxfYToSvg`/`timeToX`/`drawGrid` (existing)
- Produces: `renderScheduleEditor()` (replaces the Task 13 stub), `yToStation(y)`

- [ ] **Step 1: Fetch and render the editor's trips**

In `frontend/src/app.js`:

```javascript
function renderScheduleEditor() {
    const container = document.getElementById("schedule-editor-container");
    if (!appState.editorScheduleId) { container.innerHTML = ""; return; }

    fetch(`/api/schedules/${appState.editorScheduleId}/trips`)
        .then(r => r.json())
        .then(data => {
            appState.editorTrips = data.trips;
            drawScheduleEditorChart(container);
        });
}

function drawScheduleEditorChart(container) {
    container.innerHTML = "";
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", CHART_WIDTH);
    svg.setAttribute("height", CHART_HEIGHT);
    svg.setAttribute("id", "schedule-editor-svg");

    drawGrid(svg);

    appState.editorTrips.forEach(trip => {
        const points = trip.stops.map(stop =>
            `${timeToX(stop.time)},${dxfYToSvg(stop.y_coord, appState.selectedLine)}`
        ).join(" ");
        const polyline = document.createElementNS(SVG_NS, "polyline");
        polyline.setAttribute("points", points);
        polyline.className.baseVal = "train-path-planned";
        svg.appendChild(polyline);
    });

    container.appendChild(svg);
}
```

Note: this deliberately does **not** attach `mousedown`/drag handlers (per spec: "nós não são arrastáveis nesta versão") and does not call `startAutoScrollClock`/`centerChartOnTime` (no now-line, no auto-scroll — per spec, the reference time is just whatever's centered when the operator scrolls manually, reusing `getReferenceTime()` conceptually but with no clock-driven movement).

- [ ] **Step 2: Add `yToStation`**

In `frontend/src/app.js`, add near `dxfYToSvg`:

```javascript
// Inverse of dxfYToSvg: nearest station to an SVG Y pixel, or null outside tolerance.
const STATION_SNAP_TOLERANCE_PX = 25;

function yToStation(svgY, lineType) {
    const lineStations = stations[lineType];
    let best = null;
    let bestDist = Infinity;
    for (const station of lineStations) {
        const stationY = dxfYToSvg(station.y_dxf, lineType);
        const dist = Math.abs(svgY - stationY);
        if (dist < bestDist) { bestDist = dist; best = station; }
    }
    return bestDist <= STATION_SNAP_TOLERANCE_PX ? best : null;
}
```

(Not called anywhere yet — Task 15 uses it.)

- [ ] **Step 3: Manually verify**

Go to "Grades", select "Grade Base CPTM" (assuming it has been imported via "Importar JSON" from the Operacional tab at least once — if the dev DB is empty, import `backend/data/schedule.json` first). Confirm the same trip lines render in the editor pane as in the Operacional chart, but clicking/dragging a node does nothing (no drag handles at all — nothing is selected/highlighted, since this view doesn't call `selectTrip`).

- [ ] **Step 4: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Editor de grade (canvas somente leitura)

1. Em "Grades", selecione uma grade com viagens.
2. Confirme que as linhas aparecem no canvas do editor, no mesmo layout do gráfico operacional.
3. Confirme que não há nós arrastáveis nem linha "agora" nem auto-scroll nessa view.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: read-only schedule editor canvas"
```

---

### Task 15: Two-click trip creation with batch dialog

**Files:**
- Modify: `frontend/src/app.js`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `showDialog` (Task 10), `yToStation` (Task 14), `POST /api/schedules/{id}/trips/batch` (Task 7)

- [ ] **Step 1: Add the context menu trigger and two-click state**

In `frontend/src/app.js`, modify `drawScheduleEditorChart` to attach a `contextmenu` listener on the SVG:

```javascript
svg.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    showContextMenu(e.clientX, e.clientY, [
        { label: "Nova Viagem", onClick: () => startTripCreationMode() },
    ]);
});
svg.addEventListener("click", onScheduleEditorClick);
```

Add to `appState`'s initial definition: `tripCreationMode: null` (null, or `{ firstPoint: {station, time} }` mid-flow).

```javascript
function startTripCreationMode() {
    appState.tripCreationMode = {};
    document.getElementById("schedule-editor-svg").style.cursor = "crosshair";
}

function onScheduleEditorClick(e) {
    if (!appState.tripCreationMode) return;

    const svg = document.getElementById("schedule-editor-svg");
    const rect = svg.getBoundingClientRect();
    const svgX = e.clientX - rect.left;
    const svgY = e.clientY - rect.top;
    const station = yToStation(svgY, appState.selectedLine);
    if (!station) return;  // click missed every station within tolerance — ignore
    const time = xToTime(svgX);

    if (!appState.tripCreationMode.firstPoint) {
        appState.tripCreationMode.firstPoint = { station: station.id, time };
        return;
    }

    const secondPoint = { station: station.id, time };
    const firstPoint = appState.tripCreationMode.firstPoint;
    appState.tripCreationMode = null;
    document.getElementById("schedule-editor-svg").style.cursor = "default";
    openTripCreationDialog(firstPoint, secondPoint);
}
```

- [ ] **Step 2: Build the batch-creation dialog**

`showDialog`'s current contract (Task 10) only supports flat text/number/time fields — the spec's stop-offsets table needs a dynamic row-per-station editor, which is a genuine extension beyond a flat field list. Rather than bend the generic dialog to a one-off shape, build this dialog's markup directly (still reusing `#dialog-overlay`/`#dialog-box`):

```javascript
function openTripCreationDialog(firstPoint, secondPoint) {
    const [origin, destination] = timeStrToMinutes(firstPoint.time) <= timeStrToMinutes(secondPoint.time)
        ? [firstPoint, secondPoint] : [secondPoint, firstPoint];
    const direction = `${origin.station}-${destination.station}`;

    const overlay = document.getElementById("dialog-overlay");
    const box = document.getElementById("dialog-box");
    box.innerHTML = `
        <h3>Nova Viagem</h3>
        <p>Origem: ${origin.station} às ${origin.time.substring(0, 5)}</p>
        <p>Destino: ${destination.station} às ${destination.time.substring(0, 5)}</p>
        <div class="dialog-field">
            <label for="tc-prefix">Prefixo</label>
            <input id="tc-prefix" required maxlength="3">
        </div>
        <div class="dialog-field">
            <label for="tc-count">Nº de viagens</label>
            <input id="tc-count" type="number" value="1" min="1">
        </div>
        <div class="dialog-field">
            <label for="tc-headway">Intervalo (MM:SS)</label>
            <input id="tc-headway" value="15:00">
        </div>
        <div class="dialog-actions">
            <button class="btn btn-secondary btn-sm" id="dialog-cancel">Cancelar</button>
            <button class="btn btn-primary btn-sm" id="dialog-confirm">Criar</button>
        </div>
    `;
    overlay.classList.remove("hidden");

    document.getElementById("dialog-cancel").onclick = () => overlay.classList.add("hidden");
    document.getElementById("dialog-confirm").onclick = () => {
        const prefix = document.getElementById("tc-prefix").value;
        if (!prefix) { document.getElementById("tc-prefix").focus(); return; }
        const count = parseInt(document.getElementById("tc-count").value, 10);
        const [mm, ss] = document.getElementById("tc-headway").value.split(":").map(Number);
        const headwaySeconds = mm * 60 + ss;

        overlay.classList.add("hidden");

        fetch(`/api/schedules/${appState.editorScheduleId}/trips/batch`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                direction, first_departure: origin.time, last_station: destination.station,
                count, headway_seconds: headwaySeconds, prefix,
                stop_offsets: [
                    { station: origin.station, offset_seconds: 0 },
                    { station: destination.station, offset_seconds: Math.round((timeStrToMinutes(destination.time) - timeStrToMinutes(origin.time)) * 60) },
                ],
            }),
        })
            .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
            .then(() => renderScheduleEditor())
            .catch(err => alert("Não foi possível criar a viagem: " + err.message));
    };
}
```

Note: this first cut only supports two-point trips (origin + destination, no intermediate stations) — matching the two clicks the spec's flow describes. A richer per-station offset table (editable intermediate stops) is a natural follow-up but is not required by the spec text for the MVP interaction (the spec's dialog mockup shows a table for it, but the two-click flow as specified only captures two points). If intermediate-stop editing turns out to be needed, extend `stop_offsets` construction here — the batch endpoint (Task 7) already accepts an arbitrary-length list.

- [ ] **Step 3: Manually verify**

In "Grades", right-click the editor canvas → "Nova Viagem", click two points at different stations/times, fill in the dialog (prefix, count, headway), confirm, and verify new trip lines appear on the editor canvas immediately, correctly spaced by the headway.

- [ ] **Step 4: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Criação de viagem em duas etapas

1. Em "Grades", botão direito no canvas → "Nova Viagem".
2. Clique em dois pontos do canvas (estações/horários diferentes) — confirme que o diálogo mostra origem/destino corretos.
3. Preencha prefixo, número de viagens e intervalo; confirme — as novas linhas aparecem no canvas, espaçadas pelo intervalo.
4. Tente confirmar sem prefixo — confirme que o foco volta ao campo e nada é criado.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: two-click trip creation with batch dialog"
```

---

### Task 16: Edit prefix via context menu

**Files:**
- Modify: `frontend/src/app.js`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `showContextMenu` (Task 11), `showDialog` (Task 10), `PATCH /api/schedules/{id}/trips/{trip_id}` (Task 8)

- [ ] **Step 1: Attach a right-click handler per trip line**

In `frontend/src/app.js`, modify `drawScheduleEditorChart`'s per-trip polyline creation (Task 14, Step 1) to attach a `contextmenu` listener:

```javascript
    appState.editorTrips.forEach(trip => {
        const points = trip.stops.map(stop =>
            `${timeToX(stop.time)},${dxfYToSvg(stop.y_coord, appState.selectedLine)}`
        ).join(" ");
        const polyline = document.createElementNS(SVG_NS, "polyline");
        polyline.setAttribute("points", points);
        polyline.className.baseVal = "train-path-planned";
        polyline.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            e.stopPropagation();
            showContextMenu(e.clientX, e.clientY, [
                { label: "Editar prefixo", onClick: () => promptEditPrefix(trip) },
            ]);
        });
        svg.appendChild(polyline);
    });
```

(`e.stopPropagation()` keeps this from also triggering the SVG-level "Nova Viagem" context menu wired in Task 15, Step 1.)

- [ ] **Step 2: Implement the prefix dialog**

```javascript
function promptEditPrefix(trip) {
    const currentPrefix = trip.train_code.match(/^([A-Za-z]+)/)?.[1] || "";
    showDialog({
        title: `Editar prefixo — ${trip.train_code}`,
        fields: [{ name: "prefix", label: "Prefixo", required: true, value: currentPrefix }],
        onConfirm: (values) => {
            fetch(`/api/schedules/${appState.editorScheduleId}/trips/${encodeURIComponent(trip.trip_id)}`, {
                method: "PATCH", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prefix: values.prefix }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                .then(() => renderScheduleEditor())
                .catch(err => alert("Não foi possível editar o prefixo: " + err.message));
        },
    });
}
```

- [ ] **Step 3: Manually verify**

In "Grades", right-click an existing trip line → "Editar prefixo", change the letter, confirm, verify the canvas redraws and the trip's displayed code (and any others in its direction group) reflect the renumbering.

- [ ] **Step 4: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Editar prefixo pós-criação

1. Em "Grades", botão direito numa viagem existente → "Editar prefixo".
2. Troque o prefixo e confirme — a viagem e as demais do mesmo sentido são renumeradas.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: edit trip prefix via context menu"
```

---

## Self-Review

**Spec coverage:** Nova Grade/Salvar/Salvar Como/Renomear/Excluir/Carregar p/ Hoje → Tasks 2, 4, 5, 9, 13. Renumeração → Task 6, invoked by Tasks 7, 8. Criação em duas etapas com dialog de headway/prefixo/tabela → Task 15 (table-of-offsets simplified to two points per the interaction as specified; noted inline). Edição de prefixo pós-criação → Task 16. Mode tabs and read-only editor canvas → Tasks 12, 14. `yToStation` → Task 14. Migration and in-memory `current_schedule_id` → Tasks 1, 9.

**Placeholder scan:** none — every step has runnable code or a concrete manual verification script.

**Type consistency:** `ScheduleMetaOut` (schedule metadata: id/name/created_at/last_loaded_at) vs `ScheduleOut` (trips list, pre-existing name reused from `/api/schedule`) are named distinctly throughout and cross-checked in Task 3, Step 3 — every later task's return type matches one of these two consistently. `service.get_current_schedule_id`/`set_current_schedule_id` (Task 1) match their use in Tasks 4, 9. `_split_prefix`/`_TRAIN_CODE_RE` (Task 6) reused as-is in Task 8, no signature drift.
