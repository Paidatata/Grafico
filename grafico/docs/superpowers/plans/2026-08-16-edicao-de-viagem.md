# Edição de Viagem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a dispatcher truncate a trip early (including cancelling it outright) or move an already-scheduled trip's origin further down its own route — reusing whatever stop time was already there, never inventing new ones — plus make the "reset só toca o futuro" rule (don't rewrite the past) the general behavior of `reset_trip` everywhere it's used.

**Architecture:** Two nullable integer columns on the live `trips` table (`active_first_seq`, `active_last_seq`) define a trip's currently-active stop window; nothing is ever deleted from `planned_stops`. "Suprimir a partir daqui" narrows the window from the back, "Alterar partida" narrows it from the front (only ever forward) — both reuse the exact stop the operator clicked, validated against the same `edit_lookback_minutes` window `shift_stop` already enforces. `reset_trip` (pre-existing) gains the same lookback guard per-stop, and independently un-suppresses either boundary only if the boundary node itself is still within the editable window.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), vanilla JS/SVG (frontend). Backend tests via pytest + FastAPI TestClient; frontend verified manually.

**Spec:** `docs/superpowers/specs/2026-08-16-edicao-de-viagem-design.md`

## Global Constraints

- `active_first_seq`/`active_last_seq` live only on the `trips` table (live layer) — never on `template_trips`. `NULL` means "no cut on this side" (full route active from that end).
- Both new actions, and the lookback re-check inside `reset_trip`, use `service.get_edit_lookback_minutes` — the same setting `shift_stop` already reads. No new setting is introduced.
- "Alterar partida" only ever moves `active_first_seq` forward (to a larger sequence index than the trip's current effective origin) — moving it backward is out of scope; the only way back is `reset_trip`, and only within the lookback window.
- This plan modifies `service.reset_trip`'s behavior and its call signature (adds `now: datetime | None = None`, matching `shift_stop`'s existing pattern) — this is a real behavior change to code Specs 1, 2a already ship against. Task 2 explicitly re-audits every existing caller and test for the regression this introduces (see Task 2, Step 6).
- This plan does not touch Spec 3 (Tempo de Volta) — Spec 3's own plan is responsible for reading `active_first_seq`/`active_last_seq` as the "effective" first/last stop when it implements pairing. This plan's only obligation to Spec 3 is exposing both fields on `TripOut` (Task 1).

---

## File Structure

**Backend:**
- `backend/src/models.py` — modify: add `Trip.active_first_seq`, `Trip.active_last_seq`
- `backend/src/db.py` — modify: migrate existing `trips` table (guarded `ALTER TABLE`)
- `backend/src/schemas.py` — modify: `TripOut` gains `active_first_seq`, `active_last_seq`
- `backend/src/service.py` — modify: `reset_trip` gains lookback guard + `now` param; add `suppress_from`, `depart_from`
- `backend/src/app.py` — modify: register the two new endpoints

**Backend tests:**
- `backend/tests/test_db.py` — modify: migration assertion
- `backend/tests/test_service_reset.py` — modify: fix the now-nondeterministic existing test, add lookback-freeze tests
- `backend/tests/test_service_trip_edit.py` — new: `suppress_from`/`depart_from` tests
- `backend/tests/test_api.py` — modify: add `now` freezing to `test_reset_trip_endpoint` isn't required (already deterministic — see Task 2, Step 6) but add endpoint tests for the two new routes

**Frontend:**
- `frontend/src/app.js` — modify: context-menu wiring on chart nodes, dashed/no-drag rendering for suppressed stops

**Frontend manual tests:**
- `frontend/tests/manual_test.md` — modify: add scenarios

---

### Task 1: `active_first_seq`/`active_last_seq` columns

**Files:**
- Modify: `backend/src/models.py`, `backend/src/db.py`, `backend/src/schemas.py`, `backend/src/service.py`
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Produces: `models.Trip.active_first_seq: int | None`, `models.Trip.active_last_seq: int | None`
- Produces: `schemas.TripOut.active_first_seq`, `schemas.TripOut.active_last_seq`

- [ ] **Step 1: Write the failing migration test**

