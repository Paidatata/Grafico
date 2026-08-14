# Real-Time Schedule Backend — Design

**Date**: 2026-08-13
**Status**: Approved for implementation

## Problem

The current frontend (`frontend/src/app.js`) is 100% client-side: it loads `schedule.json` (or a hardcoded fallback) into memory, lets a dispatcher drag station-time nodes on the Marey chart, and computes the downstream time propagation independently in each browser tab. Nothing is ever persisted — `backend/data/railway.db` exists but nothing reads or writes to it; "Exportar Grade" only downloads a JSON snapshot.

Two concrete problems reported:
1. When dragging a node, the downstream stops shift, but not by a pattern that matches the dragged node — because propagation math is duplicated client-side with its own float rounding, so nothing guarantees the dragged node and its downstream neighbors end up consistent.
2. There is no persistence: edits vanish on reload and are invisible to other dispatchers. The product needs to become a real multi-user, real-time, database-backed tool ("produto para venda com alto valor agregado").

## Goals (this phase)

- One authoritative backend (FastAPI + Uvicorn) computes and persists all schedule edits to SQLite — eliminates the propagation-drift bug by construction (single computation, not duplicated per-browser).
- Multiple dispatchers on different machines see each other's edits live via WebSocket push.
- A daily reset at 03:00 restores the working schedule from an immutable "template" (the DXF-parsed baseline), so each day starts clean.
- A configurable "lookback window" limits how far into the past a node can still be edited.

## Non-goals (deferred to later phases)

