# Feature Specification: Railway Traffic Chart (Gráfico de Horário de Circulação Ferroviária)

**Feature Branch**: `001-railway-traffic-chart`

**Created**: 2026-08-04

**Status**: Ready

**Input**: User description: "grafico horario de circulação ferroviaria, com uma pré programação e circulação realizada em html e bando de dados ou tabela como verdade para o sistema. Na pagina do frontend, as linhas devem ser habilitadas para editar em nós os horarios nas estações e essa alteração se propaga ao futuro. Rastreamento será inserido futuramente."

## Clarifications

### Session 2026-08-05
- Q: Como o sistema deve processar o arquivo `.dxf` para povoar o banco de dados/tabela de verdade? → A: Um script CLI de backend extrairá os dados do DXF e gerará um arquivo intermediário JSON/CSV. Em seguida, a interface web permitirá fazer o upload desse arquivo JSON/CSV para importar os dados no banco de dados.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Visualizing the planned vs realized train graph (Priority: P1)

The traffic dispatcher wants to see a time-distance graph (Marey chart) where the pre-programmed (planned) schedule is represented as a dashed line and the actual train circulation is represented as a solid line, so that they can quickly spot delays and advances.

**Why this priority**: This is the core visualization component and the main value of the system.

**Independent Test**: Can be tested by loading sample database tables for planned and actual events and verifying that the HTML chart renders lines correctly for each train trip.

**Acceptance Scenarios**:

1. **Given** a planned schedule with Train A going from Station 1 to Station 3, **When** the page loads, **Then** a dashed line connects Station 1, 2, and 3 at their respective scheduled times.
2. **Given** realized/actual event data for Train A with a 10-minute delay at Station 2, **When** the page loads, **Then** a solid line is displayed showing the shift in arrival/departure times at Station 2.

---

### User Story 2 - Interactive editing and time propagation of planned schedules (Priority: P1)

The traffic dispatcher wants to edit schedule times for any station stop (node) on the HTML chart (e.g., dragging the node or editing a field in the UI), and have that change propagate to all subsequent stops of that train's trip.

**Why this priority**: Essential for active traffic planning and updating schedules dynamically when operational delays occur.

**Independent Test**: Can be tested by modifying a train's departure time at an intermediate station, verifying that the departure times at all downstream stations increase by the same amount, and confirming the updated times are saved in the database.

**Acceptance Scenarios**:

1. **Given** Train A has a planned schedule: Station 1 (dep 12:00), Station 2 (arr 12:15, dep 12:20), Station 3 (arr 12:40), **When** the dispatcher edits Station 2 departure to 12:30 (+10 min), **Then** Station 3 arrival automatically shifts to 12:50 (+10 min) and the new planned times are saved.

---

### User Story 3 - Displaying actual tracking data (Priority: P2)

The system displays actual train tracking data written to the database by external processes/systems.

**Why this priority**: Required for comparing planned vs actual circulation.

**Independent Test**: Can be tested by writing mock tracking data directly to the database and checking that the HTML chart refreshes and renders the new solid line section.

**Acceptance Scenarios**:

1. **Given** actual train event logs are added to the database table, **When** the chart refreshes, **Then** a solid line is drawn representing the actual circulation up to the latest logged station.

---

### User Story 4 - Importing planned schedule from DXF (Priority: P2)

The administrator wants to run a CLI tool to convert the AutoCAD DXF schedule into a JSON/CSV file, and then upload it via the web interface to quickly initialize the database with all planned train schedules.

**Why this priority**: Automates the process of entering complex railway schedules instead of manually inputting them node by node.

**Independent Test**: Can be tested by running the CLI parser on `L10 DOM.dxf`, verifying a JSON/CSV is generated, uploading it through the UI, and checking that the schedules are written to the database and render on the graph.

**Acceptance Scenarios**:

1. **Given** a valid `L10 DOM.dxf` file, **When** the CLI tool is executed, **Then** a structured JSON/CSV file is successfully generated.
2. **Given** a generated JSON/CSV file, **When** the admin uploads it via the web interface, **Then** the database is populated and the planned lines show up on the Marey chart.

---

### Edge Cases

- **Skipped Station**: What happens when a train skips a station completely (no arrival/departure event logged)? The system should draw a straight line connecting the previous station's departure to the next station's arrival, marking the intermediate station as skipped.
- **Out-of-Order Events**: How does the system handle out-of-order actual events (e.g., dispatcher logs Station 3 arrival before logging Station 2 arrival)? The system should order events by station sequence along the route rather than input order.
- **Delayed Input**: If a train has already departed a station but no actual event is registered, the realized line should stop at the last known station until new data is input.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST render a time-distance graph (Marey diagram) in an HTML interface.
- **FR-002**: The graph MUST show stations on one axis (distance-based sequence) and time on the other axis (24-hour scale).
- **FR-003**: The graph MUST display two distinct lines for each train: one for the planned schedule (pre-programacão) as a dashed line and one for the actual performed circulation as a solid line.
- **FR-004**: The system MUST use a structured database or a tabular data structure (such as SQLite or JSON/CSV files) as the single source of truth for all train, station, plan, and realized event data.
- **FR-005**: The system MUST support editing planned time nodes (station arrival/departure) directly from the HTML frontend interface.
- **FR-006**: When a planned time node is updated, the system MUST propagate the time difference (+/- minutes shift) to all downstream station stops for that specific train trip.
- **FR-007**: The system MUST automatically persist the modified planned times back to the source of truth database/table.
- **FR-008**: The system MUST read and render actual train circulation data from the database, but automatic ingestion or direct tracking input APIs are out of scope for this version (reserved for future backend work).
- **FR-009**: The system MUST include a command-line script to parse train schedule data from a local AutoCAD DXF file and export it to an intermediate structured format (JSON or CSV).
- **FR-010**: The HTML frontend interface MUST allow uploading the generated JSON/CSV file to import the planned train schedules and stations into the database.

### Key Entities *(include if feature involves data)*

- **Station**: Represents a physical location along the railway. Key attributes: ID, Name, Kilopost (distance from origin).
- **Train Trip**: Represents a specific scheduled journey. Key attributes: Trip ID, Train Number/Code, Direction.
- **Planned Stop**: Represents a scheduled stop for a train at a station. Key attributes: Trip ID, Station ID, Planned Arrival Time, Planned Departure Time.
- **Realized Event**: Represents the actual time a train arrived or departed a station. Key attributes: Trip ID, Station ID, Event Type (Arrival/Departure), Actual Timestamp.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The HTML chart must render completely in under 1 second for a 24-hour schedule with up to 50 active trains.
- **SC-002**: Chart modification and propagation calculations must execute on the frontend and persist to the database in under 500ms.
- **SC-003**: 100% of planned vs realized deviations (delays/advances) are visually distinguishable via color-coded or styled lines.

## Assumptions

- The railway line has a fixed sequence of stations that doesn't change dynamically.
- The visualization is designed for desktop browser viewports due to the detail required in the time-distance chart.
- The source of truth database/table is accessible locally or via standard HTTP/database protocols.
