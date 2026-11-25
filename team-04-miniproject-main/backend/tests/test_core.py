import pytest
import asyncio
from app.algorithms.routing import RoutingEngine
from app.simulation.traffic import TrafficSimulationEngine
from app.services.dispatch import AmbulanceAllocator
from app.services.gis_loader import load_gis_network_into_engine
from app.models.entities import Ambulance, Hospital, Incident, VehicleType, AmbulanceStatus, IncidentSeverity

TEST_BENCHMARK_NETWORK = {
    "nodes": [
        {"id": "N_CENTRAL", "name": "City Center Junction", "lat": 59.3293, "lon": 18.0686},
        {"id": "N_NORTH", "name": "North Gate Expressway", "lat": 59.3450, "lon": 18.0550},
        {"id": "N_SOUTH", "name": "South Farsta Interchange", "lat": 59.2428, "lon": 18.0922},
        {"id": "N_OLD_TOWN", "name": "Historic Old Town Pass", "lat": 59.3250, "lon": 18.0710},
        {"id": "N_LOW_BRIDGE", "name": "Canal Low Bridge Arch", "lat": 59.3150, "lon": 18.0800},
        {"id": "N_HOSPITAL_A", "name": "Karolinska Medical Center Access", "lat": 59.3510, "lon": 18.0320},
        {"id": "N_HOSPITAL_B", "name": "Södersjukhuset Trauma Hub Access", "lat": 59.3100, "lon": 18.0580},
        {"id": "N_SKONDAL", "name": "Sköndal Highway Node", "lat": 59.2550, "lon": 18.1100}
    ],
    "edges": [
        {"id": "E_N_C", "source": "N_NORTH", "target": "N_CENTRAL", "name": "Sveavägen Blvd", "distance": 2200.0, "speed": 60.0, "height": 5.0, "weight": 40.0, "width": 8.0},
        {"id": "E_C_N", "source": "N_CENTRAL", "target": "N_NORTH", "name": "Sveavägen Blvd", "distance": 2200.0, "speed": 60.0, "height": 5.0, "weight": 40.0, "width": 8.0},
        {"id": "E_N_HA", "source": "N_NORTH", "target": "N_HOSPITAL_A", "name": "Solnavägen", "distance": 1500.0, "speed": 50.0, "height": 4.5, "weight": 30.0, "width": 7.0},
        {"id": "E_HA_N", "source": "N_HOSPITAL_A", "target": "N_NORTH", "name": "Solnavägen", "distance": 1500.0, "speed": 50.0, "height": 4.5, "weight": 30.0, "width": 7.0},
        {"id": "E_C_OT", "source": "N_CENTRAL", "target": "N_OLD_TOWN", "name": "Gamla Stan Cobblestone Alley", "distance": 800.0, "speed": 25.0, "height": 3.2, "weight": 4.0, "width": 2.4},
        {"id": "E_OT_C", "source": "N_OLD_TOWN", "target": "N_CENTRAL", "name": "Gamla Stan Cobblestone Alley", "distance": 800.0, "speed": 25.0, "height": 3.2, "weight": 4.0, "width": 2.4},
        {"id": "E_OT_LB", "source": "N_OLD_TOWN", "target": "N_LOW_BRIDGE", "name": "Canal Arch Overpass", "distance": 1200.0, "speed": 40.0, "height": 2.7, "weight": 8.0, "width": 6.0},
        {"id": "E_LB_OT", "source": "N_LOW_BRIDGE", "target": "N_OLD_TOWN", "name": "Canal Arch Overpass", "distance": 1200.0, "speed": 40.0, "height": 2.7, "weight": 8.0, "width": 6.0},
        {"id": "E_C_HB", "source": "N_CENTRAL", "target": "N_HOSPITAL_B", "name": "Söderledstunneln Highway", "distance": 2400.0, "speed": 70.0, "height": 4.5, "weight": 35.0, "width": 8.0},
        {"id": "E_HB_C", "source": "N_HOSPITAL_B", "target": "N_CENTRAL", "name": "Söderledstunneln Highway", "distance": 2400.0, "speed": 70.0, "height": 4.5, "weight": 35.0, "width": 8.0},
        {"id": "E_HB_SK", "source": "N_HOSPITAL_B", "target": "N_SKONDAL", "name": "Route 73 Arterial", "distance": 4500.0, "speed": 80.0, "height": 4.8, "weight": 40.0, "width": 8.5},
        {"id": "E_SK_HB", "source": "N_SKONDAL", "target": "N_HOSPITAL_B", "name": "Route 73 Arterial", "distance": 4500.0, "speed": 80.0, "height": 4.8, "weight": 40.0, "width": 8.5},
        {"id": "E_SK_S", "source": "N_SKONDAL", "target": "N_SOUTH", "name": "Farstavägen Corridor", "distance": 2100.0, "speed": 60.0, "height": 4.5, "weight": 30.0, "width": 7.0},
        {"id": "E_S_SK", "source": "N_SOUTH", "target": "N_SKONDAL", "name": "Farstavägen Corridor", "distance": 2100.0, "speed": 60.0, "height": 4.5, "weight": 30.0, "width": 7.0},
        {"id": "E_LB_HB", "source": "N_LOW_BRIDGE", "target": "N_HOSPITAL_B", "name": "Ringvägen Connector", "distance": 1100.0, "speed": 50.0, "height": 4.2, "weight": 20.0, "width": 6.5},
        {"id": "E_HB_LB", "source": "N_HOSPITAL_B", "target": "N_LOW_BRIDGE", "name": "Ringvägen Connector", "distance": 1100.0, "speed": 50.0, "height": 4.2, "weight": 20.0, "width": 6.5}
    ]
}

