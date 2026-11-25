-- ============================================================================
-- 07_emergency_routing.sql — IERS
-- Shortest path using recursive CTE (depth-limited, safe for PG17)
-- ============================================================================
SET search_path TO iers, public;

CREATE OR REPLACE FUNCTION iers.find_shortest_path(
    p_start_node TEXT,
    p_end_node   TEXT,
    p_max_hops   INT DEFAULT 25
)
RETURNS TABLE(
    step_no    INT,
    node_id    TEXT,
    cum_cost_s FLOAT,
    cum_dist_m FLOAT
)
LANGUAGE SQL STABLE AS $$
    WITH RECURSIVE path_search(
        current_node, cum_cost, cum_dist, visited, depth
    ) AS (
        SELECT
            p_start_node::TEXT,
            0.0::FLOAT,
            0.0::FLOAT,
            ARRAY[p_start_node::TEXT],
            0
        UNION ALL
        SELECT
            e.target_id,
            ps.cum_cost + COALESCE(e.cost_seconds, 10.0),
            ps.cum_dist + COALESCE(e.distance_meters, 50.0),
            ps.visited || e.target_id,
            ps.depth + 1
        FROM path_search ps
        JOIN iers.road_network_edges e ON e.source_id = ps.current_node
        WHERE NOT e.target_id = ANY(ps.visited)
          AND ps.depth < p_max_hops
    ),
    best_path AS (
        SELECT visited, cum_cost, cum_dist
        FROM path_search
        WHERE current_node = p_end_node
        ORDER BY cum_cost
        LIMIT 1
    )
    SELECT
        ordinality::INT        AS step_no,
        node_val               AS node_id,
        ROUND(bp.cum_cost::numeric, 2)::FLOAT AS cum_cost_s,
        ROUND(bp.cum_dist::numeric, 2)::FLOAT AS cum_dist_m
    FROM best_path bp,
         LATERAL unnest(bp.visited) WITH ORDINALITY AS t(node_val, ordinality)
    ORDER BY ordinality;
$$;

-- Verify
SELECT proname, pronargs FROM pg_proc
WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname='iers')
  AND proname = 'find_shortest_path';

-- Quick smoke test
SELECT COUNT(*) AS path_hops,
       MAX(cum_cost_s) AS total_cost_s,
       MAX(cum_dist_m) AS total_dist_m
FROM iers.find_shortest_path('NODE_567', 'NODE_473', 25);
