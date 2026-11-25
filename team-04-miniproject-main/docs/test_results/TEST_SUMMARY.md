# IERS — Verified Automated & Spatial Test Results

**Run Date:** 2026-11-22  
**Database:** PostgreSQL 18 + PostGIS 3.6.2 + pgRouting 4.0.1 (`localhost:5432 / emergency_db`, schema `public`)  
**Raw Log:** [pytest_results.txt](pytest_results.txt)

---

## 1. Automated Pytest Suite (`10 / 10 PASSED` in `11.02s`)

| # | Test Suite | Test Case | Status | What It Verifies |
|---|---|---|---|---|
| 1 | `test_core.py` | `test_gis_network_loaded` | **PASSED** | Routing graph loads nodes & edges |
| 2 | `test_core.py` | `test_constrained_routing_underpass_height_rejection` | **PASSED** | Tall ALS unit rejected from low underpass |
| 3 | `test_core.py` | `test_constrained_routing_narrow_alley` | **PASSED** | Wide ambulance rerouted around narrow street |
| 4 | `test_core.py` | `test_traffic_emergency_corridor_relief` | **PASSED** | Emergency corridor dampens congestion travel time |
| 5 | `test_core.py` | `test_dispatch_concurrency_lock` | **PASSED** | Atomic lock prevents double-booking same ambulance |
| 6 | `test_end_to_end_workflow.py` | `test_complete_7_stage_workflow_and_complaints` | **PASSED** | Citizen report $\to$ spatial ranking $\to$ Dispatcher assign (`public.dispatches`) $\to$ Crew Leg 1 & auto Leg 2 $\to$ Dispatcher verify $\to$ ambulance released + complaints |
| 7 | `test_end_to_end_workflow.py` | `test_no_openstreetmap_basemap_in_frontend` | **PASSED** | Zero `tile.openstreetmap.org` URLs; native PyQGIS `/tiles/{z}/{x}/{y}.png` verified |
| 8 | `test_multi_stakeholder_and_csv.py` | `test_four_stakeholder_roles_and_rbac` | **PASSED** | 4-role JWT login (`CITIZEN`, `DISPATCHER`, `HOSPITAL_STAFF`, `AMBULANCE_OPERATOR`) + `403` enforcement on unauthorized routes |
| 9 | `test_multi_stakeholder_and_csv.py` | `test_hospital_csv_bulk_import_validation_and_security` | **PASSED** | Valid CSV commit, `icu > beds` rejection, duplicate detection, cross-hospital CSV attack blocked |
| 10 | `test_multi_stakeholder_and_csv.py` | `test_bbox_zoom_dependent_gis_roads` | **PASSED** | Level 1 Metropolitan zoom (`z=10`) returns only `trunk`/`primary` highways via `ST_SimplifyPreserveTopology` |

---

## 2. PostGIS & pgRouting Spatial Verification (`emergency_db.public`)

- **Road Network Integrity:** `40,394` edges, `40,394` unique geometries (`0` duplicates, `0` invalid, `0` empty, `0` NULL endpoints, `0` wrong SRID).
- **Connected Components (`pgr_connectedComponents`):** `5` components total (`29,375 / 29,385` vertices = **99.97%** in giant component).
- **Entity Snapping:** `91 / 91` real OpenStreetMap hospitals and `28 / 28` simulated ambulances snapped to giant-component vertices (`0` unreachable).
- **Intercity & Intra-City Dijkstra Tests (`4 / 4 PASSED`):**
  - Hubballi KIMS $\to$ Dharwad District Hospital: `139` edges, `18.22 km`
  - Dharwad Jubilee Circle $\to$ Hubballi Gokul Road: `151` edges, `20.15 km`
  - Navanagar $\to$ Old Hubballi: `116` edges, `11.22 km`
  - Saptapur Dharwad $\to$ SDM Sattur: `84` edges, `10.23 km`
- **Multi-Scale PyQGIS EPSG:3857 Tiles (`4 / 4 HTTP 200`):** `z=10` (18 KB), `z=12` (41 KB), `z=14` (88 KB), `z=15` (47 KB).
