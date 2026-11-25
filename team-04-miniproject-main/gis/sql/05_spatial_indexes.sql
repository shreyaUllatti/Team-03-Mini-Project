-- ============================================================================
-- 05_spatial_indexes.sql — IERS
-- GiST spatial indexes on all iers schema geometry columns
-- ============================================================================
SET search_path TO iers, public;

CREATE INDEX IF NOT EXISTS iers_idx_nodes_geom   ON iers.road_network_nodes USING GIST(geom);
CREATE INDEX IF NOT EXISTS iers_idx_edges_geom   ON iers.road_network_edges USING GIST(geom);
CREATE INDEX IF NOT EXISTS iers_idx_hosp_geom    ON iers.hospitals           USING GIST(geom);
CREATE INDEX IF NOT EXISTS iers_idx_amb_geom     ON iers.ambulances          USING GIST(geom);
CREATE INDEX IF NOT EXISTS iers_idx_inc_geom     ON iers.incidents           USING GIST(geom);
CREATE INDEX IF NOT EXISTS iers_idx_vert_geom    ON iers.vertices_map        USING GIST(geom);

ANALYZE iers.road_network_nodes;
ANALYZE iers.road_network_edges;
ANALYZE iers.hospitals;
ANALYZE iers.ambulances;
ANALYZE iers.vertices_map;

-- Verify
SELECT schemaname, tablename, indexname
FROM pg_indexes
WHERE schemaname = 'iers' AND indexname LIKE 'iers_idx%'
ORDER BY tablename;
