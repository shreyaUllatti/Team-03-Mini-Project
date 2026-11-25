-- ============================================================================
-- live_professor_demo.sql
-- Intelligent Emergency Response System (IERS)
-- Live Demonstration Script for University Faculty / Evaluation Committee
-- ============================================================================

\echo '----------------------------------------------------------------------------'
\echo 'DEMO STEP 1: Verifying PostGIS and pgRouting Capabilities'
\echo '----------------------------------------------------------------------------'
SELECT 
    postgis_lib_version() AS postgis,
    pgr_version() AS pgrouting;

\echo '----------------------------------------------------------------------------'
\echo 'DEMO STEP 2: Inspecting Spatial Topology & Road Network Dimensions'
\echo '----------------------------------------------------------------------------'
SELECT 
    COUNT(DISTINCT node_id) AS total_spatial_nodes,
    (SELECT COUNT(*) FROM emergency.road_network_edges) AS total_road_segments,
    (SELECT COUNT(*) FROM emergency.hospitals) AS trauma_centers,
    (SELECT COUNT(*) FROM emergency.ambulances) AS active_fleet_units
FROM emergency.road_network_nodes;

\echo '----------------------------------------------------------------------------'
\echo 'DEMO STEP 3: Sub-millisecond Spatial Proximity (K-Nearest Neighbors)'
\echo 'Finding closest road junction to emergency coordinate (15.3686° N, 75.1210° E)'
\echo '----------------------------------------------------------------------------'
SELECT * FROM emergency.find_nearest_node(75.121066, 15.368637);

\echo '----------------------------------------------------------------------------'
\echo 'DEMO STEP 4: Constrained Dijkstra Shortest Path (Physical Clearance Check)'
\echo 'Vehicle: ALS Intensive Care Ambulance (Height: 3.2m, Weight: 5.2t, Width: 2.6m)'
\echo 'Path from incident (NODE_567) to KIMS Trauma Hub (NODE_473)'
\echo '----------------------------------------------------------------------------'
SELECT 
    seq,
    node_id,
    road_name,
    ROUND(cost_seconds::numeric, 1) AS travel_time_sec,
    ROUND(distance_meters::numeric, 1) AS segment_distance_m
FROM emergency.calculate_constrained_route('NODE_567', 'NODE_473', 3.2, 5.2, 2.6);

\echo '----------------------------------------------------------------------------'
\echo 'DEMO STEP 5: Emergency Green Corridor Traffic Signal Preemption'
\echo 'Simulating priority corridor activation reducing congestion delay'
\echo '----------------------------------------------------------------------------'
SELECT 
    edge_id,
    road_name,
    current_traffic_factor,
    is_emergency_corridor,
    ROUND(cost_seconds::numeric, 1) AS travel_time_seconds
FROM emergency.road_network_edges
WHERE edge_id LIKE '%388062061%'
LIMIT 3;