```python
# backend/tests/test_db.py — append
def test_init_db_adds_active_seq_columns_to_existing_trips_table(db_session):
    from src.db import init_db
    from sqlalchemy import text

    bind = db_session.get_bind()
    init_db(bind)

    # Simulate a pre-existing DB: drop the columns by recreating the table the old way
    # is impractical in SQLite, so instead just assert the columns exist and accept NULL.
    cols = {row[1] for row in db_session.execute(text("PRAGMA table_info(trips)"))}
    assert "active_first_seq" in cols
    assert "active_last_seq" in cols

    init_db(bind)  # idempotent re-run must not error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_db.py::test_init_db_adds_active_seq_columns_to_existing_trips_table -v`
Expected: FAIL — columns don't exist yet.

- [ ] **Step 3: Add the columns to the model**

In `backend/src/models.py`, modify `Trip`:

```python
class Trip(Base):
    __tablename__ = "trips"
    id = Column(String, primary_key=True)
    train_code = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    line = Column(String, nullable=False)
    active_first_seq = Column(Integer, nullable=True)
    active_last_seq = Column(Integer, nullable=True)
```

- [ ] **Step 4: Add the migration**

In `backend/src/db.py`, inside `init_db`, after the `template_planned_stops` schedule_id migration block (from the Grades plan — if that plan hasn't been implemented yet, add this as its own guarded block in the same style), add:

```python
        existing_cols = {row[1] for row in db.execute(text("PRAGMA table_info(trips)"))}
        if "active_first_seq" not in existing_cols:
            db.execute(text("ALTER TABLE trips ADD COLUMN active_first_seq INTEGER"))
        if "active_last_seq" not in existing_cols:
            db.execute(text("ALTER TABLE trips ADD COLUMN active_last_seq INTEGER"))
        db.commit()
```

(`from sqlalchemy import text` — reuse the existing import if the Grades plan's migration already added it; otherwise add it.)

- [ ] **Step 5: Add the schema fields**

In `backend/src/schemas.py`, modify `TripOut`:

```python
class TripOut(BaseModel):
    trip_id: str
    direction: str
    train_code: str
    start_time: str
    end_time: str
    stops: List[StopOut]
    active_first_seq: Optional[int] = None
    active_last_seq: Optional[int] = None
```

- [ ] **Step 6: Populate the new fields in `_trip_to_out`**

In `backend/src/service.py`, modify `_trip_to_out`:

```python
def _trip_to_out(
    trip: models.Trip, stops: list[models.PlannedStop], station_y: dict[str, float],
) -> TripOut:
    return TripOut(
        trip_id=trip.id,
        direction=trip.direction,
        train_code=trip.train_code,
        start_time=stops[0].departure_time,
        end_time=stops[-1].departure_time,
        active_first_seq=trip.active_first_seq,
        active_last_seq=trip.active_last_seq,
        stops=[
            StopOut(station=s.station_id, time=s.departure_time, y_coord=station_y.get(s.station_id, 0.0))
            for s in stops
        ],
    )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest backend/tests/test_db.py -v`
Expected: PASS

- [ ] **Step 8: Run the full backend suite to check for regressions**

Run: `pytest backend/tests -v`
Expected: PASS — `TripOut` gained two `Optional` fields with defaults, so no existing construction site breaks.

- [ ] **Step 9: Commit**

```bash
git add backend/src/models.py backend/src/db.py backend/src/schemas.py backend/src/service.py backend/tests/test_db.py
git commit -m "feat: add active_first_seq/active_last_seq columns to trips"
```

---

### Task 2: `reset_trip` respects the lookback window ("reset só toca o futuro")

**Files:**
- Modify: `backend/src/service.py`
- Test: `backend/tests/test_service_reset.py`

**Interfaces:**
- Consumes: `service.get_edit_lookback_minutes` (existing), `Trip.active_first_seq`/`active_last_seq` (Task 1)
- Modifies: `service.reset_trip(db, trip_id, now: datetime | None = None) -> TripOut` — signature gains `now`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_reset.py — replace the file's single existing test with:
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
    # RGS's own departure_time is 05:30 (untouched by suppress_from — see Task 3); at
    # 06:00 that boundary node is 30 minutes old, beyond the 15-minute lookback.
    trip = service.reset_trip(db_session, "TRIP_BFU-RGS_050000", now=datetime(2026, 8, 13, 6, 0, 0))
    assert trip.active_last_seq == 0  # still suppressed from RGS onward


def test_reset_unknown_trip_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(TripNotFoundError):
        service.reset_trip(db_session, "NOT_A_TRIP")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_reset.py -v`
Expected: FAIL — `reset_trip` doesn't accept `now`; `suppress_from` doesn't exist yet (Task 3 adds it — for this step, comment out the two `suppress_from`-dependent tests with a `# TODO(Task 3)` marker and come back to enable them once Task 3 lands, or implement Task 1-3 in this order without running those two until Task 3 is done. Simplest: reorder — implement Task 3 (`suppress_from`) before finishing this task's test run. See Step 3 note.)

Note: `test_reset_trip_undoes_a_recent_suppress_from_boundary` and `test_reset_trip_leaves_an_old_suppress_from_boundary_in_place` depend on `suppress_from`, implemented in Task 3. Write them here (co-located with the rest of `reset_trip`'s behavior, since they test `reset_trip`, not `suppress_from`), but mark them `@pytest.mark.skip(reason="depends on Task 3's suppress_from")` for now, and remove the skip mark in Task 3, Step 6.

- [ ] **Step 3: Implement the lookback-guarded `reset_trip`**

In `backend/src/service.py`, replace `reset_trip`:

```python
def reset_trip(db: Session, trip_id: str, now: datetime | None = None) -> TripOut:
    now = now or datetime.now()
    template_stops = (
        db.query(models.TemplatePlannedStop)
        .filter(models.TemplatePlannedStop.trip_id == trip_id)
        .order_by(models.TemplatePlannedStop.sequence_order)
        .all()
    )
    if not template_stops:
        raise TripNotFoundError(trip_id)

    lookback_minutes = get_edit_lookback_minutes(db)
    now_sm = datetime_to_service_minutes(now)

    live_stops = {stop.station_id: stop for stop in _trip_stops(db, trip_id)}
    for template_stop in template_stops:
        live_stop = live_stops.get(template_stop.station_id)
        if live_stop is None:
            continue
        current_sm = time_str_to_service_minutes(live_stop.departure_time)
        if (now_sm - current_sm) > lookback_minutes:
            continue  # frozen: outside the editable window, leave as-is
        live_stop.arrival_time = template_stop.arrival_time
        live_stop.departure_time = template_stop.departure_time
        live_stop.sequence_order = template_stop.sequence_order

    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    ordered_stops = _trip_stops(db, trip_id)

    if trip.active_last_seq is not None and trip.active_last_seq + 1 < len(ordered_stops):
        boundary_sm = time_str_to_service_minutes(ordered_stops[trip.active_last_seq + 1].departure_time)
        if (now_sm - boundary_sm) <= lookback_minutes:
            trip.active_last_seq = None
    if trip.active_first_seq is not None and trip.active_first_seq < len(ordered_stops):
        boundary_sm = time_str_to_service_minutes(ordered_stops[trip.active_first_seq].departure_time)
        if (now_sm - boundary_sm) <= lookback_minutes:
            trip.active_first_seq = None

    db.commit()
    return get_trip(db, trip_id)
```

- [ ] **Step 4: Update the `app.py` endpoint (no signature change needed)**

`backend/src/app.py`'s `POST /api/trips/{trip_id}/reset` already calls `service.reset_trip(db, trip_id)` with no `now` — this still works because `now` defaults to `datetime.now()` inside `service.py`, and `test_api.py`'s existing `test_reset_trip_endpoint` already monkeypatches `src.service.datetime` (see `_freeze_service_now`), so `datetime.now()` resolves to the frozen value there. No code change required in `app.py` for this task.

- [ ] **Step 5: Run tests to verify they pass** (excluding the two skipped ones)

Run: `pytest backend/tests/test_service_reset.py -v`
Expected: PASS for the four non-skipped tests; 2 skipped.

- [ ] **Step 6: Run the full backend suite to check for regressions**

Run: `pytest backend/tests -v`
Expected: PASS. In particular, re-verify `backend/tests/test_api.py::test_reset_trip_endpoint` — it freezes `now` to `2026-08-13 05:00:00`, imports a trip with BFU at `05:00:00`, shifts it to `05:05:00`, then resets. At reset time the live stop is `05:05:00` and frozen `now` is `05:00:00` — `now_sm - current_sm` is negative (stop is "in the future" relative to now), so it's within lookback and reverts correctly to `05:00:00` — this test needs no changes. Confirm by running it explicitly: `pytest backend/tests/test_api.py::test_reset_trip_endpoint -v`.

- [ ] **Step 7: Commit**

```bash
git add backend/src/service.py backend/tests/test_service_reset.py
git commit -m "feat: reset_trip only reverts stops within the edit lookback window"
```

---

### Task 3: `suppress_from` (includes cancellation as the first-node case)

**Files:**
- Modify: `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_trip_edit.py` (new)

**Interfaces:**
- Consumes: `service.get_edit_lookback_minutes`, `_trip_stops` (existing)
- Produces: `service.suppress_from(db, trip_id: str, station_id: str, now: datetime | None = None) -> TripOut`
- Produces: `POST /api/trips/{trip_id}/suppress-from/{station_id}`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_trip_edit.py — new file
import pytest
from datetime import datetime

from src import service
from src.db import init_db
from src.errors import LookbackExceededError, StationNotFoundError, TripNotFoundError
from src.schemas import TemplateImportStop, TemplateImportTrip


def _seed(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="LUZ", time="05:10:00"),
                TemplateImportStop(station="BAS", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:30:00"),
            ],
        )
    ])


