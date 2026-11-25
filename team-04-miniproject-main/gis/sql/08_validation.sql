-- ============================================================================
-- 08_validation.sql — IERS
-- Verifies the entire iers_db GIS implementation
-- ============================================================================
SET search_path TO iers, public;

-- [1] Confirm database identity
SELECT current_database() AS database, current_user AS user_role,
       'IERS — independent from GeoPilot' AS project;

-- [2] SRID consistency check
SELECT f_table_schema, f_table_name, f_geometry_column, srid, type
FROM geometry_columns
WHERE f_table_schema = 'iers'
ORDER BY f_table_name;

-- [3] Geometry validity
SELECT tbl, total, valid, (total - valid) AS invalid FROM (
    SELECT 'road_network_nodes' AS tbl, COUNT(*) AS total,
           SUM(CASE WHEN ST_IsValid(geom) THEN 1 ELSE 0 END) AS valid
    FROM iers.road_network_nodes
    UNION ALL
    SELECT 'road_network_edges', COUNT(*),
           SUM(CASE WHEN ST_IsValid(geom) THEN 1 ELSE 0 END)
    FROM iers.road_network_edges WHERE geom IS NOT NULL
    UNION ALL
    SELECT 'hospitals', COUNT(*),
           SUM(CASE WHEN ST_IsValid(geom) THEN 1 ELSE 0 END)
    FROM iers.hospitals
    UNION ALL
    SELECT 'ambulances', COUNT(*),
           SUM(CASE WHEN ST_IsValid(geom) THEN 1 ELSE 0 END)
    FROM iers.ambulances
) sub ORDER BY tbl;

-- [4] Network bounding box
SELECT ST_AsText(ST_Envelope(ST_Collect(geom))) AS bounding_box
FROM iers.road_network_nodes;

-- [5] Spatial indexes
SELECT schemaname, tablename, indexname
FROM pg_indexes
WHERE schemaname = 'iers' AND indexname LIKE 'iers_idx%'
ORDER BY tablename;

-- [6] Network statistics
SELECT
    COUNT(*) AS total_edges,
    COUNT(DISTINCT source_id) AS distinct_sources,
    ROUND(AVG(distance_meters)::numeric, 2) AS avg_dist_m,
    ROUND(SUM(distance_meters/1000.0)::numeric, 2) AS total_road_km,
    ROUND(MAX(distance_meters)::numeric, 2) AS max_edge_m
FROM iers.road_network_edges;

-- [7] Nearest-node function test
SELECT * FROM iers.find_nearest_node(15.368637, 75.121066);  -- AMB-01 location
SELECT * FROM iers.find_nearest_node(15.369641, 75.123161);  -- KIMS

-- [8] Routing: NODE_567 → NODE_473 (ambulance to hospital)
WITH route AS (
    SELECT * FROM iers.find_shortest_path('NODE_567', 'NODE_473', 25)
)
SELECT
    COUNT(*) AS path_hops,
    MAX(cum_cost_s) AS total_cost_seconds,
    MAX(cum_dist_m) AS total_dist_meters
FROM route;
