# Interdições Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a dispatcher mark a track segment as temporarily single-track (a red rectangle in time/space on the chart) and have the server automatically sequence the opposite-direction trains that would cross it, holding whichever one arrives first until the segment clears — instead of leaving that to manual node-dragging.

**Architecture:** Two new live-only tables (`interdictions`, `interdiction_stop_snapshots`) plus a pure-function geometry helper that finds where a trip's polyline crosses an arbitrary `[y_top, y_bottom]` band by linear interpolation between real stops (mirroring how the chart itself draws straight lines between stops). A FCFS sequencing pass — chronological by each trip's *natural* crossing time — decides who waits, and applies the same delta-propagation pattern `shift_stop` already uses. Editing or deleting an interdiction reverts only the stops that interdiction itself touched, using per-stop snapshots, honoring the same `edit_lookback_minutes` window `shift_stop` already respects (frozen stops are simply left alone). The frontend gets a two-click rectangle-drawing mode (mirroring Spec 1's) and renders a three-segment "dogleg" line — diagonal, flat wait, diagonal — for every trip the interdiction affects, using entry/exit times the backend computes, never re-deriving the queue itself.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), vanilla JS/SVG (frontend). Backend tests via pytest + FastAPI TestClient; frontend verified manually per `frontend/tests/manual_test.md`.

**Spec:** `docs/superpowers/specs/2026-08-16-interdicoes-design.md`

## Global Constraints

- `interdictions`/`interdiction_stop_snapshots` are live-only tables — never touched by the daily 03:00 reset job directly (they naturally stay empty on a fresh live day since nothing recreates them; no explicit cleanup code is needed — see Task 6).
- Revert (on edit or delete) only restores a stop if its **currently stored** `departure_time` is `>= now - edit_lookback_minutes` (reusing `service.get_edit_lookback_minutes`, the same setting `shift_stop` already checks). A frozen stop is left exactly as-is.
- A trip already inside the band (`entry_time <= now < exit_time` at the moment the interdiction is applied) is excluded entirely from the automatic algorithm — not even treated as the initial occupant.
- All interpolation and FCFS ordering happens in **service-day minutes** (`timeutils.time_str_to_service_minutes`), never raw clock minutes — mirrors every existing chronology check in `service.py` so a segment crossing midnight stays monotonic.
- This plan depends on Spec 1's frontend primitives: `showDialog` (`frontend/src/app.js`, Spec 1 plan Task 10) for the create/edit dialog, and the two-click interaction pattern established in Spec 1 plan Task 15 (not a shared function — the pattern is replicated here since it operates on the operational chart, not the schedule editor canvas).

---

## File Structure

**Backend:**
- `backend/src/models.py` — modify: add `Interdiction`, `InterdictionStopSnapshot`
- `backend/src/schemas.py` — modify: add `InterdictionIn`, `InterdictionOut`, `InterdictionAffectedTrip`, `InterdictionResult`; add `interdictions: List[InterdictionOut]` to `ScheduleOut`
- `backend/src/errors.py` — modify: add `InterdictionNotFoundError`
- `backend/src/interdiction.py` — new: pure geometry/sequencing helpers (`crossing_window`, `sequence_crossings`), kept separate from `service.py` because it has no DB dependency and is easiest to unit-test in isolation
- `backend/src/service.py` — modify: add `create_interdiction`, `update_interdiction`, `delete_interdiction`, `get_live_schedule` gains interdictions
- `backend/src/app.py` — modify: register endpoints, exception handler, broadcasts

**Backend tests:**
- `backend/tests/test_interdiction_geometry.py` — new: pure-function tests for `crossing_window`/`sequence_crossings`
- `backend/tests/test_service_interdictions.py` — new: service-layer tests (create/update/delete, snapshot revert, lookback freezing, "already inside" exclusion)
- `backend/tests/test_api_interdictions.py` — new: HTTP-layer tests, broadcast assertions

**Frontend:**
- `frontend/src/app.js` — modify: two-click rectangle creation, rectangle rendering, edit/delete dialog, dogleg rendering, WebSocket handling
- `frontend/src/index.html` — modify: "Interditar via" button
- `frontend/src/index.css` — modify: `.interdiction-rect` style

**Frontend manual tests:**
- `frontend/tests/manual_test.md` — modify: add interdiction scenarios

---

### Task 1: `Interdiction` and `InterdictionStopSnapshot` models

**Files:**
- Modify: `backend/src/models.py`
- Test: `backend/tests/test_service_interdictions.py` (new)

**Interfaces:**
- Produces: `models.Interdiction` (`id`, `y_top`, `y_bottom`, `start_time`, `end_time`, `description`), `models.InterdictionStopSnapshot` (`interdiction_id`, `trip_id`, `station_id`, `arrival_time`, `departure_time`, composite PK)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_service_interdictions.py — new file
from src.db import init_db
from src import models


def test_interdiction_models_round_trip(db_session):
    init_db(db_session.get_bind())
    interdiction = models.Interdiction(
        y_top=1000.0, y_bottom=1500.0, start_time="10:00:00", end_time="14:00:00",
        description="Obra de manutenção",
    )
    db_session.add(interdiction)
    db_session.commit()
    db_session.refresh(interdiction)

    snapshot = models.InterdictionStopSnapshot(
        interdiction_id=interdiction.id, trip_id="T1", station_id="SAN",
        arrival_time="10:05:00", departure_time="10:05:00",
    )
    db_session.add(snapshot)
    db_session.commit()

    fetched = db_session.query(models.Interdiction).first()
    assert fetched.description == "Obra de manutenção"
    assert db_session.query(models.InterdictionStopSnapshot).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_service_interdictions.py -v`
Expected: FAIL — `AttributeError: module 'src.models' has no attribute 'Interdiction'`

- [ ] **Step 3: Add the models**

In `backend/src/models.py`, append:

```python
class Interdiction(Base):
    __tablename__ = "interdictions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    y_top = Column(Float, nullable=False)
    y_bottom = Column(Float, nullable=False)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    description = Column(String, nullable=False, default="")


class InterdictionStopSnapshot(Base):
    __tablename__ = "interdiction_stop_snapshots"
    interdiction_id = Column(Integer, ForeignKey("interdictions.id", ondelete="CASCADE"), primary_key=True)
    trip_id = Column(String, primary_key=True)
    station_id = Column(String, primary_key=True)
    arrival_time = Column(String, nullable=False)
    departure_time = Column(String, nullable=False)
```

These are brand-new tables — `Base.metadata.create_all` (already called by `init_db`) creates them with no migration needed, unlike Task 1 of the Grades plan which altered an *existing* table.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_service_interdictions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/models.py backend/tests/test_service_interdictions.py
git commit -m "feat: add Interdiction and InterdictionStopSnapshot models"
```

---

### Task 2: Crossing geometry and FCFS sequencing (pure functions)

**Files:**
- Create: `backend/src/interdiction.py`
- Test: `backend/tests/test_interdiction_geometry.py` (new)

**Interfaces:**
- Produces: `crossing_window(stops: list[tuple[float, str, str]], y_top: float, y_bottom: float) -> CrossingWindow | None` where each stop tuple is `(y_coordinate, arrival_time, departure_time)` and `CrossingWindow` is `(entry_service_minutes, exit_service_minutes, first_affected_stop_index)`
- Produces: `sequence_crossings(candidates: list[Candidate]) -> list[SequencedCrossing]` where `Candidate = (key, direction_sign, entry_minutes, exit_minutes)` and `SequencedCrossing = (key, delta_minutes, entry_minutes, exit_minutes)` — pure FCFS walk, no DB, no I/O. `key` is opaque (the caller passes trip_id and gets it back).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_interdiction_geometry.py — new file
from src.interdiction import crossing_window, sequence_crossings


def test_crossing_window_finds_the_segment_that_enters_the_band():
    # Stop 0 at y=1000 t=10:00:00 (600 raw min), Stop 1 at y=2000 t=10:20:00 (620 min).
    # Band [1200, 1400] sits inside this segment.
    stops = [(1000.0, "10:00:00", "10:00:00"), (2000.0, "10:20:00", "10:20:00")]
    result = crossing_window(stops, y_top=1200.0, y_bottom=1400.0)
    assert result is not None
    entry, exit_, idx = result
    # 20% and 40% of the way from y=1000 to y=2000 -> +4min and +8min from 10:00 in
    # service-day minutes (service day starts 04:00, so 10:00 = 360 service-minutes).
    assert round(entry) == 364
    assert round(exit_) == 368
    assert idx == 1


def test_crossing_window_returns_none_when_band_is_never_touched():
    stops = [(1000.0, "10:00:00", "10:00:00"), (2000.0, "10:20:00", "10:20:00")]
    assert crossing_window(stops, y_top=3000.0, y_bottom=3500.0) is None


def test_crossing_window_handles_descending_direction():
    stops = [(2000.0, "10:00:00", "10:00:00"), (1000.0, "10:20:00", "10:20:00")]
    result = crossing_window(stops, y_top=1200.0, y_bottom=1400.0)
    assert result is not None
    entry, exit_, idx = result
    assert entry < exit_  # entry is always the earlier time regardless of travel direction


def test_sequence_crossings_holds_opposite_direction_when_it_would_arrive_early():
    # Direction 1 occupies until minute 20 (its own exit); direction -1 wants to enter at minute 10.
    candidates = [
        ("A", 1, 0.0, 20.0),
        ("B", -1, 10.0, 15.0),
    ]
    result = sequence_crossings(candidates)
    by_key = {key: (delta, entry, exit_) for key, delta, entry, exit_ in result}
    assert by_key["A"] == (0.0, 0.0, 20.0)  # first through, unmodified
    assert by_key["B"][0] == 10.0  # held 10 minutes: entry was 10, occupant free at 20
    assert by_key["B"][1] == 20.0  # new entry = 20 (right when the segment frees up)
    assert by_key["B"][2] == 25.0  # exit shifts by the same delta (original duration = 5min)


def test_sequence_crossings_same_direction_never_waits():
    candidates = [
        ("A", 1, 0.0, 10.0),
        ("B", 1, 5.0, 15.0),  # same direction, would overlap in time, but rule says no wait
    ]
    result = sequence_crossings(candidates)
    by_key = {key: delta for key, delta, _, _ in result}
    assert by_key["A"] == 0.0
    assert by_key["B"] == 0.0


def test_sequence_crossings_opposite_direction_after_segment_clears_does_not_wait():
    candidates = [
        ("A", 1, 0.0, 10.0),
        ("B", -1, 15.0, 20.0),  # enters after A already exited
    ]
    result = sequence_crossings(candidates)
    by_key = {key: delta for key, delta, _, _ in result}
    assert by_key["B"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_interdiction_geometry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.interdiction'`

- [ ] **Step 3: Implement**

Create `backend/src/interdiction.py`:

```python
from .timeutils import time_str_to_service_minutes


def crossing_window(stops, y_top: float, y_bottom: float):
    """stops: list of (y_coordinate, arrival_time, departure_time), in trip order.

    Returns (entry_service_minutes, exit_service_minutes, first_affected_stop_index)
    for the first stop-to-stop segment whose y-range overlaps [y_top, y_bottom], using
    each stop's departure_time (matching how the chart itself draws straight lines
    between consecutive stops — arrival/departure are not distinguished for geometry).
    Returns None if the trip's polyline never enters the band.
    """
    for i in range(len(stops) - 1):
        y_a, _, dep_a = stops[i]
        y_b, _, dep_b = stops[i + 1]
        seg_low, seg_high = min(y_a, y_b), max(y_a, y_b)
        if seg_high < y_top or seg_low > y_bottom or y_a == y_b:
            continue

        t_a = time_str_to_service_minutes(dep_a)
        t_b = time_str_to_service_minutes(dep_b)

        def time_at_y(y):
            frac = (y - y_a) / (y_b - y_a)
            return t_a + frac * (t_b - t_a)

        t_top = time_at_y(max(seg_low, y_top))
        t_bottom = time_at_y(min(seg_high, y_bottom))
        return min(t_top, t_bottom), max(t_top, t_bottom), i + 1
    return None


def sequence_crossings(candidates):
    """candidates: list of (key, direction_sign, entry_minutes, exit_minutes), any order.

    Returns a list of (key, delta_minutes, new_entry_minutes, new_exit_minutes), one per
    candidate, processed in ascending entry_minutes order (FCFS by natural entry time —
    never re-sorted after a delay is applied). Same-direction candidates never wait;
    opposite-direction candidates wait if they would enter before the segment frees up.
    """
    ordered = sorted(candidates, key=lambda c: c[2])
    occupant_direction = None
    free_at = None
    results = []

    for key, direction, entry, exit_ in ordered:
        delta = 0.0
        if occupant_direction is not None and direction != occupant_direction and entry < free_at:
            delta = free_at - entry

        new_entry = entry + delta
        new_exit = exit_ + delta

        if occupant_direction is None or direction != occupant_direction:
            occupant_direction = direction
            free_at = new_exit
        else:
            free_at = max(free_at, new_exit)

        results.append((key, delta, new_entry, new_exit))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_interdiction_geometry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/interdiction.py backend/tests/test_interdiction_geometry.py
git commit -m "feat: pure geometry and FCFS sequencing helpers for interdictions"
```

---

### Task 3: `create_interdiction` — the core algorithm, wired to the DB

**Files:**
- Modify: `backend/src/schemas.py`, `backend/src/service.py`, `backend/src/errors.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_interdictions.py`, `backend/tests/test_api_interdictions.py` (new)

**Interfaces:**
- Consumes: `interdiction.crossing_window`/`sequence_crossings` (Task 2), `models.Interdiction`/`InterdictionStopSnapshot` (Task 1), `service._station_y_lookup`/`_trip_stops` (existing), `service.get_edit_lookback_minutes` (existing)
- Produces: `service.create_interdiction(db, y_top, y_bottom, start_time, end_time, description, now=None) -> InterdictionResult`
- Produces: `POST /api/interdictions`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_interdictions.py — append
from datetime import datetime

from src import service
from src.schemas import TemplateImportStop, TemplateImportTrip


def _seed_two_opposite_trips(db_session):
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="TRIP_BFU-RGS_050000", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="BFU", time="05:00:00"),
                TemplateImportStop(station="SAN", time="05:20:00"),
                TemplateImportStop(station="RGS", time="05:40:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="TRIP_RGS-BFU_050500", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="RGS", time="05:05:00"),
                TemplateImportStop(station="SAN", time="05:25:00"),
                TemplateImportStop(station="BFU", time="05:45:00"),
            ],
        ),
    ])
    service.set_current_schedule_id(1)
    service.perform_daily_reset(db_session, now=datetime(2026, 8, 16, 4, 30, 0))


