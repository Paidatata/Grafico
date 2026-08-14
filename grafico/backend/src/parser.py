import os
import json
import re

# Resolve paths relative to this script
script_dir = os.path.dirname(os.path.abspath(__file__))
dxf_path = os.path.join(script_dir, "../../../L10 DOM.dxf")
if not os.path.exists(dxf_path):
    dxf_path = os.path.join(script_dir, "../../data/L10 DOM.dxf")

output_dir = os.path.join(script_dir, "../data")
output_path = os.path.join(output_dir, "schedule.json")

# Ensure output directory exists
os.makedirs(output_dir, exist_ok=True)

# Define the Y coordinates mapping to station codes
stations_row1 = {
    500.32: "RGS", # Rio Grande da Serra
    1100.32: "RPI", # Ribeirão Pires
    1660.32: "GPT", # Guapituba
    2100.32: "MAU", # Mauá
    2500.32: "CPV", # Capuava
    2980.32: "SAN", # Santo André
    3220.32: "PSA", # Prefeito Saladino
    3420.32: "UTG", # Utinga
    3860.32: "SCS", # São Caetano do Sul
    4180.32: "TMD", # Tamanduateí
    4380.32: "IPG", # Ipiranga
    4740.32: "MOC", # Juventus-Mooca
    4980.32: "BAS", # Brás
    5380.32: "LUZ", # Luz
    5860.32: "BFU"  # Barra Funda
}

stations_row2 = {
    6180.32: "LUZ", # Luz
    6420.32: "ABR", # Água Branca
    6700.32: "LPA", # Lapa
    6980.32: "PQR", # Piqueri
    7300.32: "PRU", # Pirituba
    7500.32: "VCL", # Vila Clarice
    7900.32: "JRG", # Jaraguá
    8260.32: "VPL", # Vila Aurora
    8700.32: "PRT", # Perus
    9260.32: "CAI", # Caieiras
    9500.32: "FMO", # Franco da Rocha
    9940.32: "BFI", # Baltazar Fidélis
    10300.32: "FDR", # Francisco Morato
    10580.32: "BTJ", # Botujuru
    10900.32: "CLP", # Campo Limpo Paulista
    11220.32: "VAU", # Várzea Paulista
    11520.32: "JUN"  # Jundiaí
}

# Combine all stations for easy lookup by closest Y coordinate
all_stations = {}
all_stations.update(stations_row1)
all_stations.update(stations_row2)

