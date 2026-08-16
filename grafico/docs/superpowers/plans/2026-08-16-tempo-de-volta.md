# Tempo de Volta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a dispatcher configure a minimum turnaround time per station and have the chart automatically pair each arrival with the opposite-direction departure it becomes (same physical train), drawing a connector between them and flagging any pair whose gap is below the configured minimum — pure display/validation, no automatic schedule changes.

**Architecture:** One nullable column on `stations` (`turnaround_seconds`), served through `GET /api/schedule`'s existing payload as a `station_turnarounds` map — no new backend algorithm at all. The pairing itself is a pure frontend function: for each configured station and each incoming direction, sort that station's arrivals and opposite-direction departures chronologically and pair them positionally (1st with 1st, 2nd with 2nd, ...), exactly mirroring the FCFS approach Spec 2a's backend already uses, just client-side and non-mutating. "Arrival"/"departure" always mean each trip's **effective** first/last stop — `active_first_seq`/`active_last_seq` from Spec 2b when set, otherwise the literal first/last stop.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend, minimal), vanilla JS/SVG (frontend, most of the work). Backend tests via pytest; frontend verified manually.

**Spec:** `docs/superpowers/specs/2026-08-16-tempo-de-volta-design.md`

## Global Constraints

- No new backend algorithm and no persisted pairing — every connected client computes the same pairing independently from the same synced `trips` + `station_turnarounds` state, matching the spec's explicit design choice.
- "Arrival"/"departure" for a trip always resolve through its effective window: `trip.stops[trip.active_first_seq ?? 0]` for departure, `trip.stops[trip.active_last_seq ?? trip.stops.length - 1]` for arrival (Spec 2b fields — already present on every `TripOut` returned by the backend once Spec 2b ships; if Spec 2b hasn't shipped yet, both fields are simply always `null`/absent and the helpers fall back to the literal first/last stop, so this task has no hard ordering dependency on Spec 2b's implementation, only on its *data shape* already existing in `schemas.TripOut`, which Spec 2b's Task 1 adds).
- This spec never mutates a stop's time and never blocks any existing action — a violation is purely a visual flag.

---

## File Structure

**Backend:**
- `backend/src/models.py` — modify: add `Station.turnaround_seconds`
- `backend/src/db.py` — modify: migrate existing `stations` table
- `backend/src/schemas.py` — modify: add `TurnaroundSetting`; `ScheduleOut` gains `station_turnarounds`
- `backend/src/service.py` — modify: `set_station_turnaround`, `get_live_schedule` populates the new field
- `backend/src/app.py` — modify: register the endpoint, broadcast

**Backend tests:**
- `backend/tests/test_db.py` — modify: migration assertion
- `backend/tests/test_service_turnaround.py` — new
- `backend/tests/test_api_turnaround.py` — new

**Frontend:**
- `frontend/src/app.js` — modify: config dialog on station-line click, pairing algorithm, connector rendering, violation styling, hover-chain highlight

**Frontend manual tests:**
- `frontend/tests/manual_test.md` — modify: add scenarios

---

### Task 1: `turnaround_seconds` column, endpoint, and `ScheduleOut` field

**Files:**
- Modify: `backend/src/models.py`, `backend/src/db.py`, `backend/src/schemas.py`, `backend/src/service.py`, `backend/src/app.py`
- Test: `backend/tests/test_db.py`, `backend/tests/test_service_turnaround.py` (new), `backend/tests/test_api_turnaround.py` (new)

**Interfaces:**
- Produces: `models.Station.turnaround_seconds: int | None`
- Produces: `service.set_station_turnaround(db, station_id: str, turnaround_seconds: int | None) -> None`
- Modifies: `service.get_live_schedule` — `ScheduleOut.station_turnarounds: dict[str, int]`
- Produces: `PUT /api/stations/{station_id}/turnaround`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_db.py — append
def test_init_db_adds_turnaround_seconds_to_stations_table(db_session):
    from src.db import init_db
    from sqlalchemy import text

    bind = db_session.get_bind()
    init_db(bind)
    cols = {row[1] for row in db_session.execute(text("PRAGMA table_info(stations)"))}
    assert "turnaround_seconds" in cols
    init_db(bind)  # idempotent
```

```python
# backend/tests/test_service_turnaround.py — new file
import pytest

from src import service
from src.db import init_db
from src.errors import StationNotFoundError


def test_set_and_read_station_turnaround(db_session):
    init_db(db_session.get_bind())
    service.set_station_turnaround(db_session, "RGS", 600)

    schedule = service.get_live_schedule(db_session)
    assert schedule.station_turnarounds == {"RGS": 600}


def test_clearing_turnaround_removes_it_from_the_map(db_session):
    init_db(db_session.get_bind())
    service.set_station_turnaround(db_session, "RGS", 600)
    service.set_station_turnaround(db_session, "RGS", None)

    schedule = service.get_live_schedule(db_session)
    assert schedule.station_turnarounds == {}


def test_set_turnaround_on_unknown_station_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(StationNotFoundError):
        service.set_station_turnaround(db_session, "NOT_A_STATION", 600)
```

```python
# backend/tests/test_api_turnaround.py — new file
def test_put_turnaround_round_trip(app_client):
    response = app_client.put("/api/stations/RGS/turnaround", json={"turnaround_seconds": 600})
    assert response.status_code == 200
    assert response.json() == {"turnaround_seconds": 600}

    schedule = app_client.get("/api/schedule").json()
    assert schedule["station_turnarounds"] == {"RGS": 600}


def test_put_turnaround_unknown_station_returns_404(app_client):
    response = app_client.put("/api/stations/NOT_A_STATION/turnaround", json={"turnaround_seconds": 600})
    assert response.status_code == 404


def test_put_turnaround_negative_seconds_returns_422(app_client):
    response = app_client.put("/api/stations/RGS/turnaround", json={"turnaround_seconds": -5})
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_db.py backend/tests/test_service_turnaround.py backend/tests/test_api_turnaround.py -v`
Expected: FAIL — column/function/endpoint don't exist.

- [ ] **Step 3: Add the column to the model**

In `backend/src/models.py`, modify `Station`:

```python
class Station(Base):
    __tablename__ = "stations"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    y_coordinate = Column(Float, nullable=False)
    line = Column(String, nullable=False)
    turnaround_seconds = Column(Integer, nullable=True)
```

- [ ] **Step 4: Add the migration**

In `backend/src/db.py`, inside `init_db`, add (alongside any other guarded `ALTER TABLE` blocks already present from Spec 1/2b's plans):

```python
        existing_cols = {row[1] for row in db.execute(text("PRAGMA table_info(stations)"))}
        if "turnaround_seconds" not in existing_cols:
            db.execute(text("ALTER TABLE stations ADD COLUMN turnaround_seconds INTEGER"))
        db.commit()
```

- [ ] **Step 5: Add the schema**

In `backend/src/schemas.py`:

```python
class TurnaroundSetting(BaseModel):
    turnaround_seconds: Optional[int] = Field(default=None, ge=0)
```

Add `station_turnarounds: dict[str, int] = {}` as a field on the existing `ScheduleOut` class.

- [ ] **Step 6: Implement the service function and update `get_live_schedule`**

In `backend/src/service.py`:

```python
def set_station_turnaround(db: Session, station_id: str, turnaround_seconds: int | None) -> None:
    station = db.query(models.Station).filter(models.Station.id == station_id).first()
    if station is None:
        raise StationNotFoundError(station_id)
    station.turnaround_seconds = turnaround_seconds
    db.commit()
```

Modify `get_live_schedule`:

```python
def get_live_schedule(db: Session) -> ScheduleOut:
    station_y = _station_y_lookup(db)
    trips_out = []
    for trip in db.query(models.Trip).all():
        stops = _trip_stops(db, trip.id)
        if not stops:
            continue
        trips_out.append(_trip_to_out(trip, stops, station_y))

    turnarounds = {
        s.id: s.turnaround_seconds
        for s in db.query(models.Station).filter(models.Station.turnaround_seconds.isnot(None)).all()
    }
    return ScheduleOut(trips=trips_out, station_turnarounds=turnarounds)
```

(If Spec 2a's plan already added `interdictions=...` to this same `return ScheduleOut(...)` call, merge both kwargs into the one call rather than overwriting.)

- [ ] **Step 7: Wire the endpoint**

In `backend/src/app.py`:

```python
@app.put("/api/stations/{station_id}/turnaround", response_model=TurnaroundSetting)
async def put_station_turnaround(station_id: str, payload: TurnaroundSetting, db: Session = Depends(get_db)):
    service.set_station_turnaround(db, station_id, payload.turnaround_seconds)
    await manager.broadcast({"type": "schedule_reset"})
    return payload
```

(Reuses the existing `StationNotFoundError` → 404 handler already registered for `shift_stop`; its message text says "not found on trip", which is slightly imprecise for this context but not worth a second error class for one word of wording — add `TurnaroundSetting` to `app.py`'s schema imports.)

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest backend/tests/test_db.py backend/tests/test_service_turnaround.py backend/tests/test_api_turnaround.py -v`
Expected: PASS

- [ ] **Step 9: Run the full backend suite**

Run: `pytest backend/tests -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/src/models.py backend/src/db.py backend/src/schemas.py backend/src/service.py backend/src/app.py backend/tests/test_db.py backend/tests/test_service_turnaround.py backend/tests/test_api_turnaround.py
git commit -m "feat: per-station minimum turnaround setting"
```

---

### Task 2: Configure turnaround via station-line click

**Files:**
- Modify: `frontend/src/app.js`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `showDialog` (Spec 1 plan Task 10), `PUT /api/stations/{station_id}/turnaround` (Task 1)

- [ ] **Step 1: Attach a click listener to each station line**

In `frontend/src/app.js`, modify `drawGrid`'s station-line loop:

```javascript
        line.className.baseVal = "station-grid-line";
        line.addEventListener("click", () => openTurnaroundDialog(station));
        svg.appendChild(line);
```

- [ ] **Step 2: Implement the dialog**

```javascript
// ==========================================================================
// Turnaround (Tempo de Volta)
// ==========================================================================
function formatTurnaroundSeconds(seconds) {
    if (seconds == null) return "";
    const mm = Math.floor(seconds / 60);
    const ss = seconds % 60;
    return `${mm}:${String(ss).padStart(2, '0')}`;
}

// Accepts "MM:SS" or a bare integer of seconds.
function parseTurnaroundInput(value) {
    if (!value) return null;
    if (value.includes(":")) {
        const [mm, ss] = value.split(":").map(Number);
        return mm * 60 + ss;
    }
    return parseInt(value, 10);
}

function openTurnaroundDialog(station) {
    const current = (appState.stationTurnarounds || {})[station.id];
    showDialog({
        title: `Tempo de volta em ${station.name}`,
        fields: [{ name: "turnaround", label: "Tempo (MM:SS ou segundos)", value: formatTurnaroundSeconds(current) }],
        confirmLabel: "Salvar",
        onConfirm: (values) => {
            const seconds = parseTurnaroundInput(values.turnaround);
            fetch(`/api/stations/${encodeURIComponent(station.id)}/turnaround`, {
                method: "PUT", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ turnaround_seconds: seconds }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return reloadScheduleFromServer(); })
                .catch(err => alert("Não foi possível salvar: " + err.message));
        },
    });
}
```

`showDialog` (Spec 1) has no built-in "Remover" button — leaving the field empty and confirming already clears it (`parseTurnaroundInput("")` returns `null`, sent as `turnaround_seconds: null`), which satisfies the spec's "Remover" behavior without a third button.

- [ ] **Step 3: Load `station_turnarounds` into `appState`**

In `frontend/src/app.js`, wherever `appState.trips`/`appState.interdictions` are assigned from a schedule payload (`loadDefaultSchedule`, `reloadScheduleFromServer`), also assign `appState.stationTurnarounds = data.station_turnarounds || {};`.

- [ ] **Step 4: Manually verify**

Click a station's horizontal grid line, confirm the dialog opens with the station's name, enter "10:00", confirm, verify (Network tab) the PUT succeeds and the schedule reloads. Click the same line again, confirm the field now shows "10:00" pre-filled. Clear it and confirm — verify the turnaround is removed.

- [ ] **Step 5: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Configurar tempo de volta

1. Clique na linha horizontal de uma estação no gráfico — confirme o diálogo "Tempo de volta em [estação]".
2. Digite "10:00", confirme — reabra e confirme que o valor persiste.
3. Limpe o campo, confirme — reabra e confirme que está vazio (removido).
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: configure station turnaround via station-line click"
```

---

### Task 3: Pairing algorithm and connector rendering (with violation styling)

**Files:**
- Modify: `frontend/src/app.js`, `frontend/src/index.css`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `appState.stationTurnarounds` (Task 2), `trip.active_first_seq`/`active_last_seq` (Spec 2b)
- Produces: `computeTurnaroundPairs()`, `effectiveFirstStop(trip)`, `effectiveLastStop(trip)`

- [ ] **Step 1: Implement the effective-stop helpers and pairing function**

In `frontend/src/app.js`:

```javascript
function effectiveFirstStop(trip) {
    const idx = trip.active_first_seq != null ? trip.active_first_seq : 0;
    return trip.stops[idx];
}

function effectiveLastStop(trip) {
    const idx = trip.active_last_seq != null ? trip.active_last_seq : trip.stops.length - 1;
    return trip.stops[idx];
}

// Returns a flat array of { stationId, arrivalTrip, departureTrip, arrivalTime, departureTime, valid }.
// Positional FCFS pairing per (station, incoming direction) — mirrors the backend's
// interdiction queueing approach (Spec 2a), but purely as a read, never mutating anything.
function computeTurnaroundPairs() {
    const stationTurnarounds = appState.stationTurnarounds || {};
    const pairs = [];

    Object.keys(stationTurnarounds).forEach(stationId => {
        const turnaroundSeconds = stationTurnarounds[stationId];
        const directions = [...new Set(appState.trips.map(t => t.direction))];

        directions.forEach(dIn => {
            const arrivals = appState.trips
                .filter(t => effectiveLastStop(t).station === stationId && t.direction === dIn)
                .sort((a, b) => timeStrToServiceMinutes(effectiveLastStop(a).time) - timeStrToServiceMinutes(effectiveLastStop(b).time));
            const departures = appState.trips
                .filter(t => effectiveFirstStop(t).station === stationId && t.direction !== dIn)
                .sort((a, b) => timeStrToServiceMinutes(effectiveFirstStop(a).time) - timeStrToServiceMinutes(effectiveFirstStop(b).time));

            const n = Math.min(arrivals.length, departures.length);
            for (let i = 0; i < n; i++) {
                const arrivalTrip = arrivals[i], departureTrip = departures[i];
                const arrivalTime = effectiveLastStop(arrivalTrip).time;
                const departureTime = effectiveFirstStop(departureTrip).time;
                const gapSeconds = (timeStrToServiceMinutes(departureTime) - timeStrToServiceMinutes(arrivalTime)) * 60;
                pairs.push({
                    stationId, arrivalTrip, departureTrip, arrivalTime, departureTime,
                    valid: gapSeconds >= turnaroundSeconds,
                });
            }
        });
    });

    return pairs;
}
```

- [ ] **Step 2: Render connectors**

In `frontend/src/app.js`, add a rendering function called from `renderChart()` right after `drawInterdictions(svg)` (Spec 2a) or, if Spec 2a isn't implemented yet, right after `drawTrainPaths(svg)`:

```javascript
function drawTurnaroundConnectors(svg) {
    computeTurnaroundPairs().forEach(pair => {
        const station = stations[appState.selectedLine].find(s => s.id === pair.stationId);
        if (!station) return;  // pair's station isn't on the currently displayed line

        const x1 = timeToX(pair.arrivalTime);
        const x2 = timeToX(pair.departureTime);
        const y = dxfYToSvg(station.y_dxf, appState.selectedLine);

        const line = document.createElementNS(SVG_NS, "line");
        line.setAttribute("x1", x1);
        line.setAttribute("y1", y);
        line.setAttribute("x2", x2);
        line.setAttribute("y2", y);
        line.className.baseVal = pair.valid ? "turnaround-connector" : "turnaround-connector violation";
        svg.appendChild(line);
    });
}
```

Call `drawTurnaroundConnectors(svg);` in `renderChart()`.

- [ ] **Step 3: Add CSS**

In `frontend/src/index.css`:

```css
.turnaround-connector {
    stroke: var(--text-secondary, #999);
    stroke-width: 3;
    opacity: 0.5;
}
.turnaround-connector.violation {
    stroke: #dc2626;
    opacity: 0.9;
}
```

- [ ] **Step 4: Manually verify**

Configure a turnaround at a station with at least one arrival/departure pair. Confirm a connector line renders along the station's grid line spanning arrival→departure. Shrink the gap (drag the departure node earlier) below the configured minimum and confirm the connector turns red/violation-styled without blocking the drag.

- [ ] **Step 5: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Pareamento e conector de tempo de volta

1. Configure um tempo de volta numa estação com ao menos uma chegada e uma partida de sentido oposto.
2. Confirme o conector horizontal ligando chegada e partida na linha da estação.
3. Arraste a partida pra antes do mínimo — confirme que o conector fica vermelho, sem bloquear o arraste.
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app.js frontend/src/index.css frontend/tests/manual_test.md
git commit -m "feat: turnaround pairing algorithm and connector rendering"
```

---

### Task 4: Hover chain

**Files:**
- Modify: `frontend/src/app.js`
- Test: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `computeTurnaroundPairs` (Task 3)

- [ ] **Step 1: Build the chain-lookup map and highlight logic**

In `frontend/src/app.js`:

```javascript
function computeTurnaroundNextTripMap() {
    const nextTripId = {};
    computeTurnaroundPairs().forEach(pair => {
        nextTripId[pair.arrivalTrip.trip_id] = pair.departureTrip.trip_id;
    });
    return nextTripId;
}

function highlightTurnaroundChain(startTripId) {
    const nextTripId = computeTurnaroundNextTripMap();
    let currentId = startTripId;
    let hop = 0;
    const maxHops = 20;  // defensive cap; a real chain terminates naturally when no pair is found

    while (currentId && hop <= maxHops) {
        const opacity = Math.max(0.15, 1 - hop * 0.25);
        [`line-${currentId}-past`, `line-${currentId}-future`].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.opacity = opacity;
        });
        currentId = nextTripId[currentId];
        hop++;
    }
}

function clearTurnaroundChainHighlight() {
    document.querySelectorAll(".train-path-planned, .train-path-past").forEach(el => {
        el.style.opacity = "";
    });
}
```

- [ ] **Step 2: Wire `mouseenter`/`mouseleave` on trip lines**

In `frontend/src/app.js`'s `drawTrainPaths`, inside `attachTripLineEvents`, add:

```javascript
        polyline.addEventListener("mouseenter", () => highlightTurnaroundChain(trip.trip_id));
        polyline.addEventListener("mouseleave", () => clearTurnaroundChainHighlight());
```

(Additive to the existing `mouseover`/`mousemove`/`mouseout`/`click` listeners already attached there — `mouseenter`/`mouseleave` don't bubble the way `mouseover`/`mouseout` do, so they coexist safely without interfering with the existing tooltip logic.)

- [ ] **Step 3: Manually verify**

With at least two chained turnaround pairs configured (trip A arrives and pairs with departure B, which itself later arrives and pairs with departure C), hover over trip A's line. Confirm A renders at full opacity, B at reduced opacity, C at further-reduced opacity, and everything else unaffected. Move the mouse away and confirm all lines return to normal.

- [ ] **Step 4: Add manual test scenario**

Append to `frontend/tests/manual_test.md`:

```markdown
## Cadeia de rotação ao passar o mouse

1. Configure tempos de volta que encadeiem ao menos 3 viagens (A -> B -> C).
2. Passe o mouse sobre a viagem A — confirme A em ênfase total, B mais discreta, C ainda mais discreta.
3. Tire o mouse — confirme que tudo volta ao normal.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: hover highlights a trip's future turnaround chain"
```

---

## Self-Review

**Spec coverage:** `turnaround_seconds` column + endpoint + `ScheduleOut` field → Task 1. Config dialog on station-line click → Task 2. Positional FCFS pairing, connector rendering, violation styling → Task 3. Hover chain with distance-based opacity → Task 4.

**Placeholder scan:** none.

**Type consistency:** `effectiveFirstStop`/`effectiveLastStop` (Task 3) are the single source of truth for "arrival"/"departure" used consistently by both the pairing function and (via `computeTurnaroundNextTripMap`) the hover chain in Task 4 — no duplicate logic drifting apart. `appState.stationTurnarounds` name matches between Task 2 (setter) and Task 3 (reader).

**Explicit non-dependency on Spec 2a's rendering order:** Task 3, Step 2 calls out that `drawTurnaroundConnectors` can be inserted after either `drawInterdictions` (if Spec 2a shipped first) or `drawTrainPaths` (if not) — this plan does not assume implementation order relative to Spec 2a.
