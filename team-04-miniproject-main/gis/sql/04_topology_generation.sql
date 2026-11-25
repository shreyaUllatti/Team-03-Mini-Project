-- ============================================================================
-- 04_topology_generation.sql — IERS
-- Build vertices_map for topology/routing in iers_db
-- ============================================================================
SET search_path TO iers, public;

-- Populate vertices_map from road_network_nodes
INSERT INTO iers.vertices_map (node_id, geom)
SELECT node_id, geom FROM iers.road_network_nodes
ON CONFLICT (node_id) DO NOTHING;

-- Set source/target vertex IDs on edges from vertices_map
UPDATE iers.road_network_edges e
SET source_vertex_id = vm.vertex_id
FROM iers.vertices_map vm
WHERE vm.node_id = e.source_id;

UPDATE iers.road_network_edges e
SET target_vertex_id = vm.vertex_id
FROM iers.vertices_map vm
WHERE vm.node_id = e.target_id;

-- Verify
SELECT COUNT(*) AS vertices FROM iers.vertices_map;
SELECT COUNT(*) AS edges_resolved
FROM iers.road_network_edges
WHERE source_vertex_id IS NOT NULL AND target_vertex_id IS NOT NULL;
