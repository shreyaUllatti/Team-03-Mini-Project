-- ============================================================================
-- IERS Migration 013: Unify Backend Persistence onto emergency_db (public)
-- Target: localhost:5432 / emergency_db / schema: public
-- Non-destructive: preserves all 40,394 public.roads & 29,385 public.road_nodes
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Enrich public.roads with directionality, emergency contraflow & clearance
ALTER TABLE public.roads
    ADD COLUMN IF NOT EXISTS is_oneway BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS emergency_contraflow_allowed BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_emergency_corridor BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS max_height_m DOUBLE PRECISION DEFAULT 4.5,
    ADD COLUMN IF NOT EXISTS max_width_m DOUBLE PRECISION DEFAULT 6.0,
    ADD COLUMN IF NOT EXISTS max_weight_t DOUBLE PRECISION DEFAULT 25.0;

UPDATE public.roads
SET is_oneway = (
    reverse_cost < 0
    OR (other_tags IS NOT NULL AND (other_tags::hstore)->'oneway' IN ('yes', '1', 'true'))
);

UPDATE public.roads
SET emergency_contraflow_allowed = (
    is_oneway = TRUE
    AND highway IN ('secondary', 'tertiary', 'residential', 'unclassified', 'service')
    AND COALESCE((other_tags::hstore)->'dual_carriageway', 'no') <> 'yes'
    AND COALESCE((other_tags::hstore)->'expressway', 'no') <> 'yes'
    AND COALESCE((other_tags::hstore)->'bridge', 'no') <> 'yes'
);

UPDATE public.roads
SET travel_time_s = GREATEST(COALESCE(travel_time_s, distance_m / GREATEST(COALESCE(speed_limit, 25.0) * 1000.0 / 3600.0, 1.0)), 0.5),
    traffic_multiplier = COALESCE(traffic_multiplier, 1.0),
    current_travel_time_s = GREATEST(COALESCE(travel_time_s, 1.0) * COALESCE(traffic_multiplier, 1.0), 0.5);

CREATE INDEX IF NOT EXISTS idx_pub_roads_geom ON public.roads USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_pub_roads_oneway ON public.roads (is_oneway);
CREATE INDEX IF NOT EXISTS idx_pub_roads_blocked ON public.roads (is_blocked);
CREATE INDEX IF NOT EXISTS idx_pub_road_nodes_loc ON public.road_nodes USING GIST (location);

-- 2. Extend public.users for 4 stakeholder roles
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS assigned_entity_id TEXT,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE public.users ADD CONSTRAINT users_role_check
    CHECK (role IN ('CITIZEN', 'DISPATCHER', 'HOSPITAL_STAFF', 'AMBULANCE_OPERATOR'));

-- 3. Extend public.hospitals (preserving UUID PK & location geometry)
ALTER TABLE public.hospitals
    ADD COLUMN IF NOT EXISTS hospital_code TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS total_beds INTEGER DEFAULT 120,
    ADD COLUMN IF NOT EXISTS icu_available INTEGER DEFAULT 10,
    ADD COLUMN IF NOT EXISTS trauma_beds_available INTEGER DEFAULT 8,
    ADD COLUMN IF NOT EXISTS emergency_dept_capacity INTEGER DEFAULT 20,
    ADD COLUMN IF NOT EXISTS trauma_level INTEGER DEFAULT 2,
    ADD COLUMN IF NOT EXISTS has_helipad BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS nearest_node_id TEXT,
    ADD COLUMN IF NOT EXISTS osm_id TEXT,
    ADD COLUMN IF NOT EXISTS city TEXT DEFAULT 'Hubballi',
    ADD COLUMN IF NOT EXISTS service_status TEXT DEFAULT 'OPERATIONAL',
    ADD COLUMN IF NOT EXISTS service_notes TEXT DEFAULT '';

