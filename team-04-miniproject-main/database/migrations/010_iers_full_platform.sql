-- ============================================================================
-- IERS Migration 010: Metropolitan Routing Restrictions, RBAC, Events & History
-- Target: iers_db (PostgreSQL 17 + PostGIS 3.5 + pgRouting 3.7.3), schema: iers
-- Non-destructive: preserves all existing roads, nodes, and campus_reference.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;

-- 1. Enrich iers.roads with explicit directionality, emergency exceptions & clearance
ALTER TABLE iers.roads
    ADD COLUMN IF NOT EXISTS is_oneway BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS emergency_contraflow_allowed BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_emergency_corridor BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS max_height_m DOUBLE PRECISION DEFAULT 4.5,
    ADD COLUMN IF NOT EXISTS max_width_m DOUBLE PRECISION DEFAULT 6.0,
    ADD COLUMN IF NOT EXISTS max_weight_t DOUBLE PRECISION DEFAULT 25.0;

-- Populate directionality from real OSM other_tags / reverse_cost
UPDATE iers.roads
SET is_oneway = (
    reverse_cost < 0
    OR (other_tags IS NOT NULL AND (other_tags::hstore)->'oneway' IN ('yes', '1', 'true'))
);

-- Emergency contraflow exception:
-- Allowed on urban one-way streets (secondary, tertiary, residential, unclassified, service)
-- NOT allowed on divided dual carriageways, expressways, trunk/trunk_link highways, or bridges.
UPDATE iers.roads
SET emergency_contraflow_allowed = (
    is_oneway = TRUE
    AND highway IN ('secondary', 'tertiary', 'residential', 'unclassified', 'service')
    AND COALESCE((other_tags::hstore)->'dual_carriageway', 'no') <> 'yes'
    AND COALESCE((other_tags::hstore)->'expressway', 'no') <> 'yes'
    AND COALESCE((other_tags::hstore)->'bridge', 'no') <> 'yes'
);

-- Populate realistic road clearance defaults by highway class (respecting OSM maxheight if present)
UPDATE iers.roads
SET max_width_m = CASE
        WHEN highway IN ('trunk', 'primary') THEN 9.0
        WHEN highway IN ('secondary', 'trunk_link', 'primary_link') THEN 7.0
        WHEN highway IN ('tertiary', 'secondary_link', 'tertiary_link') THEN 5.5
        WHEN highway IN ('residential', 'unclassified') THEN 4.0
        ELSE 3.0
    END,
    max_weight_t = CASE
        WHEN highway IN ('trunk', 'primary', 'secondary') THEN 40.0
        WHEN highway IN ('tertiary', 'unclassified') THEN 20.0
        ELSE 10.0
    END;

-- Ensure current_travel_time_s is never NULL or <= 0
UPDATE iers.roads
SET travel_time_s = GREATEST(COALESCE(travel_time_s, distance_m / GREATEST(COALESCE(speed_limit, 25.0) * 1000.0 / 3600.0, 1.0)), 0.5),
    traffic_multiplier = COALESCE(traffic_multiplier, 1.0),
    current_travel_time_s = GREATEST(COALESCE(travel_time_s, 1.0) * COALESCE(traffic_multiplier, 1.0), 0.5);

CREATE INDEX IF NOT EXISTS idx_iers_roads_oneway ON iers.roads (is_oneway);
CREATE INDEX IF NOT EXISTS idx_iers_roads_blocked ON iers.roads (is_blocked);
CREATE INDEX IF NOT EXISTS idx_iers_roads_corridor ON iers.roads (is_emergency_corridor);

-- 2. Role-Based Users Table
CREATE TABLE IF NOT EXISTS iers.users (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('DISPATCHER', 'AMBULANCE_CREW', 'HOSPITAL_STAFF', 'ADMIN')),
    assigned_entity_id TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Enrich iers.hospitals for real OSM provenance & capabilities
ALTER TABLE iers.hospitals
    ADD COLUMN IF NOT EXISTS osm_id TEXT,
    ADD COLUMN IF NOT EXISTS has_icu BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS has_trauma_care BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS has_cardiology BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS contact_number TEXT DEFAULT '+91-836-2372200',
    ADD COLUMN IF NOT EXISTS city TEXT DEFAULT 'Hubballi',
    ADD COLUMN IF NOT EXISTS attributes_simulated BOOLEAN DEFAULT TRUE;

-- 4. Enrich iers.ambulances for capabilities & crew link
ALTER TABLE iers.ambulances
    ADD COLUMN IF NOT EXISTS registration_number TEXT,
    ADD COLUMN IF NOT EXISTS capabilities JSONB DEFAULT '["BLS","OXYGEN"]'::jsonb,
    ADD COLUMN IF NOT EXISTS assigned_user_id TEXT;

-- 5. Enrich iers.incidents for P1-P4 priority, human review, description
ALTER TABLE iers.incidents
    ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'P2' CHECK (priority IN ('P1', 'P2', 'P3', 'P4')),
    ADD COLUMN IF NOT EXISTS priority_score INTEGER DEFAULT 75,
    ADD COLUMN IF NOT EXISTS people_affected INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS description TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS reported_by TEXT,
    ADD COLUMN IF NOT EXISTS location_source TEXT DEFAULT 'MANUAL_PIN';

-- 6. Emergency Event Timeline (Audit log of every status transition)
CREATE TABLE IF NOT EXISTS iers.emergency_events (
    event_id SERIAL PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES iers.incidents(incident_id) ON DELETE CASCADE,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_by TEXT,
    remarks TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_iers_events_inc ON iers.emergency_events (incident_id, created_at DESC);

-- 7. Route History (Persisted real pgRouting calculations)
CREATE TABLE IF NOT EXISTS iers.route_history (
    route_id SERIAL PRIMARY KEY,
    incident_id TEXT,
    ambulance_id TEXT,
    algorithm TEXT NOT NULL CHECK (algorithm IN ('DIJKSTRA', 'ASTAR')),
    vehicle_mode TEXT NOT NULL CHECK (vehicle_mode IN ('AMBULANCE', 'NORMAL')),
    start_node BIGINT NOT NULL,
    end_node BIGINT NOT NULL,
    distance_m DOUBLE PRECISION NOT NULL,
    estimated_time_s DOUBLE PRECISION NOT NULL,
    contraflow_edges INTEGER DEFAULT 0,
    route_geom GEOMETRY(Geometry, 4326),
    calculated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_iers_route_hist_geom ON iers.route_history USING GIST (route_geom);
