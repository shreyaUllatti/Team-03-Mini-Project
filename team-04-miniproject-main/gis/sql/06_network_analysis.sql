-- ============================================================================
-- 06_network_analysis.sql — IERS
-- Spatial functions and analysis views on iers_db
-- ============================================================================
SET search_path TO iers, public;

-- Function: find nearest network node to a lat/lon coordinate
CREATE OR REPLACE FUNCTION iers.find_nearest_node(p_lat FLOAT, p_lon FLOAT)
RETURNS TABLE(node_id TEXT, name TEXT, dist_m FLOAT)
LANGUAGE SQL STABLE AS $$
    SELECT n.node_id, n.name,
           ST_Distance(n.geom::GEOGRAPHY, ST_SetSRID(ST_MakePoint(p_lon, p_lat),4326)::GEOGRAPHY) AS dist_m
    FROM iers.road_network_nodes n
    ORDER BY n.geom <-> ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)
    LIMIT 1;
$$;

-- View: node degree centrality (how many edges connect to each node)
CREATE OR REPLACE VIEW iers.v_node_centrality AS
SELECT
    n.node_id,
    n.name,
    n.geom,
    COUNT(e.edge_id) AS degree
FROM iers.road_network_nodes n
LEFT JOIN iers.road_network_edges e
    ON e.source_id = n.node_id OR e.target_id = n.node_id
GROUP BY n.node_id, n.name, n.geom;

-- View: hospital 500m coverage zones
CREATE OR REPLACE VIEW iers.v_hospital_coverage_500m AS
SELECT
    h.hospital_id,
    h.name,
    ST_Buffer(h.geom::GEOGRAPHY, 500)::GEOMETRY AS coverage_geom
FROM iers.hospitals h;

-- Verify
SELECT proname FROM pg_proc WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname='iers') AND proname LIKE 'find_%';
SELECT viewname FROM pg_views WHERE schemaname = 'iers';
