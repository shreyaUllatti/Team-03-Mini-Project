import asyncio
from typing import List, Dict, Optional, Tuple
from app.algorithms.routing import RoutingEngine
from app.models.entities import Ambulance, Hospital, Incident, VehicleType, AmbulanceStatus, IncidentSeverity

class AmbulanceAllocator:
    """
    Intelligent Ambulance Dispatch & Allocation Engine:
    Handles multi-criteria vehicle scoring:
    - Match severity with capability (CRITICAL -> ALS or HELI, STANDARD -> BLS or FLYER)
    - Constrained travel time using live traffic routing
    - Nearest capable hospital selection with ICU capacity
    - Concurrency lock protection against double-dispatch
    """
    def __init__(self, routing_engine: RoutingEngine):
        self.routing_engine = routing_engine
        self._dispatch_lock = asyncio.Lock()

    async def find_optimal_ambulance_and_hospital(
        self,
        incident: Incident,
        available_ambulances: List[Ambulance],
        hospitals: List[Hospital]
    ) -> Optional[Tuple[Ambulance, Hospital, Dict, Dict]]:
        async with self._dispatch_lock:
            # 1. Filter ambulances that are strictly AVAILABLE
            candidates = [a for a in available_ambulances if a.status == AmbulanceStatus.AVAILABLE]
            if not candidates:
                return None

            # 2. Select Hospital with capacity matching incident severity
            viable_hospitals = [
                h for h in hospitals 
                if (h.icu_available > 0 if incident.severity == IncidentSeverity.CRITICAL else h.total_beds > 0)
            ]
            if not viable_hospitals:
                viable_hospitals = hospitals  # fallback to nearest if full

            best_ambulance = None
            best_hospital = None
            best_to_incident_route = None
            best_to_hospital_route = None
            min_score = float('inf')

            for amb in candidates:
                # Severity capability check
                severity_penalty = 0.0
                if incident.severity == IncidentSeverity.CRITICAL and amb.vehicle_type == VehicleType.RAPID_FLYER:
                    # Flyer cannot transport critical patient, only provide initial first responder stabilization
                    severity_penalty = 500.0
                elif incident.severity == IncidentSeverity.CRITICAL and amb.vehicle_type == VehicleType.BLS:
                    severity_penalty = 120.0 # ALS strongly preferred for critical

                # Calculate constrained route to incident
                amb_node = amb.current_node_id or self.routing_engine.find_nearest_node(amb.latitude, amb.longitude)
                inc_node = incident.nearest_node_id or self.routing_engine.find_nearest_node(incident.latitude, incident.longitude)

                if not amb_node or not inc_node:
                    continue

                route_to_inc = self.routing_engine.find_constrained_route(
                    start_node=amb_node,
                    end_node=inc_node,
                    vehicle_height=amb.height_meters,
                    vehicle_weight=amb.weight_tons,
                    vehicle_width=amb.width_meters
                )

                if not route_to_inc:
                    # Ambulance cannot physically navigate clearance restrictions to incident
                    continue

                # Find best hospital from incident
                for hosp in viable_hospitals:
                    hosp_node = hosp.nearest_node_id or self.routing_engine.find_nearest_node(hosp.latitude, hosp.longitude)
                    route_to_hosp = self.routing_engine.find_constrained_route(
                        start_node=inc_node,
                        end_node=hosp_node,
                        vehicle_height=amb.height_meters,
                        vehicle_weight=amb.weight_tons,
                        vehicle_width=amb.width_meters
                    )

                    if not route_to_hosp:
                        continue

                    # Total Response Cost: Time to scene + (0.5 * Time to hospital) + Severity mismatch
                    total_time = route_to_inc["total_duration_seconds"] + (route_to_hosp["total_duration_seconds"] * 0.5)
                    composite_score = total_time + severity_penalty

                    if composite_score < min_score:
                        min_score = composite_score
                        best_ambulance = amb
                        best_hospital = hosp
                        best_to_incident_route = route_to_inc
                        best_to_hospital_route = route_to_hosp

            if best_ambulance and best_hospital:
                # Atomically flag ambulance as DISPATCHED inside the lock
                best_ambulance.status = AmbulanceStatus.DISPATCHED
                best_hospital.icu_available = max(0, best_hospital.icu_available - 1)
                return best_ambulance, best_hospital, best_to_incident_route, best_to_hospital_route

            return None
