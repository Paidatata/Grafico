import sqlite3
import os
import json

# Resolve database path relative to this script
script_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(script_dir, "../data/railway.db")
schedule_json_path = os.path.join(script_dir, "../data/schedule.json")

stations_metadata = [
    # Row 1 (Line 10)
    {"id": "RGS", "name": "Rio Grande da Serra", "y_coordinate": 500.32, "line": "Line 10"},
    {"id": "RPI", "name": "Ribeirão Pires", "y_coordinate": 1100.32, "line": "Line 10"},
    {"id": "GPT", "name": "Guapituba", "y_coordinate": 1660.32, "line": "Line 10"},
    {"id": "MAU", "name": "Mauá", "y_coordinate": 2100.32, "line": "Line 10"},
    {"id": "CPV", "name": "Capuava", "y_coordinate": 2500.32, "line": "Line 10"},
    {"id": "SAN", "name": "Santo André", "y_coordinate": 2980.32, "line": "Line 10"},
    {"id": "PSA", "name": "Prefeito Saladino", "y_coordinate": 3220.32, "line": "Line 10"},
    {"id": "UTG", "name": "Utinga", "y_coordinate": 3420.32, "line": "Line 10"},
    {"id": "SCS", "name": "São Caetano do Sul", "y_coordinate": 3860.32, "line": "Line 10"},
    {"id": "TMD", "name": "Tamanduateí", "y_coordinate": 4180.32, "line": "Line 10"},
    {"id": "IPG", "name": "Ipiranga", "y_coordinate": 4380.32, "line": "Line 10"},
    {"id": "MOC", "name": "Juventus-Mooca", "y_coordinate": 4740.32, "line": "Line 10"},
    {"id": "BAS", "name": "Brás", "y_coordinate": 4980.32, "line": "Line 10"},
    {"id": "LUZ", "name": "Luz", "y_coordinate": 5380.32, "line": "Line 10"},
    {"id": "BFU", "name": "Barra Funda", "y_coordinate": 5860.32, "line": "Line 10"},
    # Row 2 (Line 7)
    {"id": "LUZ_L7", "name": "Luz (L7)", "y_coordinate": 6180.32, "line": "Line 7"},
    {"id": "ABR", "name": "Água Branca", "y_coordinate": 6420.32, "line": "Line 7"},
    {"id": "LPA", "name": "Lapa", "y_coordinate": 6700.32, "line": "Line 7"},
    {"id": "PQR", "name": "Piqueri", "y_coordinate": 6980.32, "line": "Line 7"},
    {"id": "PRU", "name": "Pirituba", "y_coordinate": 7300.32, "line": "Line 7"},
    {"id": "VCL", "name": "Vila Clarice", "y_coordinate": 7500.32, "line": "Line 7"},
    {"id": "JRG", "name": "Jaraguá", "y_coordinate": 7900.32, "line": "Line 7"},
    {"id": "VPL", "name": "Vila Aurora", "y_coordinate": 8260.32, "line": "Line 7"},
    {"id": "PRT", "name": "Perus", "y_coordinate": 8700.32, "line": "Line 7"},
    {"id": "CAI", "name": "Caieiras", "y_coordinate": 9260.32, "line": "Line 7"},
    {"id": "FMO", "name": "Franco da Rocha", "y_coordinate": 9500.32, "line": "Line 7"},
    {"id": "BFI", "name": "Baltazar Fidélis", "y_coordinate": 9940.32, "line": "Line 7"},
    {"id": "FDR", "name": "Francisco Morato", "y_coordinate": 10300.32, "line": "Line 7"},
    {"id": "BTJ", "name": "Botujuru", "y_coordinate": 10580.32, "line": "Line 7"},
    {"id": "CLP", "name": "Campo Limpo Paulista", "y_coordinate": 10900.32, "line": "Line 7"},
    {"id": "VAU", "name": "Várzea Paulista", "y_coordinate": 11220.32, "line": "Line 7"},
    {"id": "JUN", "name": "Jundiaí", "y_coordinate": 11520.32, "line": "Line 7"}
]

def init_db():
    print(f"Initializing database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        y_coordinate REAL NOT NULL,
        line TEXT NOT NULL
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trips (
        id TEXT PRIMARY KEY,
        train_code TEXT NOT NULL,
        direction TEXT NOT NULL,
        line TEXT NOT NULL
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS planned_stops (
        trip_id TEXT NOT NULL,
        station_id TEXT NOT NULL,
        arrival_time TEXT NOT NULL,
        departure_time TEXT NOT NULL,
        sequence_order INTEGER NOT NULL,
        PRIMARY KEY (trip_id, station_id),
        FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
        FOREIGN KEY (station_id) REFERENCES stations(id)
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS realized_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id TEXT NOT NULL,
        station_id TEXT NOT NULL,
        event_type TEXT NOT NULL, -- 'ARRIVAL' or 'DEPARTURE'
        actual_time TEXT NOT NULL,
        FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
        FOREIGN KEY (station_id) REFERENCES stations(id)
    );
    """)
    
    conn.commit()
    return conn

def seed_stations(conn):
    print("Seeding stations table...")
    cursor = conn.cursor()
    for station in stations_metadata:
        cursor.execute("""
        INSERT OR REPLACE INTO stations (id, name, y_coordinate, line)
        VALUES (?, ?, ?, ?);
        """, (station["id"], station["name"], station["y_coordinate"], station["line"]))
    conn.commit()
    print(f"Successfully seeded {len(stations_metadata)} stations.")

def seed_schedule_from_json(conn):
    if not os.path.exists(schedule_json_path):
        print(f"No schedule JSON found at {schedule_json_path}. Skipping schedule seeding.")
        return
        
    print("Seeding trips and planned stops from schedule.json...")
    with open(schedule_json_path, 'r', encoding='utf-8') as f:
        trips_data = json.load(f)
        
    cursor = conn.cursor()
    
    trips_count = 0
    stops_count = 0
    
    for trip in trips_data:
        trip_id = trip["trip_id"]
        direction = trip["direction"]
        
        # Deduce line from direction/stations
        line = "Line 710"
        
        # Insert Trip
        train_code = trip_id.split("_")[-1] # fallback train code
        cursor.execute("""
        INSERT OR REPLACE INTO trips (id, train_code, direction, line)
        VALUES (?, ?, ?, ?);
        """, (trip_id, train_code, direction, line))
        trips_count += 1
        
        # Insert Planned Stops
        for idx, stop in enumerate(trip["stops"]):
            station_id = stop["station"]
            # Handle Luz station naming difference in Row 2 vs Row 1
            if y_coordinate_is_row2(stop["y_coord"]) and station_id == "LUZ":
                station_id = "LUZ_L7"
                
            time_str = stop["time"]
            cursor.execute("""
            INSERT OR REPLACE INTO planned_stops (trip_id, station_id, arrival_time, departure_time, sequence_order)
            VALUES (?, ?, ?, ?, ?);
            """, (trip_id, station_id, time_str, time_str, idx))
            stops_count += 1
            
    conn.commit()
    print(f"Successfully seeded {trips_count} trips and {stops_count} planned stops.")

def y_coordinate_is_row2(y):
    return y > 6000.0

if __name__ == "__main__":
    conn = init_db()
    seed_stations(conn)
    seed_schedule_from_json(conn)
    conn.close()
