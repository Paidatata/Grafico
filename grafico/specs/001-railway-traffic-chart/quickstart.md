# Quickstart Guide: Railway Traffic Chart

This guide explains how to execute the DXF parsing script, verify the generated JSON data, and load the interactive chart in the web browser.

## Prerequisites

- **Python 3.12** or later (no external libraries required)
- A modern web browser supporting SVG (Chrome, Firefox, Safari, Edge)

---

## 1. Extract Train Schedules from DXF

Run the Python parser script from the repository root to scan the AutoCAD drawing `L10 DOM.dxf` and generate the JSON schedule:

```bash
# Run the extraction script
python3 backend/src/parser.py
```

### Expected Output
The script prints the parsing summary:
```text
Inspecting DXF file: L10 DOM.dxf (16.60 MB)
Successfully parsed 251 trips and saved to backend/data/schedule.json
```

---

## 2. Verify Output Data

Check that the generated `backend/data/schedule.json` file contains structured trip objects:

```bash
# Preview the first few lines of the output JSON
head -n 25 backend/data/schedule.json
```

It should match the [JSON Intermediate Schema](data-model.md#2-intermediate-json-data-schema-dxf-export--frontend-import).

---

## 3. Start the Backend Server

```bash
pip install -r backend/requirements.txt
uvicorn backend.src.app:app --reload --host 0.0.0.0 --port 8000
```

The server creates `backend/data/railway.db` on first run and seeds it with station data.

## 4. Import the Schedule and Open the Chart

1. Open `http://<server-host>:8000/` in a browser (any machine on the network, not just the server itself).
2. Click **"Importar JSON"** and select `backend/data/schedule.json` (generated in step 1). This uploads it as the day's template baseline via `POST /api/template/import`, which also populates today's live schedule.
3. Verify the time-distance grid renders with stations on the vertical axis and times on the horizontal axis, with train lines plotted as dashed lines.
4. Drag a station node — the dragged node and every downstream stop on that trip shift by the same amount, computed and persisted by the backend. Open the page in a second browser tab (or from another machine) to see the edit appear there live over the WebSocket connection.
