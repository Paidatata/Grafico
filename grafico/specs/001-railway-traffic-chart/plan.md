# Implementation Plan: Railway Traffic Chart (Gráfico de Horário de Circulação Ferroviária)

**Branch**: `001-railway-traffic-chart` | **Date**: 2026-08-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-railway-traffic-chart/spec.md`

## Summary

Extract CPTM Line 710 Sunday schedule from the AutoCAD DXF drawing `L10 DOM.dxf` into an intermediate JSON file and a relational SQLite database. Then, render the time-distance train graph interactively in an HTML/JS frontend using Scalable Vector Graphics (SVG). The frontend allows dispatchers to edit station departure/arrival nodes on the chart and propagates the delays downstream.

## Technical Context

**Language/Version**: Python 3.12 (backend parser), Vanilla HTML5/CSS3/JavaScript (frontend)

**Primary Dependencies**: None (pure Python standard library for DXF parsing, standard Web DOM/SVG APIs for visualization)

**Storage**: SQLite database (single source of truth for train schedules and events), JSON file as intermediate DXF export format

**Testing**: Python `unittest` framework for parser validation, manual browser validation for interactive node dragging and time propagation

**Target Platform**: Desktop web browsers (Chrome, Firefox, Safari) and standard Python 3 execution environments (Linux/macOS)

**Project Type**: Web Application & CLI parser tool

**Performance Goals**: Render the full 24-hour train graph in under 1 second; update and propagate node shifts in under 500ms

**Constraints**: Offline-capable frontend client; fully self-contained Python parser with no external pip package requirements

**Scale/Scope**: 251 train trips, 32 physical stations, 24-hour timeline schedule

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

No constitutional violations detected. The architecture follows a simple, testable, and self-contained design.

## Project Structure

### Documentation (this feature)

```text
specs/001-railway-traffic-chart/
├── spec.md              # Feature specification
├── plan.md              # This file (implementation plan)
├── research.md          # Reverse engineering and architectural decisions
├── data-model.md        # Relational and JSON data schemas
├── quickstart.md        # Validation and execution guide
└── checklists/
    └── requirements.md  # Quality validation checklist
```

### Source Code

```text
backend/
├── src/
│   ├── parser.py        # Python script to extract DXF schedules to JSON
│   ├── database.py      # SQLite database initializer and seeder
│   └── __init__.py
├── tests/
│   ├── test_parser.py   # Unit tests for the DXF coordinate conversions
│   └── __init__.py
└── data/
    └── L10 DOM.dxf      # AutoCAD source drawing file (located in workspace root)

frontend/
├── src/
│   ├── index.html       # Main chart interface (upload JSON, view SVG graph)
│   ├── index.css        # Premium dark-mode styling and animations
│   └── app.js           # SVG rendering, interactive drag-and-drop, and propagation logic
└── tests/
    └── manual_test.md   # Interactive test scenarios checklist
```

**Structure Decision**: A clear division between the offline Python CLI parser (backend/) and the client-side SVG-based visualization tool (frontend/). This matches the user choice of two separate operations (generating JSON/CSV via script first, uploading/importing via web interface second).

## Complexity Tracking

No violations. The chosen architecture is minimal, avoids complex frameworks, and uses native browser capabilities.