def test_create_interdiction_holds_the_second_train_at_the_edge(db_session):
    """SAN sits between the two trips' BFU/RGS endpoints; band brackets the BFU-SAN and
    RGS-SAN segments so both trips cross it. BFU-RGS crosses first (05:10ish), RGS-BFU
    would cross at ~05:15 but must wait until BFU-RGS clears."""
    _seed_two_opposite_trips(db_session)
    # y-coordinates: BFU=5860.32, SAN=2980.32, RGS=500.32 (backend/src/db.py STATIONS_METADATA)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    assert result.interdiction.description == "Obra"
    affected_by_trip = {a.trip_id: a for a in result.affected_trips}
    assert "TRIP_BFU-RGS_050000" in affected_by_trip
    assert "TRIP_RGS-BFU_050500" in affected_by_trip

    # The second (opposite-direction) trip's downstream stop must have shifted later.
    rgs_bfu_trip = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    original_bfu_time = "05:45:00"
    bfu_stop = next(s for s in rgs_bfu_trip.stops if s.station == "BFU")
    assert bfu_stop.time != original_bfu_time  # shifted downstream


def test_create_interdiction_excludes_trip_already_inside_the_band(db_session):
    _seed_two_opposite_trips(db_session)
    # now=05:15 is after TRIP_BFU-RGS's natural entry into the band (~05:10) and before
    # its exit (~05:20-ish) — it must not be touched by the automatic algorithm.
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Emergência",
        now=datetime(2026, 8, 16, 5, 15, 0),
    )
    affected_ids = {a.trip_id for a in result.affected_trips}
    assert "TRIP_BFU-RGS_050000" not in affected_ids