def test_suppress_from_sets_active_last_seq_to_the_stop_before(db_session):
    _seed(db_session)
    trip = service.suppress_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 4, 30, 0))
    assert trip.active_last_seq == 1  # LUZ (index 1) stays active; BAS (2) and RGS (3) suppressed


def test_suppress_from_the_first_stop_is_a_full_cancellation(db_session):
    _seed(db_session)
    trip = service.suppress_from(db_session, "TRIP_BFU-RGS_050000", "BFU", now=datetime(2026, 8, 13, 4, 30, 0))
    assert trip.active_last_seq == -1


def test_suppress_from_beyond_lookback_raises(db_session):
    _seed(db_session)
    with pytest.raises(LookbackExceededError):
        service.suppress_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 6, 0, 0))


def test_suppress_from_unknown_station_raises(db_session):
    _seed(db_session)
    with pytest.raises(StationNotFoundError):
        service.suppress_from(db_session, "TRIP_BFU-RGS_050000", "NOT_A_STATION", now=datetime(2026, 8, 13, 4, 30, 0))


def test_suppress_from_unknown_trip_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(TripNotFoundError):
        service.suppress_from(db_session, "NOT_A_TRIP", "BFU")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_trip_edit.py -v`
Expected: FAIL — `suppress_from` does not exist.

- [ ] **Step 3: Implement**

In `backend/src/service.py`:

```python
def suppress_from(db: Session, trip_id: str, station_id: str, now: datetime | None = None) -> TripOut:
    now = now or datetime.now()
    stops = _trip_stops(db, trip_id)
    if not stops:
        raise TripNotFoundError(trip_id)

    idx = next((i for i, s in enumerate(stops) if s.station_id == station_id), None)
    if idx is None:
        raise StationNotFoundError(station_id)

    target = stops[idx]
    lookback_minutes = get_edit_lookback_minutes(db)
    now_sm = datetime_to_service_minutes(now)
    target_sm = time_str_to_service_minutes(target.departure_time)
    if (now_sm - target_sm) > lookback_minutes:
        raise LookbackExceededError(
            f"Stop at {target.departure_time} is more than {lookback_minutes} minutes in the past"
        )

    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    trip.active_last_seq = idx - 1
    db.commit()
    return get_trip(db, trip_id)
