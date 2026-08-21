# Interdição: Retenção em S_prev + Cascata de Headway — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the Spec 2a (Interdições) delay-application algorithm to hold a train at a real station platform (`S_prev`) instead of distorting a segment's speed or shifting a whole trip from its own origin, and add a new, unconditional "Gatilho de Cascata por Interdição" to Spec 4 (Regulação de Partidas) that flatly propagates the same delta to later same-direction departures so fleet headway is never eaten by a single hold.

**Architecture:** `service.py::_apply_interdiction` currently shifts a held trip's entire stop list uniformly from its own origin, and separately cascades that same delta to every same-direction trip whose *own origin* departs later — both superseded. The corrected version identifies `S_prev` (the real stop immediately before the interdicted segment) per held trip, snapshots and shifts only from `S_prev.departure_time` onward (leaving `S_prev.arrival_time` and everything before it untouched), and cascades the same flat delta to other same-direction trips keyed on their *own* passage through that same station — not their own origin. The frontend goes back to drawing a flat wait segment, but anchored on `S_prev`'s real station grid line instead of the interdiction rectangle's border, which requires exposing `arrival_time` on `StopOut` (currently only `departure_time` is exposed, aliased as `time`).

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), vanilla JS/SVG (frontend). Backend tests via pytest.

**Spec:**
- `docs/superpowers/specs/2026-08-16-interdicoes-design.md` (Passo 2, Desenho — amended 2026-08-20)
- `docs/superpowers/specs/2026-08-16-regulacao-de-partidas-design.md` (Gatilho de Cascata por Interdição — added 2026-08-20)

## Global Constraints

- The cascade trigger is **unconditional** — it runs regardless of the `auto_regulation_enabled` setting. It is a distinct operation from `apply_regulation` (the tapering ramp used by the Spec 4 toggle / manual "Regular" action); never call `apply_regulation` from the interdiction cascade.
- Stops strictly before `S_prev` never change for any trip (held or cascaded).
- `S_prev.arrival_time` never changes — only `S_prev.departure_time` and every stop after it (both `arrival_time` and `departure_time`) receive `+delta`.
- All existing interdiction/regulation tests that are not explicitly rewritten by this plan must keep passing (`pytest backend/tests -q`).

---

### Task 1: Expose `arrival_time` on `StopOut`

**Files:**
- Modify: `backend/src/schemas.py` (`StopOut`, line 9-12)
- Modify: `backend/src/service.py` (`_trip_to_out`, line 216-237)
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Produces: `StopOut.arrival_time: str` — every `TripOut.stops[i]` now carries both `time` (departure, unchanged existing field) and `arrival_time`. For every stop that hasn't been held by an interdiction, the two are identical (this codebase has never modeled non-zero dwell before now).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_db.py` currently starts with exactly these two lines and nothing else:

```python
from src.db import init_db
from src.models import Setting, Station, Schedule, TemplateTrip
```

Change them to:

```python
from datetime import datetime

from src import service
from src.db import init_db
from src.models import Setting, Station, Schedule, TemplateTrip
from src.schemas import TemplateImportStop, TemplateImportTrip
```

Then append this test to the end of the file:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_db.py::test_get_trip_exposes_arrival_time_per_stop -v`
Expected: FAIL with `AttributeError: 'StopOut' object has no attribute 'arrival_time'`

- [ ] **Step 3: Add the field to `StopOut`**

In `backend/src/schemas.py`, change:

```python
class StopOut(BaseModel):
    station: str
    time: str
    y_coord: float
```

to:

```python
class StopOut(BaseModel):
    station: str
    time: str
    arrival_time: str
    y_coord: float
```

- [ ] **Step 4: Populate it in `_trip_to_out`**

In `backend/src/service.py`, change the `StopOut(...)` construction inside `_trip_to_out` (around line 228-234) from:

```python
            StopOut(
                station=s.station_id,
                time=s.departure_time,
                # 0.0 only if a stop references a station missing from the table (SQLite
                # does not enforce the FK); the stop still renders rather than NaN-ing out.
                y_coord=station_y.get(s.station_id, 0.0),
            )