def test_create_interdiction_ignores_trips_outside_its_time_window(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="20:00:00", end_time="21:00:00", description="Noite",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    assert result.affected_trips == []
```

```python
# backend/tests/test_api_interdictions.py — new file
from datetime import datetime


def test_create_interdiction_endpoint(app_client, monkeypatch):
    from test_api import _freeze_service_now  # reuse the existing helper
    _freeze_service_now(monkeypatch, datetime(2026, 8, 16, 4, 30, 0))

    app_client.post("/api/template/import", json=[
        {
            "trip_id": "TRIP_BFU-RGS_050000", "direction": "BFU-RGS",
            "stops": [{"station": "BFU", "time": "05:00:00"}, {"station": "RGS", "time": "05:40:00"}],
        },
    ])

    response = app_client.post("/api/interdictions", json={
        "y_top": 1000.0, "y_bottom": 6000.0,
        "start_time": "05:00:00", "end_time": "06:00:00", "description": "Obra",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["interdiction"]["description"] == "Obra"
    assert len(body["affected_trips"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_interdictions.py backend/tests/test_api_interdictions.py -v`
Expected: FAIL — `create_interdiction` does not exist.

- [ ] **Step 3: Add schemas**

In `backend/src/schemas.py`:

```python
class InterdictionIn(BaseModel):
    y_top: float
    y_bottom: float
    start_time: str
    end_time: str
    description: str = ""


class InterdictionOut(BaseModel):
    id: int
    y_top: float
    y_bottom: float
    start_time: str
    end_time: str
    description: str

    class Config:
        from_attributes = True


class InterdictionAffectedTrip(BaseModel):
    trip_id: str
    entry_time: str
    exit_time: str


class InterdictionResult(BaseModel):
    interdiction: InterdictionOut
    affected_trips: List[InterdictionAffectedTrip]
```

Add `interdictions: List[InterdictionOut] = []` as a field on the existing `ScheduleOut` class (defaulting to an empty list keeps every pre-existing call site — which constructs `ScheduleOut(trips=trips_out)` without an `interdictions` kwarg — working unchanged).

- [ ] **Step 4: Add the error type**

In `backend/src/errors.py`:

```python
class InterdictionNotFoundError(Exception):
    def __init__(self, interdiction_id: int):
        self.interdiction_id = interdiction_id
        super().__init__(f"Interdiction not found: {interdiction_id}")
```

- [ ] **Step 5: Implement `create_interdiction`**

In `backend/src/service.py`, add imports (`from . import interdiction as interdiction_geometry`, `from .schemas import InterdictionIn, InterdictionOut, InterdictionAffectedTrip, InterdictionResult`, `from .errors import InterdictionNotFoundError`), then:

```python
def _direction_sign(stops, station_y: dict) -> int:
    first_y = station_y.get(stops[0].station_id, 0.0)
    last_y = station_y.get(stops[-1].station_id, 0.0)
    return 1 if last_y >= first_y else -1


def _service_minutes_to_time_str(service_minutes: float) -> str:
    from .timeutils import SERVICE_DAY_START_HOUR
    raw = (service_minutes + SERVICE_DAY_START_HOUR * 60) % (24 * 60)
    return minutes_to_time_str(raw)


def _apply_interdiction(db: Session, interdiction: models.Interdiction, now: datetime) -> list[InterdictionAffectedTrip]:
    station_y = _station_y_lookup(db)
    now_service_minutes = datetime_to_service_minutes(now)
    start_sm = time_str_to_service_minutes(interdiction.start_time)
    end_sm = time_str_to_service_minutes(interdiction.end_time)

    candidates = []  # (trip_id, direction_sign, entry_sm, exit_sm, first_affected_idx, stops)
    for trip in db.query(models.Trip).all():
        stops = _trip_stops(db, trip.id)
        if len(stops) < 2:
            continue
        geometry_stops = [(station_y.get(s.station_id, 0.0), s.arrival_time, s.departure_time) for s in stops]
        window = interdiction_geometry.crossing_window(geometry_stops, interdiction.y_top, interdiction.y_bottom)
        if window is None:
            continue
        entry_sm, exit_sm, first_idx = window
        if entry_sm >= end_sm or exit_sm <= start_sm:
            continue  # crossing happens outside the interdiction's active window
        if entry_sm <= now_service_minutes < exit_sm:
            continue  # already inside the band — always manual, per spec
        candidates.append((trip.id, _direction_sign(stops, station_y), entry_sm, exit_sm, first_idx, stops))

    sequenced = interdiction_geometry.sequence_crossings(
        [(c[0], c[1], c[2], c[3]) for c in candidates]
    )
    by_trip_id = {c[0]: c for c in candidates}

    affected = []
    for trip_id, delta, new_entry_sm, new_exit_sm in sequenced:
        _, _, _, _, first_idx, stops = by_trip_id[trip_id]
        if delta:
            for stop in stops[first_idx:]:
                existing = db.get(models.InterdictionStopSnapshot, (interdiction.id, trip_id, stop.station_id))
                if existing is None:
                    db.add(models.InterdictionStopSnapshot(
                        interdiction_id=interdiction.id, trip_id=trip_id, station_id=stop.station_id,
                        arrival_time=stop.arrival_time, departure_time=stop.departure_time,
                    ))
                stop.arrival_time = minutes_to_time_str(time_str_to_minutes(stop.arrival_time) + delta)
                stop.departure_time = minutes_to_time_str(time_str_to_minutes(stop.departure_time) + delta)
        affected.append(InterdictionAffectedTrip(
            trip_id=trip_id,
            entry_time=_service_minutes_to_time_str(new_entry_sm),
            exit_time=_service_minutes_to_time_str(new_exit_sm),
        ))

    db.commit()
    return affected


def create_interdiction(
    db: Session, y_top: float, y_bottom: float, start_time: str, end_time: str,
    description: str, now: datetime | None = None,
) -> InterdictionResult:
    now = now or datetime.now()
    top, bottom = min(y_top, y_bottom), max(y_top, y_bottom)
    interdiction = models.Interdiction(
        y_top=top, y_bottom=bottom, start_time=start_time, end_time=end_time, description=description,
    )
    db.add(interdiction)
    db.flush()

    affected = _apply_interdiction(db, interdiction, now)
    return InterdictionResult(interdiction=InterdictionOut.model_validate(interdiction), affected_trips=affected)
```

Note: `delta` in the "same-direction, never waits" and "opposite-direction, segment already clear" cases is always exactly `0.0` from `sequence_crossings` (Task 2), so the `if delta:` guard above correctly skips both the snapshot write and the stop mutation for those trips — they still appear in `affected_trips` (for frontend rendering) but their stored times are untouched.

- [ ] **Step 6: Wire the endpoint**

In `backend/src/app.py`:

```python
@app.post("/api/interdictions", response_model=InterdictionResult)
async def post_interdiction(payload: InterdictionIn, db: Session = Depends(get_db)):
    result = service.create_interdiction(
        db, payload.y_top, payload.y_bottom, payload.start_time, payload.end_time, payload.description,
    )
    await manager.broadcast({"type": "interdiction_changed", "result": result.model_dump()})
    return result
```

Add `InterdictionIn`, `InterdictionResult` to `app.py`'s schema imports.

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_interdictions.py backend/tests/test_api_interdictions.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/schemas.py backend/src/service.py backend/src/errors.py backend/src/app.py backend/tests/test_service_interdictions.py backend/tests/test_api_interdictions.py
git commit -m "feat: create interdiction — detect crossings, sequence, apply delays"
```

---

### Task 4: Revert-on-edit/delete respecting the lookback window

**Files:**
- Modify: `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_interdictions.py`, `backend/tests/test_api_interdictions.py`

**Interfaces:**
- Consumes: `_apply_interdiction` (Task 3), `service.get_edit_lookback_minutes` (existing)
- Produces: `service.update_interdiction(db, interdiction_id, y_top, y_bottom, start_time, end_time, description, now=None) -> InterdictionResult`, `service.delete_interdiction(db, interdiction_id, now=None) -> None`
- Produces: `PUT /api/interdictions/{id}`, `DELETE /api/interdictions/{id}`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_interdictions.py — append
from src.errors import InterdictionNotFoundError


def test_delete_interdiction_reverts_affected_stops_within_lookback(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    interdiction_id = result.interdiction.id
    rgs_bfu_before_delete = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    shifted_time = next(s.time for s in rgs_bfu_before_delete.stops if s.station == "BFU")
    assert shifted_time != "05:45:00"

    # Deletion happens at the same "now" — well within the default 15-min lookback of
    # every affected stop (all scheduled for ~05:20-05:45, now is 04:30... actually that's
    # in the FUTURE of now, always revertible; lookback only blocks stops in the PAST).
    service.delete_interdiction(db_session, interdiction_id, now=datetime(2026, 8, 16, 4, 30, 0))

    rgs_bfu_after = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    restored_time = next(s.time for s in rgs_bfu_after.stops if s.station == "BFU")
    assert restored_time == "05:45:00"


def test_delete_interdiction_leaves_frozen_stops_untouched(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    interdiction_id = result.interdiction.id

    # "Now" has moved to 07:00 — every affected stop (~05:20-05:45) is more than the
    # 15-minute default lookback in the past, so deletion must not touch them.
    rgs_bfu_before = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    shifted_time = next(s.time for s in rgs_bfu_before.stops if s.station == "BFU")

    service.delete_interdiction(db_session, interdiction_id, now=datetime(2026, 8, 16, 7, 0, 0))

    rgs_bfu_after = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    frozen_time = next(s.time for s in rgs_bfu_after.stops if s.station == "BFU")
    assert frozen_time == shifted_time  # untouched, not reverted


def test_update_interdiction_reverts_then_reapplies_with_new_window(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    interdiction_id = result.interdiction.id

    updated = service.update_interdiction(
        db_session, interdiction_id, y_top=3500.0, y_bottom=5000.0,
        start_time="20:00:00", end_time="21:00:00", description="Obra adiada",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    assert updated.affected_trips == []  # new window no longer overlaps either trip

    rgs_bfu_after = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    restored_time = next(s.time for s in rgs_bfu_after.stops if s.station == "BFU")
    assert restored_time == "05:45:00"  # reverted since the new window doesn't re-affect it


def test_delete_unknown_interdiction_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(InterdictionNotFoundError):
        service.delete_interdiction(db_session, 999)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_interdictions.py -k "delete_interdiction or update_interdiction" -v`
Expected: FAIL — functions don't exist.

- [ ] **Step 3: Implement**

In `backend/src/service.py`:

```python
def _get_interdiction_or_raise(db: Session, interdiction_id: int) -> models.Interdiction:
    interdiction = db.query(models.Interdiction).filter(models.Interdiction.id == interdiction_id).first()
    if interdiction is None:
        raise InterdictionNotFoundError(interdiction_id)
    return interdiction


def _revert_interdiction(db: Session, interdiction_id: int, now: datetime) -> None:
    lookback_minutes = get_edit_lookback_minutes(db)
    now_sm = datetime_to_service_minutes(now)

    snapshots = (
        db.query(models.InterdictionStopSnapshot)
        .filter(models.InterdictionStopSnapshot.interdiction_id == interdiction_id)
        .all()
    )
    for snapshot in snapshots:
        stop = (
            db.query(models.PlannedStop)
            .filter(
                models.PlannedStop.trip_id == snapshot.trip_id,
                models.PlannedStop.station_id == snapshot.station_id,
            )
            .first()
        )
        if stop is None:
            continue
        current_sm = time_str_to_service_minutes(stop.departure_time)
        if (now_sm - current_sm) > lookback_minutes:
            continue  # frozen: outside the editable window, leave as-is
        stop.arrival_time = snapshot.arrival_time
        stop.departure_time = snapshot.departure_time

    db.query(models.InterdictionStopSnapshot).filter(
        models.InterdictionStopSnapshot.interdiction_id == interdiction_id
    ).delete()
    db.commit()


def update_interdiction(
    db: Session, interdiction_id: int, y_top: float, y_bottom: float,
    start_time: str, end_time: str, description: str, now: datetime | None = None,
) -> InterdictionResult:
    now = now or datetime.now()
    interdiction = _get_interdiction_or_raise(db, interdiction_id)

    _revert_interdiction(db, interdiction_id, now)

    top, bottom = min(y_top, y_bottom), max(y_top, y_bottom)
    interdiction.y_top, interdiction.y_bottom = top, bottom
    interdiction.start_time, interdiction.end_time = start_time, end_time
    interdiction.description = description
    db.commit()

    affected = _apply_interdiction(db, interdiction, now)
    return InterdictionResult(interdiction=InterdictionOut.model_validate(interdiction), affected_trips=affected)


def delete_interdiction(db: Session, interdiction_id: int, now: datetime | None = None) -> None:
    now = now or datetime.now()
    _get_interdiction_or_raise(db, interdiction_id)
    _revert_interdiction(db, interdiction_id, now)
    db.query(models.Interdiction).filter(models.Interdiction.id == interdiction_id).delete()
    db.commit()
```

- [ ] **Step 4: Wire the endpoints**

In `backend/src/app.py`:

```python
@app.exception_handler(InterdictionNotFoundError)
def _interdiction_not_found(request, exc: InterdictionNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.put("/api/interdictions/{interdiction_id}", response_model=InterdictionResult)
async def put_interdiction(interdiction_id: int, payload: InterdictionIn, db: Session = Depends(get_db)):
    result = service.update_interdiction(
        db, interdiction_id, payload.y_top, payload.y_bottom,
        payload.start_time, payload.end_time, payload.description,
    )
    await manager.broadcast({"type": "interdiction_changed", "result": result.model_dump()})
    return result


@app.delete("/api/interdictions/{interdiction_id}")
async def delete_interdiction(interdiction_id: int, db: Session = Depends(get_db)):
    service.delete_interdiction(db, interdiction_id)
    await manager.broadcast({"type": "interdiction_deleted", "interdiction_id": interdiction_id})
    return {"deleted": interdiction_id}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_interdictions.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/service.py backend/src/app.py backend/tests/test_service_interdictions.py
git commit -m "feat: edit/delete interdiction with lookback-aware revert"
```

---

### Task 5: `GET /api/schedule` includes interdictions

**Files:**
- Modify: `backend/src/service.py`
- Test: `backend/tests/test_api_interdictions.py`

**Interfaces:**
- Consumes: `models.Interdiction` (Task 1)
- Modifies: `service.get_live_schedule` — now populates `ScheduleOut.interdictions`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_api_interdictions.py — append
def test_get_schedule_includes_active_interdictions(app_client, monkeypatch):
    from datetime import datetime
    from test_api import _freeze_service_now
    _freeze_service_now(monkeypatch, datetime(2026, 8, 16, 4, 30, 0))

    app_client.post("/api/template/import", json=[
        {"trip_id": "T1", "direction": "BFU-RGS", "stops": [{"station": "BFU", "time": "05:00:00"}]},
    ])
    app_client.post("/api/interdictions", json={
        "y_top": 1000.0, "y_bottom": 2000.0, "start_time": "05:00:00", "end_time": "06:00:00",
        "description": "Obra",
    })

    response = app_client.get("/api/schedule")
    assert len(response.json()["interdictions"]) == 1
    assert response.json()["interdictions"][0]["description"] == "Obra"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_api_interdictions.py::test_get_schedule_includes_active_interdictions -v`
Expected: FAIL — `interdictions` key is an empty list regardless (the field defaults, `get_live_schedule` never populates it).

- [ ] **Step 3: Implement**

In `backend/src/service.py`, modify `get_live_schedule`:

```python
def get_live_schedule(db: Session) -> ScheduleOut:
    station_y = _station_y_lookup(db)
    trips_out = []
    for trip in db.query(models.Trip).all():
        stops = _trip_stops(db, trip.id)
        if not stops:
            continue
        trips_out.append(_trip_to_out(trip, stops, station_y))
    interdictions_out = [
        InterdictionOut.model_validate(i) for i in db.query(models.Interdiction).all()
    ]
    return ScheduleOut(trips=trips_out, interdictions=interdictions_out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_api_interdictions.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `pytest backend/tests -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/service.py backend/tests/test_api_interdictions.py
git commit -m "feat: include active interdictions in GET /api/schedule"
```

---

### Task 6: Two-click rectangle creation

**Files:**
- Modify: `frontend/src/app.js`, `frontend/src/index.html`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `showDialog` (Spec 1 plan Task 10), `xToTime`/`dxfYToSvg` (existing), `POST /api/interdictions` (Task 3)

- [ ] **Step 1: Add the trigger button**

In `frontend/src/index.html`, inside `.chart-action-buttons` (next to the existing "Resetar" button):

```html
<button class="btn btn-secondary btn-sm" id="btn-interdict" onclick="startInterdictionCreationMode()">🚧 Interditar Via</button>
```

- [ ] **Step 2: Implement the two-click capture**

In `frontend/src/app.js`, add to `appState`'s initial definition: `interdictionCreationMode: null`.

```javascript
// ==========================================================================
// Interdictions
// ==========================================================================
function startInterdictionCreationMode() {
    appState.interdictionCreationMode = {};
    document.getElementById("train-chart-svg").style.cursor = "crosshair";
}

function onChartClickForInterdiction(e) {
    if (!appState.interdictionCreationMode) return;

    const svg = document.getElementById("train-chart-svg");
    const rect = svg.getBoundingClientRect();
    const svgX = e.clientX - rect.left;
    const svgY = e.clientY - rect.top;
    const point = { time: xToTime(svgX), y: svgYToDxfY(svgY) };

    if (!appState.interdictionCreationMode.firstPoint) {
        appState.interdictionCreationMode.firstPoint = point;
        return;
    }

    const secondPoint = point;
    const firstPoint = appState.interdictionCreationMode.firstPoint;
    appState.interdictionCreationMode = null;
    svg.style.cursor = "default";
    openInterdictionDialog(firstPoint, secondPoint);
}

// Inverse of dxfYToSvg for the currently selected line — needed because interdiction
// rectangles are drawn freehand, not snapped to a station like yToStation (Spec 1).
function svgYToDxfY(svgY) {
    const lineStations = stations[appState.selectedLine];
    const minY = lineStations[lineStations.length - 1].y_dxf;
    const maxY = lineStations[0].y_dxf;
    const pct = (svgY - MARGIN_TOP) / USABLE_HEIGHT;
    return maxY - pct * (maxY - minY);
}

function openInterdictionDialog(firstPoint, secondPoint, existing = null) {
    showDialog({
        title: existing ? "Editar Interdição" : "Nova Interdição",
        fields: [
            { name: "description", label: "Descrição", value: existing ? existing.description : "" },
            { name: "start_time", label: "Hora inicial", type: "time",
              value: (existing ? existing.start_time : firstPoint.time).substring(0, 5) },
            { name: "end_time", label: "Hora final", type: "time",
              value: (existing ? existing.end_time : secondPoint.time).substring(0, 5) },
        ],
        confirmLabel: existing ? "Salvar" : "Criar",
        onConfirm: (values) => {
            const body = {
                y_top: existing ? existing.y_top : Math.min(firstPoint.y, secondPoint.y),
                y_bottom: existing ? existing.y_bottom : Math.max(firstPoint.y, secondPoint.y),
                start_time: values.start_time + ":00",
                end_time: values.end_time + ":00",
                description: values.description,
            };
            const url = existing ? `/api/interdictions/${existing.id}` : "/api/interdictions";
            fetch(url, {
                method: existing ? "PUT" : "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                .then(() => reloadScheduleFromServer())
                .catch(err => alert("Não foi possível salvar a interdição: " + err.message));
        },
    });
}
```

In `frontend/src/app.js`'s `renderChart()`, add the click listener alongside the existing drag listeners:

```javascript
svg.addEventListener("click", onChartClickForInterdiction);
```

- [ ] **Step 3: Manually verify**

Reload the app, click "🚧 Interditar Via", click two points on the chart at different times/heights, fill in the dialog, confirm, and verify (via `GET /api/schedule` in the browser network tab, or the next task's rendering) that the interdiction was created.

- [ ] **Step 4: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Criar interdição

1. Clique em "🚧 Interditar Via".
2. Clique em dois pontos do gráfico (tempos/estações diferentes) — confirme que o diálogo abre com hora inicial/final pré-preenchidas pelos cliques.
3. Preencha a descrição e confirme — a chamada `POST /api/interdictions` deve retornar 200 (verificar na aba Network).
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app.js frontend/src/index.html frontend/tests/manual_test.md
git commit -m "feat: two-click interdiction creation"
```

---

### Task 7: Render the rectangle, click-to-edit/delete

**Files:**
- Modify: `frontend/src/app.js`, `frontend/src/index.css`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `openInterdictionDialog` (Task 6), `DELETE /api/interdictions/{id}` (Task 4), `appState.trips`'s sibling `appState.interdictions`

- [ ] **Step 1: Store interdictions in app state and render rectangles**

In `frontend/src/app.js`, modify `initSchedule`/`applyTripUpdate`-adjacent loading code: wherever `data.trips` is assigned to `appState.trips` (in `loadDefaultSchedule`, `reloadScheduleFromServer`), also assign `appState.interdictions = data.interdictions || []`.

Add rendering, called from `renderChart()` right after `drawTrainPaths(svg)`:

```javascript
function drawInterdictions(svg) {
    (appState.interdictions || []).forEach(interdiction => {
        const x1 = timeToX(interdiction.start_time);
        const x2 = timeToX(interdiction.end_time);
        const y1 = dxfYToSvg(interdiction.y_top, appState.selectedLine);
        const y2 = dxfYToSvg(interdiction.y_bottom, appState.selectedLine);

        const rect = document.createElementNS(SVG_NS, "rect");
        rect.setAttribute("x", Math.min(x1, x2));
        rect.setAttribute("y", Math.min(y1, y2));
        rect.setAttribute("width", Math.abs(x2 - x1));
        rect.setAttribute("height", Math.abs(y2 - y1));
        rect.className.baseVal = "interdiction-rect";
        rect.addEventListener("click", (e) => {
            e.stopPropagation();  // don't also trigger onChartClickForInterdiction
            openInterdictionDialog(null, null, interdiction);
        });
        svg.appendChild(rect);

        const label = document.createElementNS(SVG_NS, "text");
        label.setAttribute("x", Math.min(x1, x2) + 6);
        label.setAttribute("y", Math.min(y1, y2) + 16);
        label.className.baseVal = "interdiction-label";
        label.textContent = interdiction.description;
        svg.appendChild(label);
    });
}
```

Call `drawInterdictions(svg);` in `renderChart()` after `drawTrainPaths(svg);`.

- [ ] **Step 2: Add the delete action to the edit dialog**

Modify `openInterdictionDialog` (Task 6) to add a delete button when `existing` is set — `showDialog`'s contract (Task 10 of the Grades plan) doesn't support extra buttons, so build this dialog's confirm area directly instead of through `showDialog` for the `existing` case:

```javascript
function openInterdictionDialog(firstPoint, secondPoint, existing = null) {
    if (existing) {
        const overlay = document.getElementById("dialog-overlay");
        const box = document.getElementById("dialog-box");
        box.innerHTML = `
            <h3>Editar Interdição</h3>
            <div class="dialog-field"><label>Descrição</label><input id="id-description" value="${existing.description}"></div>
            <div class="dialog-field"><label>Hora inicial</label><input id="id-start" type="time" value="${existing.start_time.substring(0, 5)}"></div>
            <div class="dialog-field"><label>Hora final</label><input id="id-end" type="time" value="${existing.end_time.substring(0, 5)}"></div>
            <div class="dialog-actions">
                <button class="btn btn-secondary btn-sm" id="id-delete">Excluir</button>
                <button class="btn btn-secondary btn-sm" id="dialog-cancel">Cancelar</button>
                <button class="btn btn-primary btn-sm" id="dialog-confirm">Salvar</button>
            </div>
        `;
        overlay.classList.remove("hidden");
        const close = () => overlay.classList.add("hidden");
        document.getElementById("dialog-cancel").onclick = close;
        document.getElementById("id-delete").onclick = () => {
            if (!confirm("Excluir esta interdição?")) return;
            close();
            fetch(`/api/interdictions/${existing.id}`, { method: "DELETE" })
                .then(r => { if (!r.ok) throw new Error("Falha ao excluir"); return reloadScheduleFromServer(); })
                .catch(err => alert(err.message));
        };
        document.getElementById("dialog-confirm").onclick = () => {
            close();
            fetch(`/api/interdictions/${existing.id}`, {
                method: "PUT", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    y_top: existing.y_top, y_bottom: existing.y_bottom,
                    start_time: document.getElementById("id-start").value + ":00",
                    end_time: document.getElementById("id-end").value + ":00",
                    description: document.getElementById("id-description").value,
                }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return reloadScheduleFromServer(); })
                .catch(err => alert("Não foi possível salvar: " + err.message));
        };
        return;
    }

    // ... existing showDialog-based creation flow from Task 6 stays for the `!existing` case
    showDialog({
        title: "Nova Interdição",
        fields: [
            { name: "description", label: "Descrição", value: "" },
            { name: "start_time", label: "Hora inicial", type: "time", value: firstPoint.time.substring(0, 5) },
            { name: "end_time", label: "Hora final", type: "time", value: secondPoint.time.substring(0, 5) },
        ],
        confirmLabel: "Criar",
        onConfirm: (values) => {
            fetch("/api/interdictions", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    y_top: Math.min(firstPoint.y, secondPoint.y),
                    y_bottom: Math.max(firstPoint.y, secondPoint.y),
                    start_time: values.start_time + ":00",
                    end_time: values.end_time + ":00",
                    description: values.description,
                }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return reloadScheduleFromServer(); })
                .catch(err => alert("Não foi possível criar a interdição: " + err.message));
        },
    });
}
```

This replaces the `openInterdictionDialog` body written in Task 6, Step 2 — Task 6's version is superseded, not additive.

- [ ] **Step 3: Add CSS**

In `frontend/src/index.css`:

```css
.interdiction-rect {
    fill: rgba(220, 38, 38, 0.18);
    stroke: rgba(220, 38, 38, 0.6);
    stroke-width: 1;
    cursor: pointer;
}
.interdiction-label {
    font-size: 11px;
    fill: rgba(220, 38, 38, 0.9);
    pointer-events: none;
}
```

- [ ] **Step 4: Manually verify**

Create an interdiction (Task 6's flow), confirm the red translucent rectangle renders at the right time/position with its description label. Click the rectangle, confirm the edit dialog opens pre-filled; change the description and save, confirm the label updates. Open it again and click "Excluir", confirm the rectangle disappears.

- [ ] **Step 5: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Editar/excluir interdição

1. Com uma interdição criada, confirme o retângulo vermelho translúcido no gráfico, com a descrição visível.
2. Clique no retângulo — confirme o diálogo abre pré-preenchido.
3. Altere a descrição, salve — confirme que o rótulo atualiza.
4. Reabra e clique "Excluir" — confirme o retângulo some do gráfico.
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app.js frontend/src/index.css frontend/tests/manual_test.md
git commit -m "feat: render interdiction rectangle, click-to-edit/delete"
```

---

### Task 8: Dogleg rendering for affected trips

**Files:**
- Modify: `frontend/src/app.js`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `InterdictionResult.affected_trips` — but note `GET /api/schedule` (Task 5) does **not** return `entry_time`/`exit_time` per trip, only the create/edit response does. This task must derive the dogleg geometry client-side from the **already-shifted stop times** plus the interdiction's own bounds, not from a separately-tracked `entry_time`/`exit_time` map (see Step 1).

- [ ] **Step 1: Derive the dogleg segments from stop times and interdiction bounds**

Since `entry_time`/`exit_time` aren't persisted (only returned transiently from create/edit responses — see spec's "Passo 3" and the API table, which never lists a GET-time per-trip crossing endpoint), reconstruct them client-side the same way the backend does: interpolate between whichever two consecutive real stops bracket each interdiction's `[y_top, y_bottom]` band, using the trip's **current** (already-authoritative) stop times. This is geometry only — no FCFS logic is duplicated, matching the spec's "frontend não reimplementa a fila" (the ordering/holding decision was already baked into the stop times by the backend; the frontend just has to find where the resulting line crosses the band).

In `frontend/src/app.js`, add:

```javascript
// Mirrors backend/src/interdiction.py's crossing_window, but operating on the
// already-server-computed (possibly delayed) stop times — pure rendering geometry,
// not a reimplementation of the FCFS queueing decision itself.
function findInterdictionCrossing(trip, interdiction, selectedLine) {
    for (let i = 0; i < trip.stops.length - 1; i++) {
        const yA = trip.stops[i].y_coord, yB = trip.stops[i + 1].y_coord;
        const segLow = Math.min(yA, yB), segHigh = Math.max(yA, yB);
        if (segHigh < interdiction.y_top || segLow > interdiction.y_bottom || yA === yB) continue;

        const tA = timeStrToServiceMinutes(trip.stops[i].time);
        const tB = timeStrToServiceMinutes(trip.stops[i + 1].time);
        const timeAtY = (y) => tA + ((y - yA) / (yB - yA)) * (tB - tA);

        const tTop = timeAtY(Math.max(segLow, interdiction.y_top));
        const tBottom = timeAtY(Math.min(segHigh, interdiction.y_bottom));
        return {
            beforeIdx: i,
            afterIdx: i + 1,
            entryY: yA <= yB ? interdiction.y_top : interdiction.y_bottom,
            exitY: yA <= yB ? interdiction.y_bottom : interdiction.y_top,
            entryServiceMin: Math.min(tTop, tBottom),
            exitServiceMin: Math.max(tTop, tBottom),
        };
    }
    return null;
}

function serviceMinutesToTimeStr(serviceMinutes) {
    const raw = (serviceMinutes + START_HOUR * 60) % (24 * 60);
    return minutesToTimeStr(raw);
}
```

- [ ] **Step 2: Replace the affected portion of the polyline with a 3-segment dogleg**

Modify `drawTrainPaths` (in the `futurePoints.length >= 2` branch, since a dogleg only ever applies to a not-yet-passed portion of the trip): after computing `futurePoints`, for each active interdiction check if this trip crosses it and splice in the dogleg points.

```javascript
    lineTrips.forEach(trip => {
        const isSelected = appState.selectedTripId === trip.trip_id;
        let { pastPoints, futurePoints } = splitTripAtNow(trip, appState.selectedLine);

        (appState.interdictions || []).forEach(interdiction => {
            const crossing = findInterdictionCrossing(trip, interdiction, appState.selectedLine);
            if (!crossing) return;
            const entryX = timeToX(serviceMinutesToTimeStr(crossing.entryServiceMin));
            const exitX = timeToX(serviceMinutesToTimeStr(crossing.exitServiceMin));
            const entrySvgY = dxfYToSvg(crossing.entryY, appState.selectedLine);
            const exitSvgY = dxfYToSvg(crossing.exitY, appState.selectedLine);

            // Rebuild futurePoints, inserting the flat-wait segment between the two
            // real stops that bracket the crossing (only if that pair is in the future).
            const beforeStop = trip.stops[crossing.beforeIdx];
            const afterStop = trip.stops[crossing.afterIdx];
            const beforeX = timeToX(beforeStop.time), afterX = timeToX(afterStop.time);
            const rebuilt = [];
            for (const p of futurePoints) {
                rebuilt.push(p);
                if (p.x === beforeX && p.y === dxfYToSvg(beforeStop.y_coord, appState.selectedLine)) {
                    rebuilt.push({ x: entryX, y: entrySvgY });
                    rebuilt.push({ x: exitX, y: exitSvgY });
                }
            }
            futurePoints = rebuilt;
        });

        // ... rest of the function (pastLine/futureLine/hitArea/nodes) unchanged, using
        // the possibly-modified futurePoints from above instead of the original.
```

- [ ] **Step 3: Manually verify**

With an interdiction active and a held trip (per Task 3's server-side hold logic), confirm its future line shows: diagonal to the band edge, a flat horizontal segment across the red rectangle's time span at that edge, then a diagonal continuing to the next real station. Confirm a trip that crosses the band but was never held (passes straight through) still renders a normal, unbroken diagonal (its `entry`/`exit` collapse to the same natural line, so the dogleg is visually a no-op).

- [ ] **Step 4: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Dogleg de trem retido na interdição

1. Crie uma interdição que afete dois trens de sentidos opostos com tempos de cruzamento próximos.
2. Confirme que o trem retido mostra o "dogleg": diagonal até a borda, segmento reto (parado) atravessando o retângulo, diagonal de volta até a próxima estação.
3. Confirme que um trem que cruza sem ser retido continua com uma linha reta normal.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: render dogleg line for trips held at an interdiction"
```

---

### Task 9: WebSocket live sync for interdiction changes

**Files:**
- Modify: `frontend/src/app.js`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `interdiction_changed`/`interdiction_deleted` broadcast messages (Tasks 3, 4)

- [ ] **Step 1: Handle the new message types**

In `frontend/src/app.js`, modify `connectLiveUpdates`'s `socket.onmessage` handler — its current early-return (`if (message.type !== "trip_updated" && message.type !== "schedule_reset") return;`) must let the two new types through:

```javascript
    socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        const knownTypes = ["trip_updated", "schedule_reset", "interdiction_changed", "interdiction_deleted"];
        if (!knownTypes.includes(message.type)) return;

        if (appState.dragNode) {
            appState.pendingRerender = true;
            return;
        }

        if (message.type === "trip_updated") {
            applyTripUpdate(message.trip);
        } else if (message.type === "interdiction_changed" || message.type === "interdiction_deleted") {
            reloadScheduleFromServer();  // simplest correct option: interdiction changes can touch multiple trips at once
        } else {
            reloadScheduleFromServer();
        }
    };
```

- [ ] **Step 2: Manually verify**

Open the app in two browser tabs. In tab A, create an interdiction. Confirm tab B's chart updates (rectangle appears, affected trips show doglegs) without a manual reload. Edit and delete from tab A, confirm tab B reflects both.

- [ ] **Step 3: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Sincronização ao vivo de interdições

1. Abra o app em duas abas.
2. Crie uma interdição na aba A — confirme que a aba B atualiza sozinha (retângulo e doglegs).
3. Edite e depois exclua na aba A — confirme que a aba B acompanha as duas mudanças.
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: live-sync interdiction changes over WebSocket"
```

---

## Self-Review

**Spec coverage:** Data model (`interdictions`, `interdiction_stop_snapshots`) → Task 1. Crossing detection + FCFS queue → Task 2 (pure) + Task 3 (wired). "Trem já dentro" exclusion → Task 3. Lookback-aware revert on edit/delete → Task 4 (implements the spec's amendment inline, using the already-existing `edit_lookback_minutes` setting — no dependency on Spec 2b's plan being implemented first). `GET /api/schedule` interdictions list → Task 5. Two-click creation, rectangle rendering, edit/delete dialog → Tasks 6-7. Dogleg rendering → Task 8. WebSocket broadcast → Tasks 3-4 (backend), Task 9 (frontend).

**Placeholder scan:** none.

**Type consistency:** `InterdictionResult`/`InterdictionOut`/`InterdictionAffectedTrip` (Task 3) are the same shapes used by Task 4's `update_interdiction`/Task 5's `ScheduleOut.interdictions`. `_apply_interdiction`'s `first_idx` return value from `crossing_window` (Task 2) is consumed identically in Task 3's snapshot/mutation loop. Frontend's `findInterdictionCrossing` (Task 8) field names (`beforeIdx`/`afterIdx`/`entryServiceMin`/`exitServiceMin`) are self-contained to that task, not shared with any backend response shape — deliberately, since Task 8's Step 1 explains why the frontend recomputes geometry instead of consuming a field the API never persists past the initial create/edit response.

**Note on `GET /api/schedule` and per-trip crossing times:** the design spec's API table describes `entry_time`/`exit_time` only as part of the create/edit response, not as part of `ScheduleOut`. Task 8 resolves this gap by having the frontend recompute the (already-decided) crossing geometry from the live stop times whenever it renders — consistent with "o frontend não reimplementa a fila FCFS" (only geometry is derived, never the queueing decision, which is fully baked into the stop times by the time the frontend ever sees them).
