# IERS — End-to-End Technical Architecture & Operations Guide

## 1. System Overview

**IERS (Intelligent Emergency Response System)** is a metropolitan emergency dispatch and ambulance route-optimisation platform covering the **Hubballi–Dharwad** urban region (`40,394` road segments, `29,385` routing vertices, `91` real OpenStreetMap hospitals, and `28` geographically distributed fleet units).

All four stakeholder portals (**Citizen**, **Dispatcher**, **Hospital Staff**, and **Ambulance Operator**) share:
- **One PostgreSQL 18 + PostGIS 3.6 + pgRouting 4.0 database** (`localhost:5432`, database `emergency_db`, schema `public`)
- **One FastAPI backend** (`http://127.0.0.1:8000`)
- **One Native PyQGIS XYZ Tile Server** (`http://127.0.0.1:8001`, proxied at `/tiles/{z}/{x}/{y}.png`)

---

## 2. Repository Folder Structure

```text
C:\Projects\Intelligent-Emergency-Response\
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, auth, core REST, traffic sim, WebSocket hub, tile proxy
│   │   ├── core/
│   │   │   ├── config.py              # DATABASE_URL -> localhost:5432/emergency_db
│   │   │   ├── database.py            # Async SQLAlchemy + asyncpg pool (search_path=public)
│   │   │   └── auth.py                # PBKDF2-SHA256 password hashing + HS256 JWT + require_roles()
│   │   ├── routers/
│   │   │   ├── portals.py             # Role-scoped endpoints (Citizen, Hospital, Operator, Users, BBOX GIS, Diagnostics)
│   │   │   └── workflow.py            # 7-stage emergency workflow, spatial ranking, two-leg routing, telemetry sim, complaints
│   │   ├── services/
│   │   │   ├── pgrouting_service.py   # Real pgr_dijkstra & pgr_astar with one-way/contraflow/clearance/corridor costs
│   │   │   └── csv_import_service.py  # Transactional Hospital Bulk CSV validation, dedup, cross-hospital guard
│   │   ├── algorithms/routing.py      # Constrained A* unit-testable engine
│   │   └── models/entities.py         # SQLAlchemy / GeoAlchemy2 ORM models
│   └── tests/
│       ├── test_core.py               # Core routing, clearance, traffic, concurrency tests
│       ├── test_multi_stakeholder_and_csv.py  # 4-role RBAC, CSV import security & validation, BBOX GIS tests
│       └── test_end_to_end_workflow.py        # Full 7-stage two-leg workflow & zero-OSM verification
├── database/
│   └── migrations/                    # Versioned, non-destructive SQL migrations (010 through 014)
├── gis/
│   ├── qgis/
│   │   ├── Intelligent_Emergency_Response.qgz # Authoritative QGIS desktop project
│   │   └── tile_cache/                # Cached EPSG:3857 256x256 PNG tiles (v5)
│   ├── data/
│   │   └── osm_hospitals_hubballi_dharwad.json # 111 real OpenStreetMap hospitals (ODbL)
│   └── scripts/
│       ├── qgis_tile_server.py        # PyQGIS EPSG:3857 multi-scale XYZ tile server
│       └── expand_hospitals_and_demo_fleet.py # Giant-component snapping + 91 hospitals + 28 demo units
├── frontend/
│   └── index.html                     # Landing page + 4 role-scoped portals + Leaflet/MarkerCluster + Three.js 3D
└── docs/
    └── TECHNICAL_ARCHITECTURE.md      # This document
```

---

## 3. Spatial Database & Constraint-Based Route Optimisation

### 3.1 Spatial Data Model (`emergency_db.public`)
- **`public.roads` (40,394 edges, SRID 4326, GiST indexed):** Real OpenStreetMap road segments with `source`/`target` graph vertices, `distance_m`, `speed_limit`, `travel_time_s`, `traffic_multiplier`, `current_travel_time_s`, `is_oneway` (1,837 edges), `emergency_contraflow_allowed` (766 urban one-way edges; divided dual carriageways, expressways, bridges, and trunk highways remain strictly one-way), `is_emergency_corridor`, `is_blocked`, and physical clearance (`max_height_m`, `max_width_m`, `max_weight_t`).
- **`public.road_nodes` (29,385 vertices, SRID 4326, GiST indexed):** Tagged with `in_giant_component` via `pgr_connectedComponents` (`29,375` vertices = 99.97% giant component).
- **`public.hospitals` (91 real OSM hospitals) & `public.ambulances` (28 fleet units):** Every facility and ambulance is snapped to its nearest giant-component road vertex using PostGIS KNN (`ORDER BY location <-> ST_SetSRID(ST_MakePoint(lon, lat), 4326) LIMIT 1`).

### 3.2 How Constraint-Based Routing Works (`pgrouting_service.py`)
1. **Ordinary Vehicle (`NORMAL`):**
   - `reverse_cost = -1` on every `is_oneway = TRUE` edge.
   - Blocked roads (`is_blocked = TRUE`) and edges violating vehicle height/width/weight are excluded before graph traversal.
