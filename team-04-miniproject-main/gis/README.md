# Intelligent Emergency Response System (IERS) — GIS & PostGIS Layer

This documentation outlines the spatial database architecture, PostGIS integration, SQL analysis scripts, and QGIS demonstration setup for academic presentation and university professor evaluation.

---

## 1. System Architecture & Independent Container Isolation

The IERS GIS subsystem is completely decoupled from any other project (including GeoPilot):

```
┌────────────────────────────────────────────────────────┐
│           QGIS 3.44+ & SaaS Operations Web UI          │
│   (Carto Dark Matter, Real-Time Polylines, Layers)     │
└──────────────────────────┬─────────────────────────────┘
                           │ GeoJSON / REST / WebSocket / QGIS PostGIS Provider
┌──────────────────────────▼─────────────────────────────┐
│          FastAPI Spatial Backend (Port 8000)           │
│  (SQLAlchemy AsyncPG, RoutingEngine, Dispatch Lock)    │
└──────────────────────────┬─────────────────────────────┘
                           │ AsyncPG Pool (search_path = iers, public)
┌──────────────────────────▼─────────────────────────────┐
│       IERS Dedicated Container: iers-postgis           │
│  (PostgreSQL 17.5 + PostGIS 3.5.2, Host Port: 5434)    │
│  Database: iers_db | User: iers_user | Schema: iers    │
│  Volume: iers_postgis_data (Zero coupling to GeoPilot) │
│  (1,282 Nodes, 2,267 Segments, 6 GiST Indexes)        │
└────────────────────────────────────────────────────────┘
```

---

## 2. Spatial Schema & Geometry Specification

- **Host Port**: `5434` (mapped to container port `5432` to avoid clashes with default `5432` or GeoPilot `5433`).
- **Database**: `iers_db`
- **Schema**: `iers`
- **User**: `iers_user`
- **Spatial Reference System (SRID)**: `EPSG:4326` (WGS 84).
- **Network Dimensions**:
  - Intersections (`iers.road_network_nodes`): **1,282** topological intersections ($100\%$ valid geometry).
  - Segments (`iers.road_network_edges`): **2,267** road edges with physical clearance constraints (`max_height_meters`, `max_weight_tons`, `width_meters`).
  - Total road length: **67.21 km** (Average edge length: $29.65\text{ m}$).
  - Bounding Box: `POLYGON((75.100067 15.351769, 75.132646 15.390631))` (Hubballi-Dharwad metropolitan campus corridor).

---

## 3. SQL Pipeline Execution Guide

The modular SQL scripts located in `gis/sql/` execute against `iers_db`:

```powershell
# Execute against the dedicated IERS container:
Get-Content gis/sql/01_database_setup.sql    | docker exec -i iers-postgis psql -U iers_user -d iers_db
Get-Content gis/sql/02_schema_setup.sql      | docker exec -i iers-postgis psql -U iers_user -d iers_db
Get-Content gis/sql/03_road_network.sql      | docker exec -i iers-postgis psql -U iers_user -d iers_db
Get-Content gis/sql/04_topology_generation.sql| docker exec -i iers-postgis psql -U iers_user -d iers_db
Get-Content gis/sql/05_spatial_indexes.sql   | docker exec -i iers-postgis psql -U iers_user -d iers_db
Get-Content gis/sql/06_network_analysis.sql  | docker exec -i iers-postgis psql -U iers_user -d iers_db
Get-Content gis/sql/07_emergency_routing.sql | docker exec -i iers-postgis psql -U iers_user -d iers_db
Get-Content gis/sql/08_validation.sql        | docker exec -i iers-postgis psql -U iers_user -d iers_db
```

---

## 4. QGIS 3.44+ Demonstration Setup

The QGIS project is pre-configured and ready to load:
- Project Archive: `gis/qgis/Intelligent_Emergency_Response.qgz`
- XML Project File: `gis/qgis/Intelligent_Emergency_Response.qgs`

### Layers Configured in Project:
1. **Hospital 500m Service Buffer**: PostGIS view `iers.v_hospital_coverage_500m` (polygon overlay with translucent dashed perimeter).
2. **Road Network Edges**: PostGIS table `iers.road_network_edges` (2,267 segments, categorized by priority emergency corridor vs. standard arterial).
3. **Road Network Intersections**: PostGIS table `iers.road_network_nodes` (1,282 nodes).
4. **Hospitals & Trauma Hubs**: PostGIS table `iers.hospitals` (red medical cross symbology).
5. **Emergency Fleet Units**: PostGIS table `iers.ambulances` (categorized by ALS, BLS, and Rapid Flyer).
6. **Campus Boundary**: `gis/data/kle_campus.gpkg` (geographic spatial context).

### Direct QGIS Connection Parameters:
- **Host**: `localhost`
- **Port**: `5434`
- **Database**: `iers_db`
- **User**: `iers_user`
- **Password**: `iers_dev_local`
- **Schema**: `iers`
- **SSL Mode**: `disable`

---

## 5. Live FastAPI Endpoints

- `GET /api/v1/system/database-info` — Real-time database connection diagnostics proving active PostGIS database (`sqlite_in_use: false`).
- `GET /api/v1/hospitals` — Returns hospital assets with ICU capacity and PostGIS geometry.
- `GET /api/v1/ambulances` — Returns emergency response fleet with clearance specs.
- `POST /api/v1/routing/calculate` — Computes vehicle clearance routing cross-checked with PostGIS `iers.find_shortest_path`.
- `POST /api/v1/incidents/create` — Atomic multi-criteria dispatch persisted in PostGIS.
