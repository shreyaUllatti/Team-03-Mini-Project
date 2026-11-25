-- ============================================================================
-- IERS Migration 014: Giant Component Tagging, Expanded Hospital Metadata,
--                     and 28-Unit Simulated Metropolitan Fleet Support
-- Target: localhost:5432 / emergency_db / schema: public
-- ============================================================================

-- 1. Tag giant-component vertices on public.road_nodes using pgr_connectedComponents
ALTER TABLE public.road_nodes
    ADD COLUMN IF NOT EXISTS in_giant_component BOOLEAN DEFAULT FALSE;

WITH comps AS (
    SELECT node, component, COUNT(*) OVER (PARTITION BY component) AS comp_size
    FROM pgr_connectedComponents(
        'SELECT road_id AS id, source, target, current_travel_time_s AS cost, current_travel_time_s AS reverse_cost FROM public.roads WHERE NOT is_blocked'
    )
),
giant AS (
    SELECT node FROM comps WHERE comp_size = (SELECT MAX(comp_size) FROM comps)
)
UPDATE public.road_nodes n
SET in_giant_component = (n.node_id IN (SELECT node FROM giant));

CREATE INDEX IF NOT EXISTS idx_pub_road_nodes_giant ON public.road_nodes (in_giant_component);

-- 2. Enrich public.hospitals with full provenance & verification metadata
ALTER TABLE public.hospitals
    ADD COLUMN IF NOT EXISTS address TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS locality TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'Private',
    ADD COLUMN IF NOT EXISTS specialties TEXT DEFAULT 'General Medicine',
    ADD COLUMN IF NOT EXISTS data_source TEXT DEFAULT 'OpenStreetMap (ODbL)',
    ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'NEEDS_VERIFICATION';

-- 3. Enrich public.ambulances with demo/simulated labeling & operational base
ALTER TABLE public.ambulances
    ADD COLUMN IF NOT EXISTS is_simulated BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS operational_base TEXT DEFAULT 'Hubballi Central';
