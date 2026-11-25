"""
Loads the 1,282 nodes and 2,267 edges from imported_gis_network.json into PostGIS emergency schema.
Generates 03_road_network.sql and directly loads into Docker PostGIS container.
"""
import json
import subprocess
import os

JSON_PATH = "C:/Projects/Intelligent-Emergency-Response/gis/data/imported_gis_network.json"
SQL_OUT_PATH = "C:/Projects/Intelligent-Emergency-Response/gis/sql/03_road_network.sql"

with open(JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

nodes = data["nodes"]
edges = data["edges"]
print(f"Loaded {len(nodes)} nodes, {len(edges)} edges from JSON")

# Build node coordinate lookup for edge LineString generation
node_coords = {n["id"]: (n["lon"], n["lat"]) for n in nodes}

sql_lines = [
    "-- ============================================================================",
    "-- 03_road_network.sql",
    "-- Intelligent Emergency Response System (IERS)",
    f"-- Population of {len(nodes)} Nodes, {len(edges)} Edges, Hospitals & Ambulances",
    "-- Dataset: Hubballi-Vidyanagar Smart Campus Corridor",
    "-- ============================================================================\n",
    "SET search_path TO emergency, public;\n",
    "-- 1. Populate Road Network Nodes",
    "INSERT INTO emergency.road_network_nodes (node_id, name, latitude, longitude, geom) VALUES"
]

# Format nodes batch
node_value_clauses = []
for n in nodes:
    nid = n["id"].replace("'", "''")
    name = (n.get("name") or nid).replace("'", "''")
    lat = n["lat"]
    lon = n["lon"]
    node_value_clauses.append(
        f"('{nid}', '{name}', {lat}, {lon}, ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326))"
    )

sql_lines.append(",\n".join(node_value_clauses) + "\nON CONFLICT (node_id) DO NOTHING;\n")

# Format edges batch
sql_lines.append("-- 2. Populate Road Network Edges")
sql_lines.append(
    "INSERT INTO emergency.road_network_edges "
    "(edge_id, source_id, target_id, road_name, distance_meters, speed_limit_kmh, "
    "current_traffic_factor, max_height_meters, max_weight_tons, width_meters, is_one_way, is_emergency_corridor, geom) VALUES"
)

edge_value_clauses = []
skipped = 0
for e in edges:
    eid = e["id"].replace("'", "''")
    src = e["source"].replace("'", "''")
    tgt = e["target"].replace("'", "''")
    name = (e.get("name") or "Road").replace("'", "''")
    dist = float(e.get("distance", 100.0))
    speed = float(e.get("speed", 40.0))
    traffic = float(e.get("traffic", 1.0))
    height = float(e.get("height", 4.5))
    weight = float(e.get("weight", 25.0))
    width = float(e.get("width", 6.0))
    oneway = "TRUE" if e.get("oneway") else "FALSE"
    corridor = "TRUE" if e.get("is_emergency_lane") else "FALSE"
    
    # Generate LineString geometry from source and target coordinates
    if e["source"] in node_coords and e["target"] in node_coords:
        p1 = node_coords[e["source"]]
        p2 = node_coords[e["target"]]
        wkt = f"SRID=4326;LINESTRING({p1[0]} {p1[1]}, {p2[0]} {p2[1]})"
        edge_value_clauses.append(
            f"('{eid}', '{src}', '{tgt}', '{name}', {dist}, {speed}, {traffic}, {height}, {weight}, {width}, {oneway}, {corridor}, ST_GeomFromEWKT('{wkt}'))"
        )
    else:
        skipped += 1

print(f"Edges formatted: {len(edge_value_clauses)}, skipped: {skipped}")
sql_lines.append(",\n".join(edge_value_clauses) + "\nON CONFLICT (edge_id) DO NOTHING;\n")

# Format hospitals and ambulances
sql_lines.extend([
    "-- 3. Populate Hospitals & Trauma Centers",
    "INSERT INTO emergency.hospitals (hospital_id, name, nearest_node_id, total_beds, icu_available, trauma_level, has_helipad, geom) VALUES",
    "('H_01', 'KIMS Medical Center & Level 1 Trauma Hub', 'NODE_473', 180, 22, 1, TRUE, ST_SetSRID(ST_MakePoint(75.123161, 15.369641), 4326)),",
    "('H_02', 'Vidyanagar Emergency Care & Cardiac Center', 'NODE_964', 90, 8, 2, FALSE, ST_SetSRID(ST_MakePoint(75.123812, 15.365116), 4326))",
    "ON CONFLICT (hospital_id) DO UPDATE SET icu_available = EXCLUDED.icu_available;\n",
    "-- 4. Populate Emergency Fleet",
    "INSERT INTO emergency.ambulances (ambulance_id, call_sign, vehicle_type, status, height_meters, weight_tons, width_meters, current_node_id, driver_name, geom) VALUES",
    "('AMB_01', 'PARAMEDIC-ALS-01', 'ALS', 'AVAILABLE', 3.2, 5.2, 2.6, 'NODE_567', 'Harris Whitaker (EMT-P)', ST_SetSRID(ST_MakePoint(75.121066, 15.368637), 4326)),",
    "('AMB_02', 'RAPID-FLYER-02', 'FLYER', 'AVAILABLE', 1.8, 0.4, 1.1, 'NODE_964', 'Sofia Lind', ST_SetSRID(ST_MakePoint(75.123812, 15.365116), 4326)),",
    "('AMB_03', 'RESCUE-BLS-03', 'BLS', 'AVAILABLE', 2.5, 3.6, 2.3, 'NODE_473', 'Lars Nyström', ST_SetSRID(ST_MakePoint(75.123161, 15.369641), 4326))",
    "ON CONFLICT (ambulance_id) DO UPDATE SET status = EXCLUDED.status;\n"
])

full_sql = "\n".join(sql_lines)
with open(SQL_OUT_PATH, "w", encoding="utf-8") as f:
    f.write(full_sql)

print(f"Written SQL file to {SQL_OUT_PATH} ({len(full_sql)} bytes)")