2. **Emergency Vehicle (`AMBULANCE`):**
   - Authorized urban one-way streets (`emergency_contraflow_allowed = TRUE`) can be traversed in reverse with a `1.35x` safety multiplier; divided highways and bridges remain `-1` (prohibited).
   - Active emergency corridors (`is_emergency_corridor = TRUE`) receive a `0.6x` travel-time weight (40% congestion relief).
3. **Algorithms:** Both `pgr_dijkstra` and `pgr_astar` (with Euclidean heuristic) execute directly inside PostgreSQL and return oriented `ST_AsGeoJSON` road polylines.
4. **Two-Leg Dispatch:**
   - **Leg 1:** Ambulance current node $\to$ Emergency pickup node.
   - **Leg 2:** Automatically calculated on `PATIENT_PICKED_UP` from Emergency node $\to$ Recommended Hospital node.

### 3.3 Native PyQGIS Multi-Scale Rendering (`qgis_tile_server.py`)
- Renders **EPSG:3857** 256×256 PNG tiles directly from `emergency_db.public.roads` with Pixel-unit road widths and `pal.mergeLines = True` curved labels:
  - **Zoom $\le$ 10 (Metropolitan):** Trunk & primary highways only; markers clustered.
  - **Zoom 11–13 (City):** Adds secondary & tertiary roads; clusters expand.
  - **Zoom $\ge$ 14 (Street):** All local streets + curved street-name labels with white halo.
- Display simplification (`ST_SimplifyPreserveTopology`) is applied only to optional GeoJSON overlays — never to the routing graph.

---

## 4. How to Add Ambulance Operators & Grant Access in the Backend

### Method A: Via REST API (Recommended — Dispatcher Token Required)
Send a `POST /api/v1/users` request authenticated as a **Dispatcher**:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/users \
  -H "Authorization: Bearer <DISPATCHER_JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Rohan Deshpande",
    "email": "operator2@iers.gov.in",
    "password": "operator123",
    "role": "AMBULANCE_OPERATOR",
    "assigned_entity_id": "AMB_02"
  }'
```

- For **`AMBULANCE_OPERATOR`**: pass `assigned_entity_id` as either the ambulance code (e.g. `"AMB_02"`) or its UUID from `public.ambulances`. The backend automatically resolves it to the UUID.
- For **`HOSPITAL_STAFF`**: pass `assigned_entity_id` as the hospital code (e.g. `"HOSP_01"`) or UUID from `public.hospitals`.
- For **`CITIZEN`** or **`DISPATCHER`**: omit `assigned_entity_id`.

### Method B: Via Backend Python CLI (Direct DB Provisioning)
```powershell
cd C:\Projects\Intelligent-Emergency-Response\backend
$env:PYTHONPATH = "C:\Projects\Intelligent-Emergency-Response\backend"
.\venv\Scripts\python.exe -c "
import psycopg2
from app.core.auth import hash_password
c = psycopg2.connect('host=localhost port=5432 dbname=emergency_db user=postgres password=<YOUR_PASSWORD>')
cur = c.cursor()
cur.execute('SELECT ambulance_id::text FROM public.ambulances WHERE ambulance_code = %s', ('AMB_02',))
aid = cur.fetchone()[0]
cur.execute('''
  INSERT INTO public.users (name, email, password_hash, role, assigned_entity_id, is_active)
  VALUES (%s, %s, %s, 'AMBULANCE_OPERATOR', %s, TRUE)
''', ('Operator 2', 'operator2@iers.gov.in', hash_password('operator123'), aid))
c.commit(); c.close()
"
```

---

## 5. End-to-End 7-Stage Emergency Lifecycle

1. **Citizen** reports emergency (`POST /api/v1/incidents/create`) $\to$ persisted in `public.emergencies` + `public.emergency_events`.
2. **Dispatcher** runs spatial ranking (`GET /api/v1/workflow/analyze/{id}`) $\to$ ranks available ambulances by pgRouting network travel time (seconds) and hospitals by network ETA + ICU/trauma suitability.
3. **Dispatcher** assigns ambulance (`POST /api/v1/workflow/assign/{id}`) $\to$ atomic lock reserves `public.ambulances`, inserts `public.dispatches` + `public.route_history` (Leg 1).
4. **Ambulance Operator** accepts & starts Leg 1 (`POST /api/v1/workflow/crew-action/{id}`) $\to$ 60fps directional navigation animation + background telemetry simulator updates `public.ambulances` & `public.ambulance_location_history`.
5. **Ambulance Operator** confirms pickup (`PATIENT_PICKED_UP`) $\to$ Leg 2 route to hospital auto-computed via pgRouting.
6. **Hospital Staff** monitors incoming unit & updates capacity (`PATCH /api/v1/hospital/my-facility` or transactional Bulk CSV Import).
7. **Dispatcher** verifies completion (`POST /api/v1/workflow/verify/{id}`) $\to$ closes emergency (`COMPLETED`) and releases ambulance back to `AVAILABLE`.

---

## 6. Verified Test Results

All automated pytest results (`10/10 PASSED`), PostGIS topology audits, intercity pgRouting tests, and multi-scale PyQGIS tile checks are archived in [`docs/test_results/`](test_results/):
- [TEST_SUMMARY.md](test_results/TEST_SUMMARY.md) — Structured test report & spatial diagnostics
- [pytest_results.txt](test_results/pytest_results.txt) — Verbatim `pytest -v` execution log