@pytest.fixture
def setup_engine():
    engine = RoutingEngine()
    load_gis_network_into_engine(engine, TEST_BENCHMARK_NETWORK)
    return engine

def test_gis_network_loaded(setup_engine):
    assert len(setup_engine.nodes_data) == 8
    assert len(setup_engine.edges_data) == 16

def test_constrained_routing_underpass_height_rejection(setup_engine):
    """
    Test that a tall vehicle (height 3.5m) is blocked from taking the Canal Arch Overpass (max_height 2.7m),
    while a standard vehicle (height 2.2m) passes successfully.
    """
    # Route from Old Town to Low Bridge
    route_tall = setup_engine.find_constrained_route(
        start_node="N_OLD_TOWN",
        end_node="N_LOW_BRIDGE",
        vehicle_height=3.5, # Exceeds 2.7m limit
        vehicle_weight=3.0,
        vehicle_width=2.0
    )
    assert route_tall is None, "Tall vehicle should be rejected due to low bridge clearance"

    route_standard = setup_engine.find_constrained_route(
        start_node="N_OLD_TOWN",
        end_node="N_LOW_BRIDGE",
        vehicle_height=2.2, # Fits under 2.7m limit
        vehicle_weight=3.0,
        vehicle_width=2.0
    )
    assert route_standard is not None, "Standard vehicle should successfully pass"
    assert "N_LOW_BRIDGE" in route_standard["path_nodes"]

def test_constrained_routing_narrow_alley(setup_engine):
    """
    Test that a wide vehicle cannot take the direct narrow alley (E_C_OT),
    and must either take an alternate detour or fail when detour constraints also block it.
    """
    # Direct edge is blocked for width 2.8m (alley width is 2.4m)
    # The A* engine intelligently reroutes around through N_HOSPITAL_B and N_LOW_BRIDGE!
    route_wide = setup_engine.find_constrained_route(
        start_node="N_CENTRAL",
        end_node="N_OLD_TOWN",
        vehicle_height=2.5,
        vehicle_weight=3.0,
        vehicle_width=2.8 # Exceeds 2.4m direct alley width
    )
    # Verify the algorithm avoided the narrow cobblestone alley
    assert "E_C_OT" not in [s.get("from") for s in route_wide["segments"] if s.get("road_name") == "Gamla Stan Cobblestone Alley"]
    assert route_wide["segments"][0]["road_name"] != "Gamla Stan Cobblestone Alley"
    assert "N_HOSPITAL_B" in route_wide["path_nodes"], "Wide vehicle successfully took detour around narrow alley"

    # Now test an oversized vehicle that cannot take the alley AND cannot fit under the low bridge detour (height > 2.7m)
    route_oversized = setup_engine.find_constrained_route(
        start_node="N_CENTRAL",
        end_node="N_OLD_TOWN",
        vehicle_height=3.5, # Exceeds 2.7m bridge
        vehicle_weight=3.0,
        vehicle_width=2.8   # Exceeds 2.4m alley
    )
    assert route_oversized is None, "Oversized vehicle blocked on both primary alley and bridge detour"

@pytest.mark.asyncio
async def test_traffic_emergency_corridor_relief(setup_engine):
    """
    Test that activating an emergency priority lane mitigates congestion penalties.
    """
    sim = TrafficSimulationEngine(setup_engine)
    sim.update_edge_congestion("N_NORTH", "N_CENTRAL", 3.0)
    congested_time = setup_engine.graph["N_NORTH"]["N_CENTRAL"]["travel_time_seconds"]

    # Toggle green corridor
    sim.toggle_emergency_corridor("N_NORTH", "N_CENTRAL", True)
    corridor_time = setup_engine.graph["N_NORTH"]["N_CENTRAL"]["travel_time_seconds"]

    assert corridor_time < congested_time
    assert setup_engine.graph["N_NORTH"]["N_CENTRAL"]["is_emergency_lane"] is True

@pytest.mark.asyncio
async def test_dispatch_concurrency_lock(setup_engine):
    """
    Test that concurrent dispatch attempts on a single available ambulance
    cannot result in a double-dispatch race condition.
    """
    allocator = AmbulanceAllocator(setup_engine)

    amb = Ambulance(
        id="AMB_SINGLE",
        call_sign="SOLO-1",
        vehicle_type=VehicleType.BLS,
        status=AmbulanceStatus.AVAILABLE,
        height_meters=2.4,
        weight_tons=3.5,
        width_meters=2.2,
        latitude=59.3293,
        longitude=18.0686,
        current_node_id="N_CENTRAL"
    )

    hosp = Hospital(
        id="H_TEST",
        name="Emergency Hospital",
        latitude=59.3510,
        longitude=18.0320,
        nearest_node_id="N_HOSPITAL_A",
        total_beds=10,
        icu_available=5
    )

    inc1 = Incident(
        id="INC_1",
        severity=IncidentSeverity.CRITICAL,
        latitude=59.3450,
        longitude=18.0550,
        nearest_node_id="N_NORTH"
    )

    inc2 = Incident(
        id="INC_2",
        severity=IncidentSeverity.CRITICAL,
        latitude=59.3450,
        longitude=18.0550,
        nearest_node_id="N_NORTH"
    )

    # Dispatch concurrently
    res1, res2 = await asyncio.gather(
        allocator.find_optimal_ambulance_and_hospital(inc1, [amb], [hosp]),
        allocator.find_optimal_ambulance_and_hospital(inc2, [amb], [hosp])
    )

    # Exactly one dispatch succeeds; the second receives None because the ambulance is locked
    success_count = sum(1 for r in [res1, res2] if r is not None)
    assert success_count == 1
    assert amb.status == AmbulanceStatus.DISPATCHED
