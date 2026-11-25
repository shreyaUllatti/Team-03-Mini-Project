import math
import heapq
import networkx as nx
from typing import List, Dict, Optional, Tuple

class RoutingEngine:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.nodes_data: Dict[str, Dict] = {}
        self.edges_data: Dict[str, Dict] = {}

    def add_node(self, node_id: str, lat: float, lon: float, name: Optional[str] = None):
        self.graph.add_node(node_id, lat=lat, lon=lon, name=name or node_id)
        self.nodes_data[node_id] = {"lat": lat, "lon": lon, "name": name or node_id}

    def add_edge(
        self,
        edge_id: str,
        source: str,
        target: str,
        distance_meters: float,
        speed_limit_kmh: float = 50.0,
        current_traffic_factor: float = 1.0,
        max_height: float = 4.5,
        max_weight: float = 20.0,
        width: float = 7.0,
        road_name: str = "Street",
        is_emergency_lane_active: bool = False
    ):
        # Effective speed considering traffic factor (traffic_factor >= 1.0)
        # Emergency lane cuts congestion impact by 60%
        effective_traffic = current_traffic_factor
        if is_emergency_lane_active:
            effective_traffic = 1.0 + (current_traffic_factor - 1.0) * 0.4
            
        speed_ms = (speed_limit_kmh / 3.6) / effective_traffic
        travel_time_seconds = distance_meters / max(speed_ms, 1.0)

        edge_attrs = {
            "id": edge_id,
            "road_name": road_name,
            "distance_meters": distance_meters,
            "speed_limit_kmh": speed_limit_kmh,
            "traffic_factor": current_traffic_factor,
            "effective_traffic": effective_traffic,
            "travel_time_seconds": travel_time_seconds,
            "max_height": max_height,
            "max_weight": max_weight,
            "width": width,
            "is_emergency_lane": is_emergency_lane_active
        }

        self.graph.add_edge(source, target, **edge_attrs)
        self.edges_data[edge_id] = {"source": source, "target": target, **edge_attrs}

    def haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate the great circle distance in meters between two points on earth."""
        R = 6371000  # meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def find_nearest_node(self, lat: float, lon: float) -> Optional[str]:
        """Finds closest node in the road network to given coordinates."""
        closest_node = None
        min_dist = float('inf')
        for node_id, data in self.nodes_data.items():
            dist = self.haversine_distance(lat, lon, data["lat"], data["lon"])
            if dist < min_dist:
                min_dist = dist
                closest_node = node_id
        return closest_node

    def find_constrained_route(
        self,
        start_node: str,
        end_node: str,
        vehicle_height: float = 2.4,
        vehicle_weight: float = 3.5,
        vehicle_width: float = 2.2
    ) -> Optional[Dict]:
        """
        Calculates optimal A* route adhering strictly to clearance limits:
        - Rejects bridges with max_height < vehicle_height
        - Rejects bridges/roads with max_weight < vehicle_weight
        - Rejects narrow passes with road width < vehicle_width
        """
        if start_node not in self.graph or end_node not in self.graph:
            return None

        # A* Priority Queue: (f_score, current_node, current_g, path)
        dest_coords = self.nodes_data[end_node]
        
        open_set = []
        heapq.heappush(open_set, (0.0, start_node, 0.0, [start_node]))
        
        g_scores = {start_node: 0.0}
        visited = set()

        while open_set:
            f, current, g, path = heapq.heappop(open_set)

            if current == end_node:
                # Build complete path details
                total_distance = 0.0
                total_time = 0.0
                path_coordinates = []
                road_segments = []

                for i in range(len(path) - 1):
                    u, v = path[i], path[i+1]
                    edge = self.graph[u][v]
                    total_distance += edge["distance_meters"]
                    total_time += edge["travel_time_seconds"]
                    road_segments.append({
                        "from": u,
                        "to": v,
                        "road_name": edge["road_name"],
                        "distance_m": round(edge["distance_meters"], 1),
                        "time_s": round(edge["travel_time_seconds"], 1),
                        "traffic_factor": edge["traffic_factor"]
                    })
                    path_coordinates.append([self.nodes_data[u]["lat"], self.nodes_data[u]["lon"]])
                
                path_coordinates.append([dest_coords["lat"], dest_coords["lon"]])

                return {
                    "path_nodes": path,
                    "coordinates": path_coordinates,
                    "segments": road_segments,
                    "total_distance_meters": round(total_distance, 1),
                    "total_duration_seconds": round(total_time, 1),
                    "eta_minutes": round(total_time / 60.0, 1),
                    "constraints_checked": {
                        "vehicle_height": vehicle_height,
                        "vehicle_weight": vehicle_weight,
                        "vehicle_width": vehicle_width
                    }
                }

            if current in visited and g_scores.get(current, float('inf')) < g:
                continue
            visited.add(current)

            for neighbor in self.graph.neighbors(current):
                edge_data = self.graph[current][neighbor]

                # Clearance and physical constraints verification
                if edge_data["max_height"] < vehicle_height:
                    continue  # Height barrier / underpass too low
                if edge_data["max_weight"] < vehicle_weight:
                    continue  # Bridge load limit exceeded
                if edge_data["width"] < vehicle_width:
                    continue  # Road alley too narrow

                tentative_g = g + edge_data["travel_time_seconds"]
                if tentative_g < g_scores.get(neighbor, float('inf')):
                    g_scores[neighbor] = tentative_g
                    
                    # Heuristic: optimistic direct travel time at max speed (100 km/h)
                    n_coords = self.nodes_data[neighbor]
                    euclid_dist = self.haversine_distance(n_coords["lat"], n_coords["lon"], dest_coords["lat"], dest_coords["lon"])
                    h = euclid_dist / (100.0 / 3.6)
                    
                    heapq.heappush(open_set, (tentative_g + h, neighbor, tentative_g, path + [neighbor]))

        return None