```

- [ ] **Step 4: Wire the endpoint**

In `backend/src/app.py`:

```python
@app.post("/api/trips/{trip_id}/suppress-from/{station_id}", response_model=TripOut)
async def suppress_from(trip_id: str, station_id: str, db: Session = Depends(get_db)):
    trip = service.suppress_from(db, trip_id, station_id)
    await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return trip
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_trip_edit.py -v`
Expected: PASS

- [ ] **Step 6: Un-skip Task 2's dependent tests**

In `backend/tests/test_service_reset.py`, remove the `@pytest.mark.skip(...)` marker from `test_reset_trip_undoes_a_recent_suppress_from_boundary` and `test_reset_trip_leaves_an_old_suppress_from_boundary_in_place`.

Run: `pytest backend/tests/test_service_reset.py -v`
Expected: PASS (all 6 tests, none skipped)

- [ ] **Step 7: Commit**

```bash
git add backend/src/service.py backend/src/app.py backend/tests/test_service_trip_edit.py backend/tests/test_service_reset.py
git commit -m "feat: suppress a trip from a given stop onward (includes cancellation)"
```

---

### Task 4: `depart_from`

**Files:**
- Modify: `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_trip_edit.py`

**Interfaces:**
- Consumes: `service.get_edit_lookback_minutes`, `_trip_stops` (existing)
- Produces: `service.depart_from(db, trip_id: str, station_id: str, now: datetime | None = None) -> TripOut`
- Produces: `POST /api/trips/{trip_id}/depart-from/{station_id}`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_trip_edit.py — append
from src.errors import ChronologyViolationError


def test_depart_from_sets_active_first_seq(db_session):
    _seed(db_session)
    trip = service.depart_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 4, 30, 0))
    assert trip.active_first_seq == 2
    assert trip.stops[0].station == "BAS"  # get_trip still returns the full stop list; the
                                            # frontend uses active_first_seq to know what's suppressed


def test_depart_from_backward_is_rejected(db_session):
    _seed(db_session)
    service.depart_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 4, 30, 0))
    with pytest.raises(ChronologyViolationError):
        service.depart_from(db_session, "TRIP_BFU-RGS_050000", "LUZ", now=datetime(2026, 8, 13, 4, 30, 0))


def test_depart_from_beyond_active_last_seq_is_rejected(db_session):
    _seed(db_session)
    service.suppress_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 4, 30, 0))
    with pytest.raises(ChronologyViolationError):
        # active_last_seq is now 1 (LUZ); RGS (index 3) is beyond the active window.
        service.depart_from(db_session, "TRIP_BFU-RGS_050000", "RGS", now=datetime(2026, 8, 13, 4, 30, 0))


def test_depart_from_beyond_lookback_raises(db_session):
    _seed(db_session)
    with pytest.raises(LookbackExceededError):
        service.depart_from(db_session, "TRIP_BFU-RGS_050000", "BAS", now=datetime(2026, 8, 13, 6, 0, 0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_trip_edit.py -k depart_from -v`