```

to:

```python
            StopOut(
                station=s.station_id,
                time=s.departure_time,
                arrival_time=s.arrival_time,
                # 0.0 only if a stop references a station missing from the table (SQLite
                # does not enforce the FK); the stop still renders rather than NaN-ing out.
                y_coord=station_y.get(s.station_id, 0.0),
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_db.py::test_get_trip_exposes_arrival_time_per_stop -v`
Expected: PASS

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: All tests pass (adding a field is purely additive — nothing should break).

- [ ] **Step 7: Commit**

```bash
git add backend/src/schemas.py backend/src/service.py backend/tests/test_db.py
git commit -m "feat: expose arrival_time per stop in TripOut"
```

---

### Task 2: Hold the train at S_prev instead of shifting the whole trip

**Files:**
- Modify: `backend/src/service.py` (`_apply_interdiction`, currently line 821+)
- Test: `backend/tests/test_service_interdictions.py`

**Interfaces:**
- Consumes: `interdiction_geometry.crossing_window` (unchanged — still returns `(entry_sm, exit_sm, first_idx)` where `first_idx` is the index of the first stop *after* the crossing; `S_prev` is `stops[first_idx - 1]`), `interdiction_geometry.sequence_crossings` (unchanged).
- Produces: `_apply_delta_from_station(trip_id, stops, station_idx, delta)` — a new private helper in `service.py`, shared by this task and Task 3, that snapshots and shifts a trip from a given stop index onward (arrival untouched at that index, both fields shifted after it).

This task removes the "whole trip from its own origin" shift entirely. Task 3 (next) adds the cascade back using a corrected, station-anchored scope — do not skip straight to Task 3's fixture; this task's tests must pass first with cascading intentionally absent.

- [ ] **Step 1: Replace the delayed-trip test with S_prev semantics**

In `backend/tests/test_service_interdictions.py`, delete `test_create_interdiction_shifts_the_whole_delayed_trip_uniformly` (lines 147-166) and replace it with:

```python
def test_create_interdiction_holds_the_train_at_s_prev_only(db_session):
    _seed_two_opposite_trips(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    affected = {a.trip_id: a for a in result.affected_trips}["TRIP_RGS-BFU_050500"]
    delta = time_str_to_minutes(affected.entry_time) - time_str_to_minutes(affected.original_entry_time)
    assert delta > 0  # sanity: this trip was actually held

    # TRIP_RGS-BFU_050500 is RGS(05:00) -> SAN(05:10) -> BFU(05:30); the interdiction band
    # (y 3500-5000) sits on the SAN->BFU segment, so S_prev is SAN.
    trip = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    by_station = {s.station: s for s in trip.stops}

    # Before S_prev: untouched.
    assert by_station["RGS"].time == "05:00:00"

    # S_prev itself: arrival stays original (the train is on time getting there); only the
    # departure (when it's allowed to leave the platform) receives the delta.
    assert by_station["SAN"].arrival_time == "05:10:00"
    assert time_str_to_minutes(by_station["SAN"].time) - time_str_to_minutes("05:10:00") == pytest.approx(delta, abs=2 / 60)

    # After S_prev: both arrival and departure shift by the same delta, preserving speed.
    assert time_str_to_minutes(by_station["BFU"].arrival_time) - time_str_to_minutes("05:30:00") == pytest.approx(delta, abs=2 / 60)
    assert time_str_to_minutes(by_station["BFU"].time) - time_str_to_minutes("05:30:00") == pytest.approx(delta, abs=2 / 60)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_service_interdictions.py::test_create_interdiction_holds_the_train_at_s_prev_only -v`
Expected: FAIL — `RGS` will already have shifted under the current "whole trip from origin" code (`by_station["RGS"].time == "05:00:00"` fails).

- [ ] **Step 3: Read the current `_apply_interdiction` in full**

Open `backend/src/service.py` and read from `def _apply_interdiction` (around line 821) through its `return affected` (around line 913) before editing — the diff below assumes you're replacing the block starting at the `# Fleet regularity:` comment through the end of the function.

- [ ] **Step 4: Replace the delta-application block**

Replace everything from the `# Fleet regularity:` comment (around line 848) through the end of the function (the final `return affected`, around line 913) with:

```python
    all_trips_with_stops = [(t, _trip_stops(db, t.id)) for t in db.query(models.Trip).all()]
    direction_by_trip = {t.id: t.direction for t, _ in all_trips_with_stops}
    original_departure_by_key: dict[tuple[str, str], str] = {
        (t.id, s.station_id): s.departure_time
        for t, stops in all_trips_with_stops for s in stops
    }
    stop_index_by_trip_station: dict[tuple[str, str], int] = {
        (t.id, s.station_id): idx
        for t, stops in all_trips_with_stops for idx, s in enumerate(stops)
    }
    stops_by_trip = {t.id: stops for t, stops in all_trips_with_stops}

    def apply_delta_from_station(trip_id: str, stops: list[models.PlannedStop], station_idx: int, delta: float) -> None:
        # A held train can't wait mid-track -- it waits at S_prev's platform. S_prev's own
        # arrival stays original (it got there on time); only its departure and everything
        # downstream (both arrival and departure) shift, keeping every segment's speed
        # constant everywhere. Same rule for a cascade recipient, anchored at its own stop
        # matching the held train's S_prev station.
        for offset, stop in enumerate(stops[station_idx:]):
            existing = db.get(models.InterdictionStopSnapshot, (interdiction.id, trip_id, stop.station_id))
            if existing is None:
                db.add(models.InterdictionStopSnapshot(
                    interdiction_id=interdiction.id, trip_id=trip_id, station_id=stop.station_id,
                    arrival_time=stop.arrival_time, departure_time=stop.departure_time,
                ))
            if offset == 0:
                stop.departure_time = minutes_to_time_str(time_str_to_minutes(stop.departure_time) + delta)
            else:
                stop.arrival_time = minutes_to_time_str(time_str_to_minutes(stop.arrival_time) + delta)
                stop.departure_time = minutes_to_time_str(time_str_to_minutes(stop.departure_time) + delta)

    affected = []
    delayed_trip_ids: list[str] = []
    for trip_id, delta, new_entry_sm, new_exit_sm in sequenced:
        _, _, original_entry_sm, _, first_idx, stops = by_trip_id[trip_id]
        if delta:
            s_prev_idx = first_idx - 1
            apply_delta_from_station(trip_id, stops, s_prev_idx, delta)
            delayed_trip_ids.append(trip_id)
        affected.append(InterdictionAffectedTrip(
            trip_id=trip_id,
            entry_time=_service_minutes_to_time_str(new_entry_sm),
            exit_time=_service_minutes_to_time_str(new_exit_sm),
            original_entry_time=_service_minutes_to_time_str(original_entry_sm),
        ))

    db.commit()

    # A held train's delay can push its own terminus arrival past a configured
    # turnaround's minimum -- ramp the paired departure the same way shift_stop does.
    for trip_id in delayed_trip_ids:
        _maybe_auto_regulate(db, trip_id, now)

    return affected
```

This intentionally drops the old same-direction cascade (Task 3 reintroduces it, station-anchored). `stops_by_trip`, `original_departure_by_key`, and `stop_index_by_trip_station` are computed here so Task 3 can insert its cascade loop between `apply_delta_from_station(trip_id, stops, s_prev_idx, delta)` and `delayed_trip_ids.append(trip_id)` without re-deriving them.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_service_interdictions.py::test_create_interdiction_holds_the_train_at_s_prev_only -v`
Expected: PASS

- [ ] **Step 6: Run the full interdiction test file**

Run: `cd backend && python -m pytest tests/test_service_interdictions.py -v`
Expected: `test_create_interdiction_cascades_delay_to_later_same_direction_departures` now FAILS (its old origin-anchored cascade assertions no longer hold — expected, Task 3 rewrites it). All other tests in the file should still PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/service.py backend/tests/test_service_interdictions.py
git commit -m "fix: hold interdicted trains at S_prev instead of shifting the whole trip"
```

---

### Task 3: Station-anchored headway cascade (Gatilho de Cascata por Interdição)

**Files:**
- Modify: `backend/src/service.py` (`_apply_interdiction`)
- Test: `backend/tests/test_service_interdictions.py`

**Interfaces:**
- Consumes: `apply_delta_from_station`, `direction_by_trip`, `original_departure_by_key`, `stop_index_by_trip_station`, `all_trips_with_stops` — all produced by Task 2, already in scope inside `_apply_interdiction`.

- [ ] **Step 1: Replace the cascade test with station-anchored semantics**

In `backend/tests/test_service_interdictions.py`, replace `test_create_interdiction_cascades_delay_to_later_same_direction_departures` (currently around line 97-124) with:

```python
def test_create_interdiction_cascades_delay_to_later_same_direction_departures(db_session):
    _seed_two_opposite_trips_plus_later_departures(db_session)
    result = service.create_interdiction(
        db_session, y_top=3500.0, y_bottom=5000.0,
        start_time="05:00:00", end_time="06:00:00", description="Obra",
        now=datetime(2026, 8, 16, 4, 30, 0),
    )
    affected_by_trip = {a.trip_id: a for a in result.affected_trips}
    held = affected_by_trip["TRIP_RGS-BFU_050500"]
    delta = time_str_to_minutes(held.entry_time) - time_str_to_minutes(held.original_entry_time)
    assert delta > 0  # sanity: this trip was actually held

    # TRIP_RGS-BFU_050500's S_prev is SAN (see test_create_interdiction_holds_the_train_at_s_prev_only).
    # TRIP_RGS-BFU_060000 (RGS 06:00 -> SAN 06:10 -> BFU 06:30) passes through SAN later than
    # the held trip's *original* SAN departure (05:10) -- it must cascade by the same delta,
    # anchored at ITS OWN SAN stop (its own RGS departure stays untouched).
    later_same_direction = service.get_trip(db_session, "TRIP_RGS-BFU_060000")
    by_station = {s.station: s for s in later_same_direction.stops}
    assert by_station["RGS"].time == "06:00:00"  # before its own S_prev-equivalent: untouched
    assert by_station["SAN"].arrival_time == "06:10:00"
    assert time_str_to_minutes(by_station["SAN"].time) - time_str_to_minutes("06:10:00") == pytest.approx(delta, abs=2 / 60)
    assert time_str_to_minutes(by_station["BFU"].time) - time_str_to_minutes("06:30:00") == pytest.approx(delta, abs=2 / 60)

    # Headway at SAN (the shared station) between the two departures is preserved exactly.
    held_trip = service.get_trip(db_session, "TRIP_RGS-BFU_050500")
    held_new_san_departure = next(s.time for s in held_trip.stops if s.station == "SAN")
    original_headway = time_str_to_minutes("06:10:00") - time_str_to_minutes("05:10:00")
    new_headway = time_str_to_minutes(by_station["SAN"].time) - time_str_to_minutes(held_new_san_departure)
    assert new_headway == pytest.approx(original_headway, abs=2 / 60)

    # Opposite direction, later departure: must NOT cascade -- headway preservation is
    # per-direction (a same-track opposite-direction train has no shared headway to keep).
    opposite_later = service.get_trip(db_session, "TRIP_BFU-RGS_070000")
    assert opposite_later.stops[0].time == "07:00:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_service_interdictions.py::test_create_interdiction_cascades_delay_to_later_same_direction_departures -v`
Expected: FAIL — `TRIP_RGS-BFU_060000` doesn't shift at all yet (cascade was removed in Task 2, not yet reintroduced).

- [ ] **Step 3: Add the cascade loop**

In `backend/src/service.py`, inside the `for trip_id, delta, new_entry_sm, new_exit_sm in sequenced:` loop from Task 2, change:

```python
        if delta:
            s_prev_idx = first_idx - 1
            apply_delta_from_station(trip_id, stops, s_prev_idx, delta)
            delayed_trip_ids.append(trip_id)
```

to:

```python
        if delta:
            s_prev_idx = first_idx - 1
            s_prev_station = stops[s_prev_idx].station_id
            held_original_departure_sm = time_str_to_service_minutes(original_departure_by_key[(trip_id, s_prev_station)])

            apply_delta_from_station(trip_id, stops, s_prev_idx, delta)
            delayed_trip_ids.append(trip_id)

            # Gatilho de Cascata por Interdição (Spec 4): the same flat delta propagates to
            # every later same-direction departure through S_prev, so the headway planned
            # between consecutive departures at that station is never eaten by this hold.
            # Unconditional -- does not check auto_regulation_enabled, and does not call
            # apply_regulation (that's the separate, tapering ramp for the Spec 4 toggle).
            held_direction = direction_by_trip[trip_id]
            for other_id, other_stops in all_trips_with_stops:
                if other_id == trip_id or direction_by_trip.get(other_id) != held_direction:
                    continue
                other_idx = stop_index_by_trip_station.get((other_id, s_prev_station))
                if other_idx is None:
                    continue
                other_original_departure_sm = time_str_to_service_minutes(
                    original_departure_by_key[(other_id, s_prev_station)]
                )
                if other_original_departure_sm > held_original_departure_sm:
                    apply_delta_from_station(other_id, other_stops, other_idx, delta)
                    if other_id not in delayed_trip_ids:
                        delayed_trip_ids.append(other_id)
```

`stops_by_trip` (produced in Task 2) is no longer read anywhere in this function after this change — remove that line too if your editor flags it as unused; it's fine to leave it if you'd rather not touch an unrelated line, but the cleaner diff removes it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_service_interdictions.py::test_create_interdiction_cascades_delay_to_later_same_direction_departures -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: All tests pass. Pay particular attention to `test_interdiction_delay_triggers_auto_regulation_when_enabled` and `test_interdiction_delay_does_not_auto_regulate_when_disabled` (lines 301-388) — these exercise a *different* trip (`D1`, paired via turnaround, not a same-direction cascade recipient) and must be unaffected by this change. If either fails, re-read `_maybe_auto_regulate` (line 326) and confirm you didn't change what it's called with.

- [ ] **Step 6: Commit**

```bash
git add backend/src/service.py backend/tests/test_service_interdictions.py
git commit -m "feat: cascade interdiction hold delta to later same-direction departures at S_prev"
```

---

### Task 4: Frontend — wait segment at S_prev's own station line

**Files:**
- Modify: `frontend/src/app.js` (`drawTrainPaths`, currently around line 1577-1660)

**Interfaces:**
- Consumes: `StopOut.arrival_time` (Task 1) via `trip.stops[i].arrival_time`; `trip.stops[i].y_coord` / `trip.stops[i].time` (existing, unchanged).

This task is JS-only; there's no automated frontend test harness in this repo (see `CLAUDE.md`) — verify manually per Step 4 below, and update `frontend/tests/manual_test.md` per Step 5.

- [ ] **Step 1: Read the current rendering block**

Open `frontend/src/app.js` and read `drawTrainPaths` from its `const activeStops = ...` line (around 1598) through the comment `// An interdiction delay is a pure time shift...` (around 1600-1604) — you're replacing that comment and the `splitTripAtNow` call's surrounding context with logic that inserts a wait vertex before splitting past/future.

- [ ] **Step 2: Insert the wait vertex before the past/future split**

Replace:

```javascript
        const activeStops = (first <= last && first >= 0) ? trip.stops.slice(first, last + 1) : [];
        const activeTrip = { ...trip, stops: activeStops };
        // An interdiction delay is a pure time shift applied to every stop of the trip (see
        // service.py:_apply_interdiction) -- the trip's own speed never changes anywhere, so
        // its polyline needs no special-casing here: it already renders correctly, crossing
        // an opposing train's line exactly at the interdiction border rather than inside it.
        let { pastPoints, futurePoints } = splitTripAtNow(activeTrip, appState.selectedLine);
```

with:

```javascript
        const activeStops = (first <= last && first >= 0) ? trip.stops.slice(first, last + 1) : [];
        // A held stop's arrival_time differs from its departure_time (the train waited on
        // the platform between them) -- insert that stop twice, once at arrival_time and
        // once at departure_time, so the polyline draws a flat wait on the station's own
        // grid line instead of jumping straight from arrival to the (later) departure.
        // Untouched stops always have arrival_time === time (this app never modeled dwell
        // before interdiction holds), so this is a no-op duplicate-free pass-through for them.
        const stopsWithWait = [];
        activeStops.forEach(stop => {
            if (stop.arrival_time && stop.arrival_time !== stop.time) {
                stopsWithWait.push({ ...stop, time: stop.arrival_time });
            }
            stopsWithWait.push(stop);
        });
        const activeTrip = { ...trip, stops: stopsWithWait };
        let { pastPoints, futurePoints } = splitTripAtNow(activeTrip, appState.selectedLine);
```

`splitTripAtNow` (unchanged) already builds each point from `stop.time` via `timeToX`/`getStopY`, so the duplicated arrival-time entry naturally lands at the same Y (same station) and an earlier X (the original, unheld time), producing the flat segment for free — no changes needed to `splitTripAtNow` or the polyline-building code below it.

- [ ] **Step 3: Confirm no other code reads `activeStops` after this point**

Search the rest of `drawTrainPaths` (`grep -n "activeStops" frontend/src/app.js`) — it should only appear in the block you just edited. If another reference exists lower in the function, it needs to read `stopsWithWait` instead (or `activeStops` if it specifically wants the undoubled list) — check before assuming.

- [ ] **Step 4: Manually verify in the browser**

1. From the project root (the directory containing `backend/` and `frontend/`, i.e. `Grafico/Grafico/` in this checkout — the module path below is relative to it, do NOT `cd backend` first), start the server: `python -m uvicorn backend.src.app:app --host 127.0.0.1 --port 8000 --reload`. If a server is already running on port 8000, kill every `python`/`pythonw` process first and start fresh — `--reload` in this environment has repeatedly failed to pick up multi-file changes (confirmed earlier in this project's history); never trust it to already be serving your edits.
2. Open `http://localhost:8000/`.
3. Create an interdiction (right-click on the chart → "🚧 Interditar via", drag, confirm) over a segment where you can see two opposite-direction trains scheduled close together.
4. Confirm the held train's line: normal diagonal to `S_prev`, a **flat horizontal segment exactly on `S_prev`'s station grid line**, then a normal diagonal onward — crossing the red rectangle at cruise speed, touching only its borders.
5. Confirm a later same-direction train (per the cascade) also shows its own flat wait at *its own* passage through the same station, with headway preserved.
6. Open the browser console and confirm no errors.

- [ ] **Step 5: Update the manual test scenario**

In `frontend/tests/manual_test.md`, find the "Deslocamento de viagem retida pela interdição" section (added in the prior session) and replace steps 2-3 (which describe the whole-trip-from-origin behavior) with:

```markdown
2. Confirme que o trem retido é desenhado como: diagonal normal até `S_prev` (a última estação real antes da faixa), um segmento **reto e horizontal exatamente sobre a linha de grade de `S_prev`** (de `arrival_time` original até o novo `departure_time`), depois diagonal normal — com a mesma inclinação (velocidade) do resto da viagem — até a próxima parada. Nada de cotovelo na borda do retângulo vermelho.
3. Selecione o trem retido e confirme que paradas **antes** de `S_prev` (incluindo a origem) não mudaram; só `S_prev.departure_time` em diante.
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: draw the interdiction wait as a flat segment on S_prev's station line"
```

---

### Task 5: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: All tests pass, zero failures, zero errors.

- [ ] **Step 2: Restart the dev server manually**

`uvicorn --reload` has been unreliable at picking up multi-file changes in this environment (confirmed earlier in this project's history). Kill every running `python`/`pythonw` process first, then start fresh from the project root (the directory containing `backend/` and `frontend/`, i.e. `Grafico/Grafico/` in this checkout — do NOT `cd backend`):

```bash
python -m uvicorn backend.src.app:app --host 127.0.0.1 --port 8000 --reload
```

- [ ] **Step 3: Confirm the OpenAPI schema reflects the changes**

```bash
curl -s http://localhost:8000/openapi.json | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('StopOut fields:', list(d['components']['schemas']['StopOut']['properties'].keys()))
"
```
Expected: `['station', 'time', 'arrival_time', 'y_coord']`

- [ ] **Step 4: Re-run the full manual browser check from Task 4 Step 4**

Confirm end to end: create an interdiction, confirm the flat wait renders on `S_prev`'s own grid line for the held train and for a cascaded same-direction train, confirm headway is preserved, confirm no console errors.

---

## Self-Review

**Spec coverage:**
- Passo 2 (S_prev identification, arrival untouched, departure + downstream shifted, stops before S_prev untouched) → Task 2.
- "Gatilho de Cascata por Interdição" (same direction, same station, later original departure, flat delta, unconditional, separate from `apply_regulation`) → Task 3.
- Desenho (flat wait on `S_prev`'s station line, no border vertices) → Task 4.

**Placeholder scan:** No TBDs; every step has concrete code or an exact shell command.

**Type consistency:** `apply_delta_from_station(trip_id: str, stops: list[models.PlannedStop], station_idx: int, delta: float) -> None` is defined once in Task 2 and reused as-is (same name, same signature) in Task 3 — no renaming across tasks.
