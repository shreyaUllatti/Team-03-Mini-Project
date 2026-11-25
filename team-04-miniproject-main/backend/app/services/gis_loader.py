import json
import os
from typing import Dict, Any, Optional
from app.algorithms.routing import RoutingEngine

GIS_JSON_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "gis", "data", "imported_gis_network.json"))

def load_gis_network_into_engine(engine: RoutingEngine, network_dict: Optional[Dict] = None):
    """
    Populates in-memory routing engine graph with real GIS road network (Hubballi / Vidyanagar campus corridor).
    Falls back to embedded reference network if JSON file is absent.
    """
    if network_dict is None and os.path.exists(GIS_JSON_PATH):
        try:
            with open(GIS_JSON_PATH, "r", encoding="utf-8") as f:
                network_dict = json.load(f)
        except Exception:
            network_dict = None

    if not network_dict:
        # Fallback benchmark topology
        network_dict = {
            "nodes": [
                {"id": "NODE_1", "name": "KLE Tech Main Entrance", "lat": 15.3670, "lon": 75.1220},
                {"id": "NODE_2", "name": "Vidyanagar Junction", "lat": 15.3645, "lon": 75.1240},
                {"id": "NODE_3", "name": "BVB Campus Ring Road", "lat": 15.3685, "lon": 75.1205},
                {"id": "NODE_4", "name": "Hospital Emergency Gate", "lat": 15.3620, "lon": 75.1260}
            ],
            "edges": [
                {"id": "E1", "source": "NODE_1", "target": "NODE_2", "distance": 450.0, "speed": 40.0, "height": 4.5, "weight": 20.0, "width": 6.5, "name": "Campus Drive"},
                {"id": "E1_rev", "source": "NODE_2", "target": "NODE_1", "distance": 450.0, "speed": 40.0, "height": 4.5, "weight": 20.0, "width": 6.5, "name": "Campus Drive"},
                {"id": "E2", "source": "NODE_2", "target": "NODE_4", "distance": 520.0, "speed": 50.0, "height": 4.5, "weight": 25.0, "width": 7.0, "name": "Vidyanagar Main Rd"},
                {"id": "E2_rev", "source": "NODE_4", "target": "NODE_2", "distance": 520.0, "speed": 50.0, "height": 4.5, "weight": 25.0, "width": 7.0, "name": "Vidyanagar Main Rd"}
            ]
        }

    for n in network_dict["nodes"]:
        engine.add_node(n["id"], n["lat"], n["lon"], n.get("name"))
    
    for e in network_dict["edges"]:
        engine.add_edge(
            edge_id=e["id"],
            source=e["source"],
            target=e["target"],
            distance_meters=e.get("distance", 100.0),
            speed_limit_kmh=e.get("speed", 40.0),
            current_traffic_factor=e.get("traffic", 1.0),
            max_height=e.get("height", 4.5),
            max_weight=e.get("weight", 20.0),
            width=e.get("width", 6.0),
            road_name=e.get("name", "Road")
        )
