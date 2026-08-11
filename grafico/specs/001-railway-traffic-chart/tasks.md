# Tasks: Railway Traffic Chart (Gráfico de Horário de Circulação Ferroviária)

**Input**: Design documents from `specs/001-railway-traffic-chart/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Exact file paths are included in descriptions.

## Path Conventions

- **Web app**: `backend/src/`, `frontend/src/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic folder structure setup.

- [x] T001 Create project folder structure (`backend/src/`, `backend/data/`, `frontend/src/`) per implementation plan
- [x] T002 Initialize the project files (empty files `backend/src/__init__.py`, `frontend/src/index.html`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core database seeder and schema mapping that must be complete before any user story.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T003 Setup database schema SQLite creation queries in `backend/src/database.py` per data-model.md
- [x] T004 Create a mock seeder script in `backend/src/seed.py` that populates basic station table records in the database

**Checkpoint**: Foundation ready - user story implementation can now begin.

---

## Phase 3: User Story 1 - Visualizing the planned vs realized train graph (Priority: P1) 🎯 MVP

**Goal**: View a time-distance graph in the browser with stations on the Y-axis and times (00:00 to 24:00) on the X-axis, showing train lines based on the database data.

**Independent Test**: Load the frontend HTML page, select a mock schedule JSON file, and verify that the SVG graph renders correctly styled grid lines and train paths.

### Implementation for User Story 1

- [x] T005 [P] [US1] Design HTML page structure with SVG container and file upload inputs in `frontend/src/index.html`
- [x] T006 [P] [US1] Implement premium dark-mode styling, grid styling, and train line styles in `frontend/src/index.css`
- [x] T007 [US1] Implement SVG grid rendering logic (Y-axis stations, X-axis hours/minutes grid lines) in `frontend/src/app.js`
- [x] T008 [US1] Implement SVG polyline rendering logic to draw train schedules as lines in `frontend/src/app.js`

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently.

---

## Phase 4: User Story 2 - Interactive editing and time propagation of planned schedules (Priority: P1)

**Goal**: Click and drag station stop nodes on the SVG graph to edit planned times, propagating changes to downstream stops.

**Independent Test**: Drag a node for a train at an intermediate station, verify that downstream nodes move accordingly, and that the modified times are saved.

### Implementation for User Story 2

- [x] T009 [US2] Implement click and drag mouse-event listeners on SVG node circles in `frontend/src/app.js`
- [x] T010 [US2] Implement coordinate-to-time transformation functions (X-coord to HH:MM:SS) in `frontend/src/app.js` per research.md
- [x] T011 [US2] Implement time propagation logic (recalculating downstream stops) in `frontend/src/app.js`
- [x] T012 [US2] Implement save handler (exporting modified JSON or sending updates to backend) in `frontend/src/app.js`

**Checkpoint**: At this point, User Stories 1 and 2 should both work independently.

---

## Phase 5: User Story 4 - Importing planned schedule from DXF (Priority: P2)

**Goal**: Run a CLI tool to convert AutoCAD DXF schedule into a JSON file, and upload it via the web interface.

**Independent Test**: Run the CLI script on `L10 DOM.dxf` and upload the resulting JSON file, verifying the chart renders the correct number of trains.

### Implementation for User Story 4

- [x] T013 [P] [US4] Implement DXF line-by-line entity parser for LWPOLYLINE and MTEXT in `backend/src/parser.py`
- [x] T014 [US4] Implement chronological sorting and start/end time calculations in `backend/src/parser.py`
- [x] T015 [US4] Implement file upload upload-handling logic in `frontend/src/app.js` to parse the exported JSON and render the graph

**Checkpoint**: User Story 4 should be functional, allowing DXF import to build the base planned timetables.

---

## Phase 6: User Story 3 - Displaying actual tracking data (Priority: P2)

**Goal**: Display actual train tracking data written to the database by external processes as solid lines on the SVG graph.

**Independent Test**: Load mock tracking data from the database and verify that solid lines are plotted on the SVG chart matching the actual event times.

### Implementation for User Story 3

- [x] T016 [US3] Add database table mapping for realized train events in `backend/src/database.py`
- [x] T017 [US3] Implement SVG polyline rendering for actual (solid) train lines in `frontend/src/app.js`
- [x] T018 [US3] Create a mock script to populate realized train events in `backend/src/mock_realized.py`

**Checkpoint**: All user stories should now be independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories.

- [x] T019 [P] Write unit tests for DXF coordinate conversion functions in `backend/tests/test_parser.py`
- [x] T020 [P] Document system operation and quickstart validation execution in `frontend/tests/manual_test.md`
- [x] T021 Run quickstart.md validation scenarios to verify end-to-end integration

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories.
- **User Stories (Phase 3+)**: All depend on Foundational phase completion.
  - User Story 4 (DXF parser) should be run first to generate the planned schedule file.
  - User Story 1 (Visualization) consumes this file.
  - User Story 2 (Editing/propagation) extends User Story 1.
  - User Story 3 (Actual tracking) adds overlay lines on top of the graph.
- **Polish (Phase 7)**: Depends on all desired user stories being complete.

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel.
- Front-end layout styling (`T005`, `T006`) can be developed in parallel with backend database work (`T003`, `T004`).
- Once Foundation is complete, the DXF parser CLI backend (`T013`, `T014`) can be developed in parallel with the SVG grid renderer frontend (`T007`, `T008`).

---

## Implementation Strategy

### MVP First (User Stories 1 & 4)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (Database models).
3. Complete Phase 5: User Story 4 (Parse DXF to JSON schedule).
4. Complete Phase 3: User Story 1 (SVG visualization of the JSON schedule).
5. **STOP and VALIDATE**: Verify that the Sunday schedule from `L10 DOM.dxf` is extracted and displayed correctly in the browser.