-- 4. Extend public.ambulances (preserving UUID PK & current_location geometry)
ALTER TABLE public.ambulances DROP CONSTRAINT IF EXISTS ambulances_status_check;
ALTER TABLE public.ambulances DROP CONSTRAINT IF EXISTS ambulances_ambulance_type_check;
ALTER TABLE public.ambulances
    ADD COLUMN IF NOT EXISTS ambulance_code TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS call_sign TEXT,
    ADD COLUMN IF NOT EXISTS vehicle_type TEXT DEFAULT 'ALS',
    ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS current_node_id TEXT,
    ADD COLUMN IF NOT EXISTS height_meters DOUBLE PRECISION DEFAULT 2.4,
    ADD COLUMN IF NOT EXISTS width_meters DOUBLE PRECISION DEFAULT 2.2,
    ADD COLUMN IF NOT EXISTS weight_tons DOUBLE PRECISION DEFAULT 3.5,
    ADD COLUMN IF NOT EXISTS driver_name TEXT DEFAULT 'Paramedic Crew',
    ADD COLUMN IF NOT EXISTS fuel_percent DOUBLE PRECISION DEFAULT 100.0,
    ADD COLUMN IF NOT EXISTS unavailability_reason TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS current_speed_kmh DOUBLE PRECISION DEFAULT 0.0;

-- 5. Extend public.emergencies (preserving UUID PK & location geometry)
ALTER TABLE public.emergencies DROP CONSTRAINT IF EXISTS emergencies_status_check;
ALTER TABLE public.emergencies
    ADD COLUMN IF NOT EXISTS incident_code TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS caller_name TEXT DEFAULT 'Emergency Caller',
    ADD COLUMN IF NOT EXISTS caller_phone TEXT DEFAULT '112',
    ADD COLUMN IF NOT EXISTS reported_by_email TEXT,
    ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS nearest_node_id TEXT,
    ADD COLUMN IF NOT EXISTS assigned_ambulance_id UUID REFERENCES public.ambulances(ambulance_id),
    ADD COLUMN IF NOT EXISTS target_hospital_id UUID REFERENCES public.hospitals(hospital_id),
    ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS location_source TEXT DEFAULT 'MANUAL_PIN',
    ADD COLUMN IF NOT EXISTS active_leg TEXT DEFAULT 'LEG_1',
    ADD COLUMN IF NOT EXISTS active_route_json JSONB,
    ADD COLUMN IF NOT EXISTS eta_seconds INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS remaining_distance_m DOUBLE PRECISION DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS override_reason TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'NONE',
    ADD COLUMN IF NOT EXISTS verified_by TEXT,
    ADD COLUMN IF NOT EXISTS verification_notes TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;

-- 6. Extend public.emergency_events to allow email/actor string alongside changed_by UUID
ALTER TABLE public.emergency_events
    ADD COLUMN IF NOT EXISTS changed_by_email TEXT;

-- 7. Supporting audit & workflow tables in public schema
CREATE TABLE IF NOT EXISTS public.hospital_capacity_history (
    history_id SERIAL PRIMARY KEY,
    hospital_id UUID NOT NULL REFERENCES public.hospitals(hospital_id) ON DELETE CASCADE,
    changed_by TEXT NOT NULL,
    total_beds INTEGER,
    icu_available INTEGER,
    trauma_beds_available INTEGER,
    emergency_dept_capacity INTEGER,
    service_status TEXT,
    remarks TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.hospital_csv_imports (
    import_id TEXT PRIMARY KEY,
    hospital_id UUID NOT NULL REFERENCES public.hospitals(hospital_id) ON DELETE CASCADE,
    uploaded_by TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    import_mode TEXT NOT NULL,
    total_rows INTEGER NOT NULL DEFAULT 0,
    successful_rows INTEGER NOT NULL DEFAULT 0,
    failed_rows INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'COMPLETED',
    error_summary JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.ambulance_location_history (
    loc_id SERIAL PRIMARY KEY,
    ambulance_id UUID NOT NULL REFERENCES public.ambulances(ambulance_id) ON DELETE CASCADE,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    speed_kmh DOUBLE PRECISION DEFAULT 0.0,
    bearing_deg DOUBLE PRECISION DEFAULT 0.0,
    is_simulated BOOLEAN DEFAULT TRUE,
    geom GEOMETRY(Point, 4326),
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.complaints (
    complaint_id TEXT PRIMARY KEY,
    emergency_id UUID REFERENCES public.emergencies(emergency_id) ON DELETE SET NULL,
    submitted_by TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'RESPONSE_DELAY',
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'IN_REVIEW', 'RESOLVED')),
    dispatcher_response TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
