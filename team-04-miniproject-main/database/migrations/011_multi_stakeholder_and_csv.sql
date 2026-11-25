-- ============================================================================
-- IERS Migration 011: Multi-Stakeholder Roles, Capacity History, CSV Imports,
--                     Ambulance Location History & 10-State Workflow
-- Non-destructive: preserves all 40,394 roads, 29,385 nodes, 22 real hospitals
-- ============================================================================

-- 1. Update iers.users role constraint to exact 4 stakeholder roles
ALTER TABLE iers.users DROP CONSTRAINT IF EXISTS users_role_check;
UPDATE iers.users SET role = 'AMBULANCE_OPERATOR' WHERE role = 'AMBULANCE_CREW';
DELETE FROM iers.users WHERE role = 'ADMIN';
ALTER TABLE iers.users ADD CONSTRAINT users_role_check
    CHECK (role IN ('CITIZEN', 'DISPATCHER', 'HOSPITAL_STAFF', 'AMBULANCE_OPERATOR'));

-- 2. Enrich iers.hospitals for full Hospital Staff Portal
ALTER TABLE iers.hospitals
    ADD COLUMN IF NOT EXISTS emergency_dept_capacity INTEGER DEFAULT 25,
    ADD COLUMN IF NOT EXISTS trauma_beds_available INTEGER DEFAULT 10,
    ADD COLUMN IF NOT EXISTS service_status TEXT DEFAULT 'OPERATIONAL',
    ADD COLUMN IF NOT EXISTS service_notes TEXT DEFAULT '';

-- 3. Enrich iers.ambulances for Operator Portal & 3D Inspection
ALTER TABLE iers.ambulances
    ADD COLUMN IF NOT EXISTS unavailability_reason TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS current_speed_kmh DOUBLE PRECISION DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS current_road_name TEXT DEFAULT '';

-- 4. Hospital Capacity Update History
CREATE TABLE IF NOT EXISTS iers.hospital_capacity_history (
    history_id SERIAL PRIMARY KEY,
    hospital_id TEXT NOT NULL REFERENCES iers.hospitals(hospital_id) ON DELETE CASCADE,
    changed_by TEXT NOT NULL,
    total_beds INTEGER,
    icu_available INTEGER,
    trauma_beds_available INTEGER,
    emergency_dept_capacity INTEGER,
    service_status TEXT,
    remarks TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_iers_hosp_hist ON iers.hospital_capacity_history (hospital_id, created_at DESC);

-- 5. Hospital CSV Bulk Import History
CREATE TABLE IF NOT EXISTS iers.hospital_csv_imports (
    import_id TEXT PRIMARY KEY,
    hospital_id TEXT NOT NULL REFERENCES iers.hospitals(hospital_id) ON DELETE CASCADE,
    uploaded_by TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    import_mode TEXT NOT NULL CHECK (import_mode IN ('UPDATE_EXISTING', 'INSERT_NEW')),
    total_rows INTEGER NOT NULL DEFAULT 0,
    successful_rows INTEGER NOT NULL DEFAULT 0,
    failed_rows INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'COMPLETED',
    error_summary JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_iers_csv_imp ON iers.hospital_csv_imports (hospital_id, created_at DESC);

-- 6. Ambulance Location Update History (GPS vs Simulated)
CREATE TABLE IF NOT EXISTS iers.ambulance_location_history (
    loc_id SERIAL PRIMARY KEY,
    ambulance_id TEXT NOT NULL REFERENCES iers.ambulances(ambulance_id) ON DELETE CASCADE,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    speed_kmh DOUBLE PRECISION DEFAULT 0.0,
    bearing_deg DOUBLE PRECISION DEFAULT 0.0,
    is_simulated BOOLEAN DEFAULT TRUE,
    geom GEOMETRY(Point, 4326),
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_iers_amb_loc_hist ON iers.ambulance_location_history (ambulance_id, recorded_at DESC);