def coord_to_time(x):
    # 1 hour = 1200 units, 1 minute = 20 units
    total_minutes = x / 20.0
    hours = int(total_minutes // 60) % 24
    minutes = int(total_minutes % 60)
    seconds = int((total_minutes * 60) % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def get_station_code(y):
    closest_y = min(all_stations.keys(), key=lambda k: abs(k - y))
    if abs(closest_y - y) > 50.0:
        return None
    return all_stations[closest_y]

def parse_dxf_schedule():
    if not os.path.exists(dxf_path):
        print(f"Error: DXF file not found at {dxf_path}")
        return

    print(f"Inspecting DXF file: {dxf_path} ({os.path.getsize(dxf_path) / 1024 / 1024:.2f} MB)")
    
    target_layers = {"BFU-RGS", "RGS-BFU"}
    trips = []
    
    current_entity = None
    with open(dxf_path, 'r', encoding='utf-8', errors='ignore') as f:
        code_line = f.readline()
        while code_line:
            code = code_line.strip()
            val = f.readline().strip()
            
            if code == '0':
                if current_entity and current_entity.get('layer') in target_layers:
                    process_trip(current_entity, trips)
                current_entity = {'type': val, 'vertices': []}
            elif current_entity:
                if code == '8':
                    current_entity['layer'] = val
                elif code == '10':
                    current_entity['vertices'].append([float(val), None])
                elif code == '20':
                    if current_entity['vertices']:
                        current_entity['vertices'][-1][1] = float(val)
            
            code_line = f.readline()
            
    # Process last entity
    if current_entity and current_entity.get('layer') in target_layers:
        process_trip(current_entity, trips)

    disambiguate_trip_ids(trips)
    compute_train_codes(trips)

    # Save to JSON
    with open(output_path, 'w', encoding='utf-8') as out_f:
        json.dump(trips, out_f, indent=2, ensure_ascii=False)
        
    print(f"Successfully parsed {len(trips)} trips and saved to {output_path}")

def process_trip(entity, trips):
    vertices = entity.get('vertices', [])
    valid_vertices = [pt for pt in vertices if pt[0] > 10.0 and pt[1] is not None and pt[1] > 10.0]
    
    if len(valid_vertices) < 2:
        return
        
    stops = []
    for x, y in valid_vertices:
        station = get_station_code(y)
        if station:
            time_str = coord_to_time(x)
            stops.append({
                "station": station,
                "time": time_str,
                "x_coord": x,
                "y_coord": y
            })
            
    if len(stops) >= 2:
        # Sort stops chronologically by X coordinate (time)
        stops = sorted(stops, key=lambda s: s["x_coord"])

        direction = entity.get('layer')
        start_time = stops[0]["time"]
        end_time = stops[-1]["time"]

        trips.append({
            "trip_id": f"TRIP_{direction}_{start_time.replace(':', '')}",
            "direction": direction,
            "start_time": start_time,
            "end_time": end_time,
            "stops": stops
        })

def disambiguate_trip_ids(trips):
    # Two distinct DXF entities can share both direction and start_time (e.g. a train
    # starting its run partway down the line at the same minute another train departs
    # the terminal) — trip_id is built from only those two fields, so they'd otherwise
    # collide and violate the backend's trip_id primary key. First occurrence of an id
    # keeps it unchanged; each later collision gets a stable "_2", "_3", ... suffix in
    # the order trips were appended (deterministic for a given DXF file).
    seen_counts = {}
    for trip in trips:
        base_id = trip["trip_id"]
        occurrence = seen_counts.get(base_id, 0) + 1
        seen_counts[base_id] = occurrence
        if occurrence > 1:
            trip["trip_id"] = f"{base_id}_{occurrence}"
    return trips

# Real-world CPTM Line 710 field convention: trains are numbered by direction,
# not by a raw sequential counter. Trains terminating at Barra Funda get an
# odd-increasing "P" code; trains terminating at Rio Grande da Serra or at
# Mauá (a shorter turn-back service) share one even-increasing sequence,
# prefixed "R" or "M" by their own destination. Extend this table — not the
# fallback below — if a future DXF introduces another destination.
ODD_DESTINATION_PREFIXES = {"BFU": "P"}
EVEN_DESTINATION_PREFIXES = {"RGS": "R", "MAU": "M"}

def compute_train_codes(trips):
    # Numbers increase through the day by departure time. Two trips can share
    # an exact departure time (see disambiguate_trip_ids) when one starts
    # partway down the line instead of at the terminal — in that case the one
    # whose origin is geographically closer to the destination (shorter DXF Y
    # distance, i.e. shorter route) gets the smaller number.
    def sort_key(trip):
        origin_y = trip["stops"][0]["y_coord"]
        destination_y = trip["stops"][-1]["y_coord"]
        return (trip["start_time"], abs(origin_y - destination_y))

    def destination_of(trip):
        return trip["stops"][-1]["station"]

    odd_group = sorted(
        (t for t in trips if destination_of(t) in ODD_DESTINATION_PREFIXES),
        key=sort_key,
    )
    for i, trip in enumerate(odd_group):
        number = 2 * i + 1
        trip["train_code"] = f"{ODD_DESTINATION_PREFIXES[destination_of(trip)]}{number}"

    even_group = sorted(
        (t for t in trips if destination_of(t) in EVEN_DESTINATION_PREFIXES),
        key=sort_key,
    )
    for i, trip in enumerate(even_group):
        number = 2 * (i + 1)
        trip["train_code"] = f"{EVEN_DESTINATION_PREFIXES[destination_of(trip)]}{number}"

    unassigned = [t for t in trips if "train_code" not in t]
    if unassigned:
        destinations = sorted({destination_of(t) for t in unassigned})
        raise ValueError(
            f"compute_train_codes: {len(unassigned)} trip(s) terminate at a "
            f"destination outside the known P/R/M scheme ({destinations}). "
            "Add it to ODD_DESTINATION_PREFIXES or EVEN_DESTINATION_PREFIXES "
            "before regenerating schedule.json."
        )

    return trips

if __name__ == "__main__":
    parse_dxf_schedule()
