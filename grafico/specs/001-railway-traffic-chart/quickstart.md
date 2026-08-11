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

## 3. Launch Frontend Time-Distance Graphic

1. Navigate to the `frontend/` directory.
2. Open `src/index.html` in a web browser.
3. Select the generated `schedule.json` file via the file upload input.
4. Verify that:
   - The time-distance grid is displayed showing stations on the vertical axis and times (00:00 to 24:00) on the horizontal axis.
   - Train lines are plotted (dashed lines for planned schedule).
   - Clicking and dragging any station node on the chart shifts the time and propagates the delay to all subsequent station stops.