- Authentication / user accounts / access control.
- Ingesting real "realized" (actual train position) events from an external system (planned for later, polling every 60s — schema stays compatible, ingestion not built now).
- Per-edit audit log (`who changed what, when`) — deferred until user accounts exist, since there's no "who" to record yet.
- Deployment/hosting, horizontal scaling, moving off SQLite to Postgres (the design keeps this cheap to do later via SQLAlchemy, but doesn't do it now).

## Architecture

```
DXF file --(existing parser.py)--> schedule.json --(POST /api/template/import)--> template_* tables
                                                                                        |
                                                                          (daily 03:00 reset copies)
                                                                                        v
Dispatcher browser <--WebSocket (live push)--  FastAPI + Uvicorn  <-->  trips / planned_stops (SQLite)
       |                                              ^
       +---- POST /api/stops/shift (drag a node) -----+
```

The frontend remains a static page (no new frontend framework), but now talks to the backend for reads/writes instead of managing its own copy of the schedule as the source of truth.

## Data model (SQLite via SQLAlchemy)

- **`stations`** — unchanged from the existing `specs/001-railway-traffic-chart/data-model.md` (id, name, y_coordinate, line).
- **`template_trips` / `template_planned_stops`** — the immutable "gráfico padrão." Populated via `POST /api/template/import` (uploads a `schedule.json` produced by `backend/src/parser.py`). Only changes on deliberate re-import; dispatcher edits never touch it.
- **`trips` / `planned_stops`** — today's live, editable schedule. Every dispatcher edit writes here. Reset from the template tables every day at 03:00.
- **`realized_events`** — unchanged from the existing data model; stays unused until a future external tracking integration starts writing to it (out of scope this phase).
- **`settings`** — key-value table for runtime-configurable policy. This phase only needs `edit_lookback_minutes` and `last_reset_date` (the latter lets the reset job catch up if the server was down at 03:00, without double-resetting if restarted later the same day).

No `edit_log` table this phase (explicitly deferred — decided during design review).

## API

REST (JSON) + one WebSocket:

- `GET /api/schedule` — today's live trips + stops. Replaces the current `fetch("../data/schedule.json")` / hardcoded fallback.
- `POST /api/template/import` — upload a `schedule.json`; replaces the template tables. Replaces today's "Importar JSON" button semantics (now seeds the baseline, not just browser memory).
- `POST /api/stops/shift` — body `{trip_id, station_id, new_time}`. Server computes `delta = new_time - current_stored_time`, applies that same delta to every downstream stop (`sequence_order` greater, same trip) in one DB transaction, persists, returns the fully updated trip, and broadcasts it over the WebSocket. This is the fix for the propagation-drift bug: one computation, and every client (including the one that dragged) re-renders from this authoritative response.
- `POST /api/trips/{trip_id}/reset` — reverts one trip to its template values. Replaces the current global "Resetar" button (scoped per-trip since a global reset is too blunt with multiple dispatchers editing concurrently).
- `GET/PUT /api/settings/edit-lookback-minutes` — read/write the configurable lookback value.
- `WS /ws` — dispatcher browsers hold this open. Server pushes `{type: "trip_updated", trip}` after every shift/reset, and `{type: "schedule_reset"}` after the daily 03:00 reset.

### Validation on `POST /api/stops/shift`

Reject with 400 if:
- the trip or station doesn't exist (404 instead, for clarity),
- `new_time` isn't parseable,
- the new time would fall before the immediately upstream stop's departure time (breaks chronological order),
- the stop being dragged is older than `now - edit_lookback_minutes` (the retroactive-edit guard).

## Daily reset (03:00)

Runs in-process via APScheduler (`AsyncIOScheduler`, cron trigger `03:00` server-local time) — no OS-level cron dependency. On trigger, in one transaction: delete all rows from `trips`/`planned_stops` and `realized_events`, reinsert `trips`/`planned_stops` from the template tables, update `settings.last_reset_date`, then broadcast `{type: "schedule_reset"}`.

Startup catch-up: on process start, compare `settings.last_reset_date` to today; if the server was down through 03:00 (date is stale), run the reset immediately instead of waiting for the next 03:00. This avoids both "missed reset because the server was off" and "double reset because it restarted after 03:00 the same day."

## Frontend changes (`frontend/src/app.js`)

- `loadDefaultSchedule()` → `fetch("/api/schedule")` instead of the static file / `fallbackSchedule`. Fallback mock data is removed as a silent behavior — a real multi-dispatcher tool should show a clear "can't reach server" state instead of quietly rendering stale mock data.
- Open a WebSocket to `/ws` on load. On `trip_updated`, replace that trip in `appState.trips` and re-render — unless it's the trip the local user is currently mid-drag on, to avoid fighting their gesture. On `schedule_reset`, refetch `/api/schedule` and re-render everything, with a visible notice.
- `onNodeDragEnd`: POST the final `{trip_id, station_id, new_time}` to `/api/stops/shift`. On success, replace the trip with the server's response (this is what removes the drift). On 400/404, revert the visual drag to its pre-drag position and surface the rejection reason in the tooltip.
- On load, `GET /api/settings/edit-lookback-minutes` once; nodes older than the cutoff render non-draggable (dimmed, `cursor: not-allowed`, no drag listeners attached).
- "Importar JSON" now calls `POST /api/template/import`.
- "Exportar Grade" is unchanged (client-side snapshot download, no backend involvement).
- "Resetar" now calls `POST /api/trips/{id}/reset` for the selected trip. The client-side `originalTrips` backup concept is removed — the server is the source of truth.
- Mocked "Mostrar Realizado" data stays mocked this phase (real ingestion is future work).

## Error handling

- Backend returns structured JSON errors (`{"detail": "..."}`, FastAPI default) with distinct status codes (404 unknown trip/station, 400 validation failures).
- WebSocket: client auto-reconnects with exponential backoff; on every reconnect, it refetches `/api/schedule` once to resync in case any broadcast was missed while disconnected.
- SQLite handles this write volume (schedule edits, not high-frequency transactions) fine with a single-writer/serialized-transaction pattern — no need for row-level locking infrastructure this phase.

## Testing

- Backend: `pytest` + FastAPI's `TestClient`. Cover shift propagation (the previously-duplicated logic now has exactly one implementation to test), lookback rejection, upstream-order rejection, template import, and daily reset (call the reset function directly with a mocked "now" rather than waiting for a real 03:00).
- `backend/tests/test_parser.py` (DXF parsing) is untouched — unrelated to this change.
- `frontend/tests/manual_test.md` gets new scenarios: multi-tab live sync, a lookback-blocked node, and the "server unreachable" state.

## Open items carried forward (not blocking this phase)

- Auth/accounts — needed before an `edit_log` makes sense.
- Real realized-event ingestion (60s poll from an external system).
- Postgres migration, if/when SQLite's single-writer model becomes a bottleneck.
