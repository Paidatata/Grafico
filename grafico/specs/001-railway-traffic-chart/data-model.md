# Data Model: Railway Traffic Chart

This document defines the schema and data models for the station network, planned schedules, and realized train events.

## 1. Relational Database Schema (SQLite)

We will use SQLite as the single source of truth for the local database.

### `stations`
Represents a physical railway station.
```sql
CREATE TABLE stations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    y_coordinate REAL NOT NULL, -- Geometric coordinate in DXF
    line TEXT NOT NULL          -- 'Line 10' or 'Line 7'
);
```

### `trips`
Represents an individual train journey.
```sql
CREATE TABLE trips (
    id TEXT PRIMARY KEY,        -- e.g., 'TRIP_BFU-RGS_043600'
    train_code TEXT NOT NULL,   -- e.g., 'G24', 'B365'
    direction TEXT NOT NULL,    -- 'BFU-RGS' or 'RGS-BFU'
    line TEXT NOT NULL          -- 'Line 10' or 'Line 7' or 'Line 710'
);
```

### `planned_stops`
Represents a planned scheduled arrival/departure time for a trip at a station.
```sql
CREATE TABLE planned_stops (
    trip_id TEXT NOT NULL,
    station_id TEXT NOT NULL,
    arrival_time TEXT NOT NULL,   -- 'HH:MM:SS' format
    departure_time TEXT NOT NULL, -- 'HH:MM:SS' format
    sequence_order INTEGER NOT NULL,
    PRIMARY KEY (trip_id, station_id),
    FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    FOREIGN KEY (station_id) REFERENCES stations(id)
);
```

### `realized_events`
Represents the actual timestamp when a train arrived or departed a station (populated via future tracking integration).
```sql
CREATE TABLE realized_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL,
    station_id TEXT NOT NULL,
    event_type TEXT NOT NULL,      -- 'ARRIVAL' or 'DEPARTURE'
    actual_time TEXT NOT NULL,     -- 'HH:MM:SS' format
    FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    FOREIGN KEY (station_id) REFERENCES stations(id)
);
```

---

## 2. Intermediate JSON Data Schema (DXF Export / Frontend Import)

The command-line parser outputs a `schedule.json` file. The frontend imports this file to render the planned train graph.

### Trip Object Structure
```json
[
  {
    "trip_id": "TRIP_BFU-RGS_043600",
    "direction": "BFU-RGS",
    "start_time": "04:36:00",
    "end_time": "04:46:00",
    "stops": [
      {
        "station": "GPT",
        "time": "04:36:00",
        "x_coord": 5520.08,
        "y_coord": 1660.32
      },
      {
        "station": "RPI",
        "time": "04:41:00",
        "x_coord": 5620.08,
        "y_coord": 1100.32
      },
      {
        "station": "RGS",
        "time": "04:46:00",
        "x_coord": 5720.08,
        "y_coord": 500.32
      }
    ]
  }
]
```

## 3. Data Integrity & Validation Rules

1. **Chronological Order**:
   For any trip, the stops must be sorted by `sequence_order`. The time at `sequence_order = N + 1` must be greater than or equal to the time at `sequence_order = N`.
2. **Propagation Logic**:
   When a planned departure time at `sequence_order = K` is updated by $+D$ minutes:
   - For all stops where `sequence_order > K`:
     - The arrival time and departure time must be incremented by $+D$ minutes.
     - The travel duration between stations remains constant.
