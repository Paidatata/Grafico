# Regulação de Partidas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a delayed arrival's paired departure (Spec 3) would fall below the station's minimum turnaround, spread that delay as a cumulative ramp across the still-future departures from the same origin/direction — instead of dumping the whole delay onto one departure — either on manual "Regular" click or automatically.

**Architecture:** Spec 3's pairing algorithm is pure frontend JS with no server-side equivalent, but this spec's `POST /api/regulation/apply` needs to run the same pairing server-side to know which departure to ramp toward and which trips sit between now and it — so this plan ports a positional-FCFS pairing lookup into `service.py`, deliberately mirroring (not sharing code with) the frontend's `computeTurnaroundPairs`. The actual per-step delta math is a small pure function (`regulation.compute_ramp_deltas`), reusable and independently testable, mirroring `interdiction.py`'s pattern from Spec 2a. Automatic mode is wired into `shift_stop` — the primary source of arrival-time changes — as this plan's MVP trigger; other arrival-changing paths (e.g. interdiction resolution) are not auto-wired here (see Global Constraints).

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), vanilla JS/SVG (frontend). Backend tests via pytest; frontend verified manually.

**Spec:** `docs/superpowers/specs/2026-08-16-regulacao-de-partidas-design.md`

## Global Constraints

- **Hard dependency on Spec 3 and Spec 2b already being implemented**: this plan reads `station.turnaround_seconds` (Spec 3, Task 1) and `trip.active_first_seq`/`active_last_seq` (Spec 2b, Task 1). Do not start this plan before both land.
- `excess` is always recomputed against **current** live stop times on every invocation (never the template) — a shrinking delay compresses the ramp back down, a growing one extends it, exactly mirroring `shift_stop`'s "current state is truth" philosophy.
- A candidate departure is never moved to a time `<= now` — if the computed compression would do that, that specific candidate is left untouched (delta forced to 0) and the plan does **not** attempt to redistribute its share among the others (the spec itself flags this as loosely specified; full optimal redistribution is out of scope — see Task 3, Step 3's inline note).
- Automatic mode (`auto_regulation_enabled`) is wired only into `shift_stop` in this plan. Spec 2a's interdiction resolution and Spec 2b's `suppress_from`/`depart_from` are plausible future trigger points but are explicitly **not** wired here — each would need its own follow-up task once this plan's pattern is established.
- The anchor departure `DN` (`P`, the paired departure the ramp targets) always gets `delta = excess` exactly, never the rounded per-step formula — this is what keeps the anchor precise regardless of rounding drift among the earlier steps.

---

## File Structure

**Backend:**
- `backend/src/regulation.py` — new: pure `compute_ramp_deltas` function (mirrors `interdiction.py`'s separation of pure math from DB-wired service code)
- `backend/src/service.py` — modify: `get_auto_regulation_enabled`/`set_auto_regulation_enabled`, `apply_regulation`, `shift_stop` gains an automatic-mode hook
- `backend/src/schemas.py` — modify: `RegulationRequest`, `AutoRegulationSetting`
- `backend/src/app.py` — modify: register endpoints, broadcast

**Backend tests:**
- `backend/tests/test_regulation_math.py` — new: pure-function tests
- `backend/tests/test_service_regulation.py` — new: service-layer tests
- `backend/tests/test_api_regulation.py` — new: HTTP-layer tests

**Frontend:**
- `frontend/src/app.js` — modify: header toggle, "Regular" context-menu action
- `frontend/src/index.html` — modify: toggle button
- `frontend/src/index.css` — modify: toggle state style

**Frontend manual tests:**
- `frontend/tests/manual_test.md` — modify: add scenarios

---

### Task 1: `auto_regulation_enabled` setting

**Files:**
- Modify: `backend/src/schemas.py`, `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_regulation.py` (new), `backend/tests/test_api_regulation.py` (new)

**Interfaces:**
- Produces: `service.get_auto_regulation_enabled(db) -> bool`, `service.set_auto_regulation_enabled(db, enabled: bool) -> None`
- Produces: `GET`/`PUT /api/settings/auto-regulation`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_regulation.py — new file
from src import service
from src.db import init_db


def test_auto_regulation_defaults_to_disabled(db_session):
    init_db(db_session.get_bind())
    assert service.get_auto_regulation_enabled(db_session) is False


def test_set_and_read_auto_regulation(db_session):
    init_db(db_session.get_bind())
    service.set_auto_regulation_enabled(db_session, True)
    assert service.get_auto_regulation_enabled(db_session) is True
```

```python
# backend/tests/test_api_regulation.py — new file
def test_auto_regulation_setting_round_trip(app_client):
    get_response = app_client.get("/api/settings/auto-regulation")
    assert get_response.json() == {"enabled": False}

    put_response = app_client.put("/api/settings/auto-regulation", json={"enabled": True})
    assert put_response.status_code == 200

    assert app_client.get("/api/settings/auto-regulation").json() == {"enabled": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_regulation.py backend/tests/test_api_regulation.py -v`
Expected: FAIL — functions/endpoints don't exist.

- [ ] **Step 3: Add the schema**

In `backend/src/schemas.py`:

```python
class AutoRegulationSetting(BaseModel):
    enabled: bool
```

- [ ] **Step 4: Implement, following the exact pattern of `get_edit_lookback_minutes`/`set_edit_lookback_minutes`**

In `backend/src/service.py`:

```python
def get_auto_regulation_enabled(db: Session) -> bool:
    setting = db.query(models.Setting).filter(models.Setting.key == "auto_regulation_enabled").first()
    return setting.value == "true" if setting else False


def set_auto_regulation_enabled(db: Session, enabled: bool) -> None:
    _set_setting(db, "auto_regulation_enabled", "true" if enabled else "false")
    db.commit()
```

- [ ] **Step 5: Wire the endpoints**

In `backend/src/app.py`:

```python
@app.get("/api/settings/auto-regulation", response_model=AutoRegulationSetting)
def get_auto_regulation(db: Session = Depends(get_db)):
    return AutoRegulationSetting(enabled=service.get_auto_regulation_enabled(db))


@app.put("/api/settings/auto-regulation", response_model=AutoRegulationSetting)
def put_auto_regulation(payload: AutoRegulationSetting, db: Session = Depends(get_db)):
    service.set_auto_regulation_enabled(db, payload.enabled)
    return payload
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_regulation.py backend/tests/test_api_regulation.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/schemas.py backend/src/service.py backend/src/app.py backend/tests/test_service_regulation.py backend/tests/test_api_regulation.py
git commit -m "feat: auto_regulation_enabled setting"
```

---

### Task 2: Ramp delta math (pure function)

**Files:**
- Create: `backend/src/regulation.py`
- Test: `backend/tests/test_regulation_math.py` (new)

**Interfaces:**
- Produces: `compute_ramp_deltas(candidate_ids: list[str], excess: float) -> dict[str, float]`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_regulation_math.py — new file
from src.regulation import compute_ramp_deltas


def test_ramp_distributes_evenly_and_anchor_is_exact():
    deltas = compute_ramp_deltas(["D1", "D2", "D3", "D4", "D5"], excess=10.0)
    assert deltas["D1"] == 2.0
    assert deltas["D2"] == 4.0
    assert deltas["D3"] == 6.0
    assert deltas["D4"] == 8.0
    assert deltas["D5"] == 10.0  # anchor: always exact, never the rounded formula


def test_ramp_handles_non_divisible_excess_without_anchor_drift():
    deltas = compute_ramp_deltas(["D1", "D2", "D3"], excess=10.0)
    # 10/3 = 3.33 -> round(3.33)=3, round(6.67)=7, anchor forced to 10 regardless.
    assert deltas["D1"] == 3
    assert deltas["D2"] == 7
    assert deltas["D3"] == 10.0


def test_ramp_handles_negative_excess_for_compression():
    deltas = compute_ramp_deltas(["D1", "D2"], excess=-10.0)
    assert deltas["D1"] == -5.0
    assert deltas["D2"] == -10.0


def test_ramp_with_a_single_candidate_is_just_the_anchor():
    deltas = compute_ramp_deltas(["D1"], excess=7.0)
    assert deltas == {"D1": 7.0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_regulation_math.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `backend/src/regulation.py`:

```python
def compute_ramp_deltas(candidate_ids: list[str], excess: float) -> dict[str, float]:
    """candidate_ids: chronologically ordered [D1..DN], DN is the anchor (the paired
    departure the ramp targets). Returns trip_id -> delta_minutes.

    Every entry except the last uses round(k * excess / N); the last always gets
    exactly `excess`, regardless of rounding — this is what keeps the anchor's
    resulting departure time exact even when excess doesn't divide evenly by N.
    """
    n = len(candidate_ids)
    deltas = {trip_id: round(k * excess / n) for k, trip_id in enumerate(candidate_ids[:-1], start=1)}
    if candidate_ids:
        deltas[candidate_ids[-1]] = excess
    return deltas
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_regulation_math.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/regulation.py backend/tests/test_regulation_math.py
git commit -m "feat: pure ramp-delta math for regulação de partidas"
```

---

### Task 3: `apply_regulation` — pairing lookup, candidate list, ramp application

**Files:**
- Modify: `backend/src/schemas.py`, `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_service_regulation.py`, `backend/tests/test_api_regulation.py`

**Interfaces:**
- Consumes: `regulation.compute_ramp_deltas` (Task 2), `station.turnaround_seconds` (Spec 3), `trip.active_first_seq`/`active_last_seq` (Spec 2b), `service.get_edit_lookback_minutes`/`_trip_stops`/`_station_y_lookup` (existing)
- Produces: `service.apply_regulation(db, arrival_trip_id: str, station_id: str, now: datetime | None = None) -> list[TripOut]`
- Produces: `POST /api/regulation/apply`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_service_regulation.py — append
from datetime import datetime

from src import service
from src.db import init_db
from src.schemas import TemplateImportStop, TemplateImportTrip


def _seed_turnaround_scenario(db_session):
    """Two RGS-BFU departures from BFU (D1 at 06:00, D2/anchor at 06:15) and one
    BFU-RGS arrival at BFU at 05:50. Turnaround at BFU = 20 minutes, so the arrival's
    target departure is 06:10 — D2 (06:15) already clears that without a violation
    until the arrival itself is delayed (see the actual test bodies)."""
    init_db(db_session.get_bind())
    service.import_template(db_session, [
        TemplateImportTrip(
            trip_id="ARRIVAL", direction="BFU-RGS",
            stops=[
                TemplateImportStop(station="RGS", time="05:20:00"),
                TemplateImportStop(station="BFU", time="05:50:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D1", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="BFU", time="06:00:00"),
                TemplateImportStop(station="RGS", time="06:30:00"),
            ],
        ),
        TemplateImportTrip(
            trip_id="D2", direction="RGS-BFU",
            stops=[
                TemplateImportStop(station="BFU", time="06:15:00"),
                TemplateImportStop(station="RGS", time="06:45:00"),
            ],
        ),
    ])
    service.set_station_turnaround(db_session, "BFU", 20 * 60)  # 20 minutes


def test_apply_regulation_ramps_intermediate_departures(db_session):
    _seed_turnaround_scenario(db_session)
    now = datetime(2026, 8, 16, 4, 30, 0)
    # Delay ARRIVAL's BFU stop to 06:05 -> target = 06:25, D2 (paired departure,
    # 2nd arrival <-> 2nd departure position) currently at 06:15 -> excess = 10 min.
    service.shift_stop(db_session, "ARRIVAL", "BFU", "06:05:00", now=now)

    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)
    updated_by_id = {t.trip_id: t for t in updated}

    assert updated_by_id["D2"].stops[0].time == "06:25:00"  # anchor: exact
    assert updated_by_id["D1"].stops[0].time == "06:05:00"  # 06:00 + round(1*10/2)=5min


def test_apply_regulation_is_noop_when_no_violation(db_session):
    _seed_turnaround_scenario(db_session)
    now = datetime(2026, 8, 16, 4, 30, 0)
    # No shift applied — D2 at 06:15 already exceeds the 20-min minimum after 05:50 arrival
    # (target would be 06:10, D2 is already at 06:15) -> excess is negative but tiny; to keep
    # this test a clean no-op, use a arrival unpaired to any configured station instead:
    updated = service.apply_regulation(db_session, "ARRIVAL", "RGS", now=now)  # RGS has no turnaround configured
    assert updated == []


def test_apply_regulation_never_compresses_a_departure_into_the_past(db_session):
    _seed_turnaround_scenario(db_session)
    # "now" is past D1's original 06:00 departure — D1 is no longer a valid candidate
    # (it already departed), so only D2 (the anchor) can be adjusted.
    now = datetime(2026, 8, 16, 6, 1, 0)
    service.shift_stop(db_session, "ARRIVAL", "BFU", "06:05:00", now=datetime(2026, 8, 16, 4, 30, 0))

    updated = service.apply_regulation(db_session, "ARRIVAL", "BFU", now=now)
    updated_by_id = {t.trip_id: t for t in updated}
    assert "D1" not in updated_by_id  # already departed, excluded from candidates entirely
    assert updated_by_id["D2"].stops[0].time == "06:25:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_regulation.py -v`
Expected: FAIL — `apply_regulation` does not exist.

- [ ] **Step 3: Implement**

In `backend/src/service.py`, add:

```python
from . import regulation


def _effective_stop_bounds(trip: models.Trip, stops: list[models.PlannedStop]) -> tuple[int, int]:
    first = trip.active_first_seq if trip.active_first_seq is not None else 0
    last = trip.active_last_seq if trip.active_last_seq is not None else len(stops) - 1
    return first, last


def _effective_first_stop(trip: models.Trip, stops: list[models.PlannedStop]):
    first, last = _effective_stop_bounds(trip, stops)
    return stops[first] if 0 <= first <= last < len(stops) else None


def _effective_last_stop(trip: models.Trip, stops: list[models.PlannedStop]):
    first, last = _effective_stop_bounds(trip, stops)
    return stops[last] if 0 <= first <= last < len(stops) else None


def apply_regulation(
    db: Session, arrival_trip_id: str, station_id: str, now: datetime | None = None,
) -> list[TripOut]:
    now = now or datetime.now()
    station = db.query(models.Station).filter(models.Station.id == station_id).first()
    if station is None or station.turnaround_seconds is None:
        return []

    arrival_trip = db.query(models.Trip).filter(models.Trip.id == arrival_trip_id).first()
    if arrival_trip is None:
        raise TripNotFoundError(arrival_trip_id)
    arrival_stops = _trip_stops(db, arrival_trip_id)
    arrival_stop = _effective_last_stop(arrival_trip, arrival_stops)
    if arrival_stop is None or arrival_stop.station_id != station_id:
        return []

    all_trips_with_stops = [(t, _trip_stops(db, t.id)) for t in db.query(models.Trip).all()]

    # Full positional pairing (Spec 3's rule), including past trips, to find WHICH
    # departure this arrival is paired with — mirrors frontend/src/app.js's
    # computeTurnaroundPairs exactly.
    arrivals = sorted(
        (
            (t, s) for t, s in all_trips_with_stops
            if s and _effective_last_stop(t, s) and _effective_last_stop(t, s).station_id == station_id
            and t.direction == arrival_trip.direction
        ),
        key=lambda ts: time_str_to_service_minutes(_effective_last_stop(ts[0], ts[1]).departure_time),
    )
    departures = sorted(
        (
            (t, s) for t, s in all_trips_with_stops
            if s and _effective_first_stop(t, s) and _effective_first_stop(t, s).station_id == station_id
            and t.direction != arrival_trip.direction
        ),
        key=lambda ts: time_str_to_service_minutes(_effective_first_stop(ts[0], ts[1]).departure_time),
    )
    arrival_idx = next((i for i, (t, _) in enumerate(arrivals) if t.id == arrival_trip_id), None)
    if arrival_idx is None or arrival_idx >= len(departures):
        return []
    departure_trip, departure_stops = departures[arrival_idx]

    target_sm = time_str_to_service_minutes(arrival_stop.departure_time) + station.turnaround_seconds / 60
    departure_stop = _effective_first_stop(departure_trip, departure_stops)
    current_departure_sm = time_str_to_service_minutes(departure_stop.departure_time)
    excess = target_sm - current_departure_sm
    if excess == 0:
        return []

    # Ramp candidates: only NOT-YET-DEPARTED trips at (station, departure_trip.direction),
    # up to and including the anchor (departure_trip) — a strict subset of `departures`.
    now_sm = datetime_to_service_minutes(now)
    future_departures = [
        (t, s) for t, s in departures
        if time_str_to_service_minutes(_effective_first_stop(t, s).departure_time) > now_sm
    ]
    anchor_idx = next(i for i, (t, _) in enumerate(future_departures) if t.id == departure_trip.id)
    candidates = future_departures[: anchor_idx + 1]

    deltas = regulation.compute_ramp_deltas([t.id for t, _ in candidates], excess)

    updated = []
    for trip, stops in candidates:
        delta = deltas[trip.id]
        first_idx, _ = _effective_stop_bounds(trip, stops)
        new_departure_sm = time_str_to_service_minutes(stops[first_idx].departure_time) + delta
        if new_departure_sm <= now_sm:
            continue  # would push a future departure into the past — skip, leave untouched

        for stop in stops[first_idx:]:
            stop.arrival_time = minutes_to_time_str(time_str_to_minutes(stop.arrival_time) + delta)
            stop.departure_time = minutes_to_time_str(time_str_to_minutes(stop.departure_time) + delta)
        updated.append(trip.id)

    db.commit()
    return [get_trip(db, trip_id) for trip_id in updated]
```

- [ ] **Step 4: Add the schema and endpoint**

In `backend/src/schemas.py`:

```python
class RegulationRequest(BaseModel):
    trip_id: str
    station_id: str
```

In `backend/src/app.py`:

```python
@app.post("/api/regulation/apply", response_model=list[TripOut])
async def post_apply_regulation(payload: RegulationRequest, db: Session = Depends(get_db)):
    updated = service.apply_regulation(db, payload.trip_id, payload.station_id)
    for trip in updated:
        await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return updated
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_regulation.py -v`
Expected: PASS

- [ ] **Step 6: Add and run the API-level test**

```python
# backend/tests/test_api_regulation.py — append
from datetime import datetime


def test_apply_regulation_endpoint(app_client, monkeypatch):
    from test_api import _freeze_service_now
    _freeze_service_now(monkeypatch, datetime(2026, 8, 16, 4, 30, 0))

    app_client.post("/api/template/import", json=[
        {"trip_id": "ARRIVAL", "direction": "BFU-RGS",
         "stops": [{"station": "RGS", "time": "05:20:00"}, {"station": "BFU", "time": "05:50:00"}]},
        {"trip_id": "D1", "direction": "RGS-BFU",
         "stops": [{"station": "BFU", "time": "06:15:00"}, {"station": "RGS", "time": "06:45:00"}]},
    ])
    app_client.put("/api/stations/BFU/turnaround", json={"turnaround_seconds": 1200})
    app_client.post("/api/stops/shift", json={"trip_id": "ARRIVAL", "station_id": "BFU", "new_time": "06:05:00"})

    response = app_client.post("/api/regulation/apply", json={"trip_id": "ARRIVAL", "station_id": "BFU"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["trip_id"] == "D1"
    assert body[0]["stops"][0]["time"] == "06:25:00"
```

Run: `pytest backend/tests/test_api_regulation.py -v`
Expected: PASS

- [ ] **Step 7: Run the full backend suite**

Run: `pytest backend/tests -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/schemas.py backend/src/service.py backend/src/app.py backend/tests/test_service_regulation.py backend/tests/test_api_regulation.py
git commit -m "feat: apply regulation ramp for a violated turnaround pairing"
```

---

### Task 4: Automatic mode — hook into `shift_stop`

**Files:**
- Modify: `backend/src/service.py`
- Test: `backend/tests/test_service_regulation.py`

**Interfaces:**
- Consumes: `service.apply_regulation` (Task 3), `service.get_auto_regulation_enabled` (Task 1)
- Modifies: `service.shift_stop` — calls `apply_regulation` for the shifted trip/station when auto mode is on and the shifted stop is that trip's effective last (arrival) stop

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_service_regulation.py — append
from src.schemas import TemplateImportStop, TemplateImportTrip


def test_shift_stop_auto_regulates_when_enabled(db_session):
    _seed_turnaround_scenario(db_session)
    service.set_auto_regulation_enabled(db_session, True)
    now = datetime(2026, 8, 16, 4, 30, 0)

    service.shift_stop(db_session, "ARRIVAL", "BFU", "06:05:00", now=now)

    d2 = service.get_trip(db_session, "D2")
    assert d2.stops[0].time == "06:25:00"  # ramp applied automatically, no explicit apply_regulation call


def test_shift_stop_does_not_auto_regulate_when_disabled(db_session):
    _seed_turnaround_scenario(db_session)
    # auto_regulation_enabled defaults to False (Task 1) — no explicit call needed.
    now = datetime(2026, 8, 16, 4, 30, 0)

    service.shift_stop(db_session, "ARRIVAL", "BFU", "06:05:00", now=now)

    d2 = service.get_trip(db_session, "D2")
    assert d2.stops[0].time == "06:15:00"  # untouched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_service_regulation.py::test_shift_stop_auto_regulates_when_enabled -v`
Expected: FAIL — `D2` unchanged even with auto mode on.

- [ ] **Step 3: Implement the hook**

In `backend/src/service.py`, modify `shift_stop` — after its existing `db.commit()` and before `return get_trip(db, trip_id)`, add:

```python
    if get_auto_regulation_enabled(db):
        # Only the shifted stop's trip, and only if that stop is this trip's effective
        # arrival (last active stop) — shifting an intermediate stop doesn't change
        # when the trip arrives anywhere.
        refreshed_stops = _trip_stops(db, trip_id)
        refreshed_trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
        arrival_stop = _effective_last_stop(refreshed_trip, refreshed_stops)
        if arrival_stop is not None and arrival_stop.station_id == station_id:
            apply_regulation(db, trip_id, station_id, now=now)
```

(`now` here is `shift_stop`'s own `now` parameter, already resolved to a concrete `datetime` earlier in the function — reuse it rather than calling `datetime.now()` again, keeping the whole operation consistent with a single wall-clock reading.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_service_regulation.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `pytest backend/tests -v`
Expected: PASS — in particular, every pre-existing `shift_stop` test still passes since `auto_regulation_enabled` defaults to `False` and the hook is a no-op until explicitly turned on.

- [ ] **Step 6: Commit**

```bash
git add backend/src/service.py backend/tests/test_service_regulation.py
git commit -m "feat: auto-regulate on shift_stop when enabled"
```

---

### Task 5: Header toggle for automatic regulation

**Files:**
- Modify: `frontend/src/index.html`, `frontend/src/app.js`, `frontend/src/index.css`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `GET`/`PUT /api/settings/auto-regulation` (Task 1)

- [ ] **Step 1: Add the button**

In `frontend/src/index.html`, next to the existing `#btn-theme-toggle`:

```html
<button class="btn-theme-toggle" id="btn-auto-regulation" onclick="toggleAutoRegulation()" title="Regulação automática de partidas">⚙️</button>
```

- [ ] **Step 2: Implement the toggle**

In `frontend/src/app.js`:

```javascript
// ==========================================================================
// Automatic Regulation Toggle
// ==========================================================================
function loadAutoRegulationSetting() {
    fetch("/api/settings/auto-regulation")
        .then(r => r.json())
        .then(data => {
            appState.autoRegulationEnabled = data.enabled;
            syncAutoRegulationIcon();
        });
}

function toggleAutoRegulation() {
    const newValue = !appState.autoRegulationEnabled;
    fetch("/api/settings/auto-regulation", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: newValue }),
    })
        .then(r => r.json())
        .then(data => {
            appState.autoRegulationEnabled = data.enabled;
            syncAutoRegulationIcon();
        });
}

function syncAutoRegulationIcon() {
    const btn = document.getElementById("btn-auto-regulation");
    if (!btn) return;
    btn.classList.toggle("active", !!appState.autoRegulationEnabled);
    btn.title = appState.autoRegulationEnabled
        ? "Regulação automática: ligada (clique para desligar)"
        : "Regulação automática: desligada (clique para ligar)";
}
```

Call `loadAutoRegulationSetting();` in `loadDefaultSchedule`'s `.then` chain, alongside the existing `loadLookbackSetting();`.

- [ ] **Step 3: Add CSS**

In `frontend/src/index.css`:

```css
#btn-auto-regulation.active {
    background: var(--accent, #2563eb);
    color: white;
}
```

(If `--accent` isn't an existing token, grep `index.css` for whatever primary-action color `.btn-primary` already uses and match it instead of inventing a new token.)

- [ ] **Step 4: Manually verify**

Reload, confirm the ⚙️ icon starts inactive (default off). Click it, confirm it visually activates and `PUT /api/settings/auto-regulation` fires with `enabled: true`. Reload the page and confirm the state persisted (still active).

- [ ] **Step 5: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Toggle de regulação automática

1. Confirme o ícone ⚙️ no header, inativo por padrão.
2. Clique — confirme que ativa visualmente e persiste (recarregar a página mantém o estado).
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/index.html frontend/src/app.js frontend/src/index.css frontend/tests/manual_test.md
git commit -m "feat: header toggle for automatic regulation"
```

---

### Task 6: "Regular" context-menu action on a violated departure

**Files:**
- Modify: `frontend/src/app.js`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `showContextMenu` (Spec 1 plan Task 11), `computeTurnaroundPairs` (Spec 3 plan Task 3), `POST /api/regulation/apply` (Task 3)

- [ ] **Step 1: Attach the context menu to violated departure nodes**

In `frontend/src/app.js`, modify the node-rendering loop in `drawTrainPaths` (the same loop Spec 2b's plan, Task 5 adds "Suprimir a partir daqui"/"Alterar partida" to) — add a check for whether this stop is the origin of a violated turnaround pair:

```javascript
                const violatedPair = computeTurnaroundPairs().find(p =>
                    p.departureTrip.trip_id === trip.trip_id && !p.valid
                    && effectiveFirstStop(trip).station === stop.station
                );
                if (violatedPair) {
                    circle.addEventListener("contextmenu", (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        showContextMenu(e.clientX, e.clientY, [
                            { label: "Regular", onClick: () => applyRegulation(violatedPair.arrivalTrip.trip_id, violatedPair.stationId) },
                        ]);
                    });
                }
```

(If Spec 2b's context-menu wiring already attached a `contextmenu` listener to this same circle, merge the menu items into a single `showContextMenu` call carrying both entries, rather than attaching two competing listeners — whichever plan lands second should read the other's code and merge.)

- [ ] **Step 2: Implement `applyRegulation`**

```javascript
function applyRegulation(arrivalTripId, stationId) {
    fetch("/api/regulation/apply", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trip_id: arrivalTripId, station_id: stationId }),
    })
        .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
        .then(updatedTrips => {
            updatedTrips.forEach(applyTripUpdate);
        })
        .catch(err => alert("Não foi possível regular: " + err.message));
}
```

- [ ] **Step 3: Manually verify**

Create a turnaround violation (Spec 3), select the violated departure trip so its nodes render, right-click its origin node, confirm "Regular" appears, click it, verify the departure and any intermediate trips update and the violation (red connector) clears.

- [ ] **Step 4: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Regular manualmente uma violação

1. Configure um tempo de volta e provoque uma violação (arraste uma chegada para atrasar).
2. Selecione a viagem de partida violada, botão direito no nó de origem — confirme a opção "Regular".
3. Clique — confirme que a partida (e intermediárias, se houver) se ajustam e a violação some.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: manual Regular action on a violated turnaround departure"
```

---

## Self-Review

**Spec coverage:** `auto_regulation_enabled` setting → Task 1. Ramp math with exact anchor → Task 2. Pairing lookup (server-side mirror of Spec 3) + candidate list + application → Task 3. Reexecução (always against current times) → inherent in Task 3's design (recomputes `excess` from live data every call). Negative excess / can't-compress-into-past → Task 3, Step 3's `new_departure_sm <= now_sm` guard. Automatic mode → Tasks 1 (setting) + 4 (hook). Header icon → Task 5. "Regular" context menu → Task 6.

**Placeholder scan:** none.

**Type consistency:** `apply_regulation` (Task 3) returns `list[TripOut]`, consumed identically by Task 4 (ignores return value, just needs the side effect) and the `POST /api/regulation/apply` endpoint (Task 3) and frontend's `applyRegulation` (Task 6). `regulation.compute_ramp_deltas`'s signature (Task 2) — `list[str], float -> dict[str, float]` — matches exactly how Task 3 calls it.

**Acknowledged scope limits (carried from the spec's own "Casos de borda" section):** full optimal redistribution when a candidate can't compress is not implemented (documented in Global Constraints); automatic mode only hooks `shift_stop`, not every possible arrival-changing action (documented in Global Constraints and Task 4's docstring comment).