Expected: FAIL — `depart_from` does not exist.

- [ ] **Step 3: Implement**

In `backend/src/service.py`:

```python
def depart_from(db: Session, trip_id: str, station_id: str, now: datetime | None = None) -> TripOut:
    now = now or datetime.now()
    stops = _trip_stops(db, trip_id)
    if not stops:
        raise TripNotFoundError(trip_id)

    idx = next((i for i, s in enumerate(stops) if s.station_id == station_id), None)
    if idx is None:
        raise StationNotFoundError(station_id)

    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    current_first = trip.active_first_seq or 0
    current_last = trip.active_last_seq if trip.active_last_seq is not None else len(stops) - 1

    if idx <= current_first:
        raise ChronologyViolationError("New departure must be further along the route than the current origin")
    if idx > current_last:
        raise ChronologyViolationError("New departure must be within the currently active route")

    target = stops[idx]
    lookback_minutes = get_edit_lookback_minutes(db)
    now_sm = datetime_to_service_minutes(now)
    target_sm = time_str_to_service_minutes(target.departure_time)
    if (now_sm - target_sm) > lookback_minutes:
        raise LookbackExceededError(
            f"Stop at {target.departure_time} is more than {lookback_minutes} minutes in the past"
        )

    trip.active_first_seq = idx
    db.commit()
    return get_trip(db, trip_id)
```

- [ ] **Step 4: Wire the endpoint**

In `backend/src/app.py`:

```python
@app.post("/api/trips/{trip_id}/depart-from/{station_id}", response_model=TripOut)
async def depart_from(trip_id: str, station_id: str, db: Session = Depends(get_db)):
    trip = service.depart_from(db, trip_id, station_id)
    await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return trip
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_trip_edit.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend suite**

Run: `pytest backend/tests -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/service.py backend/src/app.py backend/tests/test_service_trip_edit.py
git commit -m "feat: move a trip's origin forward, reusing its own existing stop time"
```

---

### Task 5: Context menu — "Suprimir a partir daqui"

**Files:**
- Modify: `frontend/src/app.js`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `showContextMenu` (Spec 1 plan Task 11), `POST /api/trips/{trip_id}/suppress-from/{station_id}` (Task 3)

- [ ] **Step 1: Attach the context menu to every draggable node**

In `frontend/src/app.js`, modify `drawTrainPaths`'s node-rendering loop (the `if (isSelected) { trip.stops.forEach(...) }` block) to add a `contextmenu` listener on each `circle`:

```javascript
                circle.addEventListener("contextmenu", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const menuItems = [
                        { label: "Suprimir a partir daqui", onClick: () => confirmSuppressFrom(trip, stop) },
                    ];
                    if (stopIdx === (trip.active_first_seq || 0)) {
                        menuItems.push({ label: "Alterar partida", onClick: () => startDepartFromMode(trip) });
                    }
                    showContextMenu(e.clientX, e.clientY, menuItems);
                });
```

(Insert this right after the existing `circle.addEventListener("mouseover", ...)`/`mouseout` lines, before `svg.appendChild(circle);`.)

- [ ] **Step 2: Implement `confirmSuppressFrom`**

```javascript
function confirmSuppressFrom(trip, stop) {
    const isFirstStop = stop.station === trip.stops[trip.active_first_seq || 0].station;
    const message = isFirstStop
        ? `Cancelar a viagem ${trip.train_code} inteira?`
        : `Suprimir ${trip.train_code} a partir de ${stop.station}?`;
    if (!confirm(message)) return;

    fetch(`/api/trips/${encodeURIComponent(trip.trip_id)}/suppress-from/${encodeURIComponent(stop.station)}`, {
        method: "POST",
    })
        .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
        .then(updatedTrip => applyTripUpdate(updatedTrip))
        .catch(err => alert("Não foi possível suprimir: " + err.message));
}
```

- [ ] **Step 3: Manually verify**

Select a trip, right-click an intermediate node → "Suprimir a partir daqui", confirm the prompt, verify the trip updates (Task 7 makes the suppressed portion visually dashed — until then, verify via the Network tab that the response's `active_last_seq` is correct). Right-click the trip's first node and confirm the confirmation message says "Cancelar a viagem inteira".

- [ ] **Step 4: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Suprimir a partir daqui / cancelar

1. Selecione uma viagem, botão direito num nó intermediário → "Suprimir a partir daqui" → confirme.
2. Verifique (aba Network) que `active_last_seq` corresponde ao nó anterior ao clicado.
3. Repita no primeiro nó da viagem — confirme que a mensagem de confirmação menciona cancelamento da viagem inteira.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: suprimir a partir daqui via context menu"
```

---

### Task 6: "Alterar partida" two-click flow

**Files:**
- Modify: `frontend/src/app.js`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `POST /api/trips/{trip_id}/depart-from/{station_id}` (Task 4)

- [ ] **Step 1: Implement the picking mode**

In `frontend/src/app.js`, add to `appState`'s initial definition: `departFromMode: null` (`null`, or `{ tripId }` mid-flow).

```javascript
function startDepartFromMode(trip) {
    appState.departFromMode = { tripId: trip.trip_id };
    document.getElementById("train-chart-svg").style.cursor = "crosshair";
}
```

Modify the same node-rendering loop from Task 5 to intercept clicks while in this mode — add a `click` listener alongside the existing `mousedown` one on each circle:

```javascript
                circle.addEventListener("click", (e) => {
                    if (!appState.departFromMode || appState.departFromMode.tripId !== trip.trip_id) return;
                    e.stopPropagation();
                    const targetStationId = stop.station;
                    appState.departFromMode = null;
                    document.getElementById("train-chart-svg").style.cursor = "default";

                    fetch(`/api/trips/${encodeURIComponent(trip.trip_id)}/depart-from/${encodeURIComponent(targetStationId)}`, {
                        method: "POST",
                    })
                        .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                        .then(updatedTrip => applyTripUpdate(updatedTrip))
                        .catch(err => alert("Não foi possível alterar a partida: " + err.message));
                });
```

- [ ] **Step 2: Manually verify**

Select a trip, right-click its current origin node → "Alterar partida", confirm the cursor becomes a crosshair, click a later node of the same trip, verify the request fires with the right station and the trip updates. Verify clicking a node of a *different* trip while in this mode does nothing (the `tripId` guard in Step 1 blocks it).

- [ ] **Step 3: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Alterar partida

1. Selecione uma viagem, botão direito no nó de partida atual → "Alterar partida".
2. Clique num nó mais à frente da mesma viagem — confirme que a partida muda para essa estação, mantendo o horário que a parada já tinha.
3. Tente escolher um nó de outra viagem enquanto o modo está ativo — confirme que nada acontece.
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: alterar partida two-click flow"
```

---

### Task 7: Dashed/no-drag rendering outside the active window

**Files:**
- Modify: `frontend/src/app.js`, `frontend/src/index.css`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `trip.active_first_seq`/`trip.active_last_seq` (Task 1, already flowing through `applyTripUpdate`/`initSchedule` unchanged since they're just new `TripOut` fields)

- [ ] **Step 1: Compute the active window bounds once per trip**

In `frontend/src/app.js`, add a small helper near `dxfYToSvg`:

```javascript
function activeStopRange(trip) {
    const first = trip.active_first_seq != null ? trip.active_first_seq : 0;
    const last = trip.active_last_seq != null ? trip.active_last_seq : trip.stops.length - 1;
    return { first, last };
}
```

- [ ] **Step 2: Skip drag handles and dash suppressed nodes**

In `drawTrainPaths`'s node-rendering loop, wrap the existing lookback-lock logic with the active-window check:

```javascript
            trip.stops.forEach((stop, stopIdx) => {
                const { first, last } = activeStopRange(trip);
                const isSuppressed = stopIdx < first || stopIdx > last;

                const px = timeToX(stop.time);
                const py = dxfYToSvg(stop.y_coord, appState.selectedLine);

                const circle = document.createElementNS(SVG_NS, "circle");
                circle.setAttribute("cx", px);
                circle.setAttribute("cy", py);
                circle.setAttribute("r", 5);
                circle.setAttribute("id", `node-${trip.trip_id}-${stopIdx}`);

                const nowMinutes = dateToServiceMinutes(new Date());
                const stopMinutes = timeStrToServiceMinutes(stop.time);
                const isLocked = (nowMinutes - stopMinutes) > appState.editLookbackMinutes;

                circle.className.baseVal = isSuppressed ? "time-node suppressed" : (isLocked ? "time-node locked" : "time-node");
                if (!isLocked && !isSuppressed) {
                    circle.addEventListener("mousedown", (e) => onNodeDragStart(e, trip.trip_id, stopIdx));
                }
                // ... existing mouseover/mouseout/contextmenu/click listeners (Tasks 5, 6) unchanged
```

- [ ] **Step 3: Dash the suppressed portion of the polyline**

Modify the polyline-building logic (both `pastPoints`/`futurePoints` from `splitTripAtNow`, and the hit area) to split at the active window boundary too. Simplest correct approach: filter `trip.stops` down to the active range *before* computing points, for the purposes of the solid rendering, and separately draw the suppressed portion(s) as their own dashed polyline(s):

```javascript
    lineTrips.forEach(trip => {
        const isSelected = appState.selectedTripId === trip.trip_id;
        const { first, last } = activeStopRange(trip);

        if (first > 0 || last < trip.stops.length - 1) {
            const suppressedBefore = trip.stops.slice(0, first + 1);  // includes one active point to connect the dash visually
            const suppressedAfter = trip.stops.slice(last, trip.stops.length);
            [suppressedBefore, suppressedAfter].forEach(segment => {
                if (segment.length < 2) return;
                const points = segment.map(s => `${timeToX(s.time)},${dxfYToSvg(s.y_coord, appState.selectedLine)}`).join(" ");
                const dashed = document.createElementNS(SVG_NS, "polyline");
                dashed.setAttribute("points", points);
                dashed.className.baseVal = "train-path-suppressed";
                svg.appendChild(dashed);
            });
        }

        const activeStops = trip.stops.slice(first, last + 1);
        const activeTrip = { ...trip, stops: activeStops };
        const { pastPoints, futurePoints } = splitTripAtNow(activeTrip, appState.selectedLine);
        // ... rest of the existing rendering (pastLine/futureLine/hitArea) uses activeStops/activeTrip
        // in place of trip/trip.stops wherever it currently reads trip.stops directly.
```

Note: this reassigns what the rest of the per-trip block reads from `trip.stops` to `activeStops`/`activeTrip.stops` for every existing reference inside this `forEach` (the hit-area polyline construction, the `if (isSelected)` node loop's `trip.stops.forEach` — change that to `activeStops.forEach` too, but keep using the ORIGINAL `stopIdx` from the full `trip.stops` array so `onNodeDragStart`/the context menu handlers still reference the correct absolute index; iterate with `activeStops.forEach((stop, i) => { const stopIdx = first + i; ... })` instead of relying on the slice's own local index).

- [ ] **Step 4: Add CSS**

In `frontend/src/index.css`:

```css
.train-path-suppressed {
    fill: none;
    stroke: var(--text-secondary, #999);
    stroke-width: 1.5;
    stroke-dasharray: 4, 4;
    opacity: 0.6;
}
.time-node.suppressed {
    fill: var(--text-secondary, #999);
    opacity: 0.5;
    cursor: default;
}
```

- [ ] **Step 5: Manually verify**

Suppress part of a trip (Task 5), confirm the suppressed portion renders dashed/gray and its nodes are not draggable (no `mousedown` effect) but the active portion still drags normally. Suppress from the first node (full cancellation) and confirm the entire trip renders dashed.

- [ ] **Step 6: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Renderização de trecho suprimido

1. Suprima parte de uma viagem — confirme que o trecho suprimido fica tracejado/cinza, sem alça de arraste.
2. Confirme que o trecho ainda ativo continua arrastável normalmente.
3. Cancele uma viagem inteira (suprimir a partir do primeiro nó) — confirme que a viagem inteira fica tracejada.
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app.js frontend/src/index.css frontend/tests/manual_test.md
git commit -m "feat: dashed/no-drag rendering for the suppressed portion of a trip"
```

---

## Self-Review

**Spec coverage:** `active_first_seq`/`active_last_seq` columns → Task 1. "Suprimir a partir daqui" (including cancellation-as-first-node) → Task 3, frontend Task 5. "Alterar partida" (forward-only, reuses existing stop time) → Task 4, frontend Task 6. Lookback validation on both new actions → Tasks 3, 4. "Reset só toca o futuro" general rule → Task 2 (applied to `reset_trip`; Spec 2a's plan already applied the equivalent rule to its own revert path independently, using the same `edit_lookback_minutes` setting — no shared code between the two, by design, since they revert different things: `reset_trip` reverts to template, Spec 2a's revert goes to a snapshot). Dashed/no-drag rendering → Task 7.

**Placeholder scan:** none.

**Type consistency:** `suppress_from`/`depart_from` (Tasks 3, 4) both return `TripOut` via the existing `get_trip` — consistent with `shift_stop`/`reset_trip`. `active_first_seq`/`active_last_seq` field names match exactly between `models.Trip` (Task 1), `schemas.TripOut` (Task 1), and every later task's frontend/backend reference (Tasks 2-7) — no drift (e.g. no `activeFirstSeq` camelCase mismatch anywhere; the frontend reads the same snake_case JSON keys FastAPI serializes, matching how every other field like `train_code`/`start_time` already works in `app.js`).

**Regression note:** Task 2 is the plan's highest-risk step — it changes `reset_trip`'s signature and behavior, and Step 6 of that task explicitly re-derives why the one pre-existing consumer (`test_api.py::test_reset_trip_endpoint`) still passes, rather than asserting it blindly. Any other future caller of `service.reset_trip` must account for the same lookback semantics.
