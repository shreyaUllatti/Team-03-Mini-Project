-- ============================================================================
-- IERS Migration 012: Complaints, Two-Leg Routing, Dispatcher Verification
-- Non-destructive: preserves all existing tables, roads, nodes, hospitals
-- ============================================================================

ALTER TABLE iers.incidents
    ADD COLUMN IF NOT EXISTS override_reason TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS active_leg TEXT DEFAULT 'LEG_1',
    ADD COLUMN IF NOT EXISTS active_route_json JSONB,
    ADD COLUMN IF NOT EXISTS eta_seconds INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS remaining_distance_m DOUBLE PRECISION DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS handover_confirmed_by TEXT,
    ADD COLUMN IF NOT EXISTS handover_confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'NONE',
    ADD COLUMN IF NOT EXISTS verified_by TEXT,
    ADD COLUMN IF NOT EXISTS verification_notes TEXT DEFAULT '';

CREATE TABLE IF NOT EXISTS iers.complaints (
    complaint_id TEXT PRIMARY KEY,
    incident_id TEXT REFERENCES iers.incidents(incident_id) ON DELETE SET NULL,
    submitted_by TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'RESPONSE_DELAY',
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'IN_REVIEW', 'RESOLVED')),
    dispatcher_response TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_iers_complaints_sub ON iers.complaints (submitted_by, created_at DESC);
