# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A time-distance (Marey) chart for CPTM railway Line 710 (São Paulo) train schedules. A Python CLI parses train schedule geometry out of an AutoCAD DXF drawing into JSON; a static vanilla-JS/SVG frontend renders the planned schedule as an interactive chart where dispatchers can drag station-time nodes and see the delay propagate downstream.

There is no build system or frontend toolchain, but there *is* a server: a FastAPI backend with pip dependencies (`backend/requirements.txt`) that owns the schedule state in SQLite and serves the frontend. Two pieces:

- `backend/` — a FastAPI + SQLAlchemy app (REST + WebSocket API over SQLite), plus a standard-library-only DXF parser script
- `frontend/` — a single static HTML/CSS/JS page (no framework, no modules), served by the backend at `http://localhost:8000/`

## Commands

Run all commands from the `grafico/` project root (this directory).

```bash
# Install backend dependencies
pip install -r backend/requirements.txt

# Run the FastAPI backend server (frontend is served at http://localhost:8000/)
uvicorn backend.src.app:app --reload

# Parse the DXF drawing into backend/data/schedule.json
python3 backend/src/parser.py

# Run parser unit tests only
python3 -m unittest backend/tests/test_parser.py -v

# Run all backend tests (includes parser tests)
pytest backend/tests -v
```

The frontend is now served by the backend at `http://localhost:8000/` when the server runs; there is no standalone static-file serving needed.

Manual frontend test scenarios (no automated UI tests exist) are in `frontend/tests/manual_test.md`.

## Architecture

**The FastAPI backend (`backend/src/app.py`) is now the server-authoritative source of truth,** managing a SQLite database (`backend/data/railway.db`) with a template/live schedule split. The frontend fetches and posts through the REST+WebSocket API and receives live updates via WebSocket broadcasts. The data flow is:

```
L10 DOM.dxf --(backend/src/parser.py)--> backend/data/schedule.json --(app initialization)--> backend/data/railway.db
  ^                                                                                              |
  |---- (DXF re-import via API) <----  (POST /api/template/import) <---- frontend
                                                                       /ws <--
                                             (WebSocket broadcast)  broadcast
```

**Backend structure:**
- **`app.py`**: FastAPI application with REST endpoints (`GET /api/schedule`, `POST /api/stops/shift`, `POST /api/template/import`, `POST /api/trips/{trip_id}/reset`, settings endpoints) and WebSocket endpoint `/ws` for live sync
- **`service.py`**: All business logic including `shift_stop()`, which computes the delta from the dragged stop's current stored `departure_time` (in the live `planned_stops` table), then applies that delta to all downstream stops — this server-authoritative computation fixes the original client-side drag bug
- **`models.py` / `db.py`**: SQLAlchemy ORM models and database initialization; `database.py` no longer exists (superseded by `db.py` + `service.py`)
- **`scheduler.py`**: Daily 03:00 reset (server-local time) that resets `trips` and `planned_stops` from their `template_*` counterparts, with startup catch-up for server restarts
- **`ws_manager.py`**: WebSocket connection manager handling broadcasts to all connected clients

**Data model:**
- `template_trips` and `template_planned_stops`: Immutable baseline imported from the DXF drawing via parser
- `trips` and `planned_stops`: Today's live editable copy, reset from template daily at 03:00 server-local time and updated via REST API
- When a stop is dragged, the server (`service.py:shift_stop()`) computes delta from the dragged stop's current stored `departure_time` (not from a client-supplied delta or template baseline), then applies that same delta to all downstream stops in the same trip — this server-authoritative approach ensures consistent propagation across all connected clients

**Frontend changes:**
- Now fetches schedule state from the backend API on load
- Posts all edits (node drags) via REST to the backend
- Receives live updates from other dispatchers via WebSocket broadcast

- **DXF → JSON (`backend/src/parser.py`)**: Streams the DXF as text, watching for group codes `0` (entity type), `8` (layer), `10`/`20` (vertex X/Y). Only entities on layers `BFU-RGS` or `RGS-BFU` are kept as trips. X coordinates encode time (`coord_to_time`: 20 DXF units = 1 minute); Y coordinates encode station via nearest-match against a hardcoded `y_coordinate → station code` table (`get_station_code`, 50-unit snap tolerance). One row of stations (`stations_row1`) is Line 10, the other (`stations_row2`) is Line 7; they share the "Luz" station at different Y values, disambiguated downstream as `LUZ` vs `LUZ_L7`.
- **Frontend (`frontend/src/app.js`)**: A single file, no framework, no modules. `appState.trips` holds the live schedule fetched from the server; `appState.dragNode` holds per-gesture transient state including `dragStartStops` (a deep clone of the trip's stops at the moment drag started, used only for the local live-drag preview). All chart geometry is generated by hand-building SVG DOM nodes (no charting library) — see `timeToX`/`xToTime` and `dxfYToSvg` for the coordinate mappings between clock time / DXF Y and SVG pixels. The `stations` object in `app.js` duplicates the station table from `parser.py`/`db.py` — if station Y-coordinates or line groupings change, all three places need updating together.
- **Node drag + propagation**: Client-side, `onNodeDragStart`/`onNodeDrag`/`onNodeDragEnd` implement the core interaction. `onNodeDragStart` deep-clones the trip's stops into `dragStartStops` (transient per-gesture reference), which drives the live-drag SVG preview. `onNodeDragEnd` POSTs the dragged stop's new time to `POST /api/stops/shift` (no delta supplied; just the target stop id and new time). The backend's `service.py:shift_stop()` computes the delta from the stop's current stored `departure_time`, applies it to all downstream stops, and returns the updated trip. The server response is rendered via `applyTripUpdate` and broadcast to all connected clients via WebSocket. "Resetar" resets today's live schedule to the template baseline by calling `POST /api/trips/{trip_id}/reset`.
- **Realized/actual data**: Currently only a hardcoded `mockRealizedData` array toggled via the "Mostrar Realizado" button — there is no live tracking ingestion (this matches spec.md FR-008, explicitly out of scope for this version).

## Repo layout quirk

This CLAUDE.md lives at `Grafico/grafico/` — note the nested `Grafico/` (capital, git root) → `grafico/` (lowercase, actual project) path. `L10 DOM.dxf`, the source drawing, lives one level up at `Grafico/L10 DOM.dxf`; `parser.py` looks for it there first and falls back to `backend/data/L10 DOM.dxf`.

## Spec-kit artifacts

`specs/001-railway-traffic-chart/` holds the original spec/plan/data-model/quickstart docs (GitHub spec-kit format) for the sole feature in this repo. `data-model.md` documents an intended SQLite schema; treat it as design intent, not as a description of what the frontend currently reads/writes (see Architecture above). `.specify/memory/constitution.md` is an unfilled template — ignore it.
