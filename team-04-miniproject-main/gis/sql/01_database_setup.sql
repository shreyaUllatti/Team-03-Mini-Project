-- ============================================================================
-- 01_database_setup.sql
-- Intelligent Emergency Response System (IERS)
-- Target: iers_db on iers-postgis container (port 5434)
-- Owner: iers_user  —  completely independent from GeoPilot
-- ============================================================================

-- Enable required extensions in iers_db
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

-- Create IERS schema namespace (all IERS GIS objects live here)
CREATE SCHEMA IF NOT EXISTS iers AUTHORIZATION iers_user;

-- Verify
SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis','postgis_topology');
SELECT current_database() AS db, current_user AS usr;
