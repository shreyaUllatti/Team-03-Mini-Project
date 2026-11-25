import struct
import sqlite3
import json
from shapely import wkb

def parse_gpkg_geom(blob):
    """
    Decodes standard OGC GeoPackage binary geometry header to Shapely shape.
    """
    if not blob or len(blob) < 8:
        return None
    # GPKG geometry binary header:
    # 2 bytes magic: 'GP' (0x47, 0x50)
    # 1 byte version
    # 1 byte flags
    # 4 bytes srs_id
    magic, version, flags, srs_id = struct.unpack('<2sBB i', blob[:8])
    if magic != b'GP':
        return None
    
    # Envelope contents indicator (bits 1-3)
    envelope_type = (flags >> 1) & 0x07
    header_len = 8
    if envelope_type == 1:
        header_len += 32
    elif envelope_type in (2, 3):
        header_len += 48
    elif envelope_type == 4:
        header_len += 64

    wkb_bytes = blob[header_len:]
    try:
        geom = wkb.loads(wkb_bytes)
        return geom
    except Exception:
        return None

def import_gpkg_to_network(gpkg_path, table_name="campus_roads_1"):
    conn = sqlite3.connect(gpkg_path)
    cur = conn.cursor()
    cur.execute(f"SELECT fid, geom, full_id, highway, maxspeed, maxheight, width, oneway, name FROM {table_name}")
    rows = cur.fetchall()

    nodes_dict = {}
    edges_list = []

    def get_node_id(pt):
        # Round coordinates to 6 decimals to snap adjacent endpoints
        key = (round(pt[1], 6), round(pt[0], 6)) # (lat, lon)
        if key not in nodes_dict:
            n_id = f"NODE_{len(nodes_dict) + 1}"
            nodes_dict[key] = {
                "id": n_id,
                "lat": key[0],
                "lon": key[1],
                "name": f"Junction {n_id}"
            }
        return nodes_dict[key]["id"]

    for row in rows:
        fid, geom_blob, full_id, highway, maxspeed, maxheight, width, oneway, name = row
        geom = parse_gpkg_geom(geom_blob)
        if not geom:
            continue

        lines = [geom] if geom.geom_type == 'LineString' else (geom.geoms if geom.geom_type == 'MultiLineString' else [])

        for line in lines:
            coords = list(line.coords)
            if len(coords) < 2:
                continue

            for i in range(len(coords) - 1):
                p1 = coords[i]     # (lon, lat)
                p2 = coords[i + 1] # (lon, lat)
                
                u = get_node_id(p1)
                v = get_node_id(p2)

                # Estimate distance in meters using simple equirectangular projection
                dlat = (p2[1] - p1[1]) * 111139.0
                dlon = (p2[0] - p1[0]) * 111139.0 * 0.96 # approx cos(lat)
                dist = max(1.0, (dlat**2 + dlon**2)**0.5)

                speed = 40.0
                if maxspeed:
                    try: speed = float(str(maxspeed).split()[0])
                    except: pass
                elif highway in ('motorway', 'trunk', 'primary'):
                    speed = 60.0

                h_val = 4.5
                if maxheight:
                    try: h_val = float(str(maxheight).split()[0])
                    except: pass

                w_val = 6.0
                if width:
                    try: w_val = float(str(width).split()[0])
                    except: pass

                edge_id = f"E_{full_id or fid}_{i}"
                road_label = name or f"{highway or 'road'} ({full_id or fid})"

                edges_list.append({
                    "id": edge_id,
                    "source": u,
                    "target": v,
                    "distance": round(dist, 1),
                    "speed": speed,
                    "height": h_val,
                    "weight": 25.0,
                    "width": w_val,
                    "name": road_label
                })

                if not oneway or oneway in ('no', '0', 'false'):
                    edges_list.append({
                        "id": f"{edge_id}_rev",
                        "source": v,
                        "target": u,
                        "distance": round(dist, 1),
                        "speed": speed,
                        "height": h_val,
                        "weight": 25.0,
                        "width": w_val,
                        "name": road_label
                    })

    conn.close()
    return {
        "nodes": list(nodes_dict.values()),
        "edges": edges_list
    }

if __name__ == "__main__":
    net = import_gpkg_to_network("C:/Projects/Intelligent-Emergency-Response/gis/data/campus_roads_export.gpkg")
    print(f"Imported real GIS network: {len(net['nodes'])} nodes, {len(net['edges'])} edges")
    with open("C:/Projects/Intelligent-Emergency-Response/gis/data/imported_gis_network.json", "w", encoding="utf-8") as f:
        json.dump(net, f, indent=2)
    print("Saved imported network to imported_gis_network.json")
