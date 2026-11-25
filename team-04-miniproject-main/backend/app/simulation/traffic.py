import random
import asyncio
from typing import Dict, List, Optional, Tuple
from app.algorithms.routing import RoutingEngine

class TrafficSimulationEngine:
    def __init__(self, routing_engine: RoutingEngine):
        self.routing_engine = routing_engine
        self.incident_hotspots: List[str] = []
        self.is_running = False

    def update_edge_congestion(self, u: str, v: str, congestion_factor: float):
        """Dynamically modifies road travel times due to live traffic."""
        if self.routing_engine.graph.has_edge(u, v):
            edge = self.routing_engine.graph[u][v]
            edge["traffic_factor"] = round(congestion_factor, 2)
            
            effective = congestion_factor
            if edge.get("is_emergency_lane", False):
                effective = 1.0 + (congestion_factor - 1.0) * 0.4
            
            edge["effective_traffic"] = round(effective, 2)
            speed_ms = (edge["speed_limit_kmh"] / 3.6) / effective
            edge["travel_time_seconds"] = edge["distance_meters"] / max(speed_ms, 1.0)

    def trigger_rush_hour(self, bottleneck_edges: List[Tuple[str, str]]):
        """Simulate peak hour congestion on key arterial roads."""
        for u, v in bottleneck_edges:
            heavy_factor = random.uniform(2.5, 4.2)
            self.update_edge_congestion(u, v, heavy_factor)

    def clear_congestion(self, u: str, v: str):
        """Restore free flow traffic."""
        self.update_edge_congestion(u, v, 1.0)

    def toggle_emergency_corridor(self, u: str, v: str, active: bool):
        """Activates green corridor / priority lane."""
        if self.routing_engine.graph.has_edge(u, v):
            edge = self.routing_engine.graph[u][v]
            edge["is_emergency_lane"] = active
            self.update_edge_congestion(u, v, edge["traffic_factor"])
