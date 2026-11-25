import asyncio
import json
import os
import urllib.request
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine, get_db
from app.core.auth import (
    verify_password,
    create_access_token,
    get_current_user,
    get_optional_user,
    require_roles,
)
from app.services.pgrouting_service import find_nearest_road_node, compute_pgrouting_path
from app.routers.portals import router as portals_router
from app.routers.workflow import router as workflow_router, register_ws_broadcaster

app = FastAPI(title=settings.APP_NAME, version="3.2.0")
app.include_router(portals_router)
app.include_router(workflow_router)

static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

dispatch_lock = asyncio.Lock()

TRAFFIC_SIM_STATE = {
    "mode": "NORMAL",
    "is_simulated": True,
    "multiplier": 1.0,
    "updated_at": datetime.utcnow().isoformat() + "Z",
}


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                self.disconnect(connection)


ws_manager = ConnectionManager()
register_ws_broadcaster(ws_manager.broadcast)


@app.get("/")
def root():
    frontend_index = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "index.html"))
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    return {"status": "online", "system": settings.APP_NAME}


@app.get("/tiles/{z}/{x}/{y}.png")
async def proxy_qgis_tile(z: int, x: int, y: int):
    url = f"http://127.0.0.1:8001/tiles/{z}/{x}/{y}.png"

    def _fetch():
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.read()

    try:
        data = await asyncio.to_thread(_fetch)
        return Response(content=data, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"QGIS tile server unavailable: {e}")


# ============================================================================
# AUTHENTICATION (public.users in emergency_db)
# ============================================================================
@app.post("/api/v1/auth/login")
async def login(payload: dict, db: AsyncSession = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    res = await db.execute(
        text("SELECT user_id::text, name, email, password_hash, role, assigned_entity_id, is_active FROM public.users WHERE LOWER(email) = :email"),
        {"email": email},
    )
    user = res.mappings().first()
    if not user or not user["is_active"] or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({
        "sub": user["user_id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "assigned_entity_id": user["assigned_entity_id"],
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": user["user_id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "assigned_entity_id": user["assigned_entity_id"],
        },
    }


@app.post("/api/v1/auth/register")
async def register(payload: dict, db: AsyncSession = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    role = (payload.get("role") or "CITIZEN").strip().upper()
    if not name or not email or len(password) < 4:
        raise HTTPException(status_code=400, detail="Name, email, and password (min 4 chars) are required")
    if role not in ("CITIZEN", "AMBULANCE_OPERATOR", "HOSPITAL_STAFF"):
        role = "CITIZEN"

    existing = (await db.execute(text("SELECT 1 FROM public.users WHERE LOWER(email) = :em"), {"em": email})).scalar()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    assigned_entity_id = None
    if role == "AMBULANCE_OPERATOR":
        assigned_entity_id = (await db.execute(text("SELECT ambulance_id::text FROM public.ambulances ORDER BY call_sign LIMIT 1"))).scalar()
    elif role == "HOSPITAL_STAFF":
        assigned_entity_id = (await db.execute(text("SELECT hospital_id::text FROM public.hospitals ORDER BY name LIMIT 1"))).scalar()

    from app.core.auth import hash_password
    pw_hash = hash_password(password)
    row = (await db.execute(
        text("""
            INSERT INTO public.users (name, email, password_hash, role, assigned_entity_id, is_active)
            VALUES (:name, :em, :pw, :role, :ent, TRUE)
            RETURNING user_id::text, name, email, role, assigned_entity_id
        """),
        {"name": name, "em": email, "pw": pw_hash, "role": role, "ent": assigned_entity_id},
    )).mappings().first()
    await db.commit()

    token = create_access_token({
        "sub": row["user_id"], "name": row["name"], "email": row["email"],
        "role": row["role"], "assigned_entity_id": row["assigned_entity_id"],
    })
    return {"access_token": token, "token_type": "bearer", "user": dict(row)}


@app.get("/api/v1/auth/me")
async def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    return user


# ============================================================================
# SYSTEM & GIS DIAGNOSTICS (emergency_db / public)
# ============================================================================
@app.get("/api/v1/system/database-info")
async def get_database_info(db: AsyncSession = Depends(get_db)):
    res = await db.execute(text("""
        SELECT
            current_database() AS db_name,
            current_user AS db_user,
            current_schema() AS active_schema,
            inet_server_port() AS server_port,
            postgis_version() AS postgis_ver,
            pgr_version() AS pgrouting_ver
    """))
    row = dict(res.fetchone()._mapping)

    counts = (await db.execute(text("""
        SELECT
            (SELECT count(*) FROM public.road_nodes) AS road_nodes,
            (SELECT count(*) FROM public.roads) AS road_edges,
            (SELECT count(*) FROM public.roads WHERE is_oneway) AS oneway_edges,
            (SELECT count(*) FROM public.roads WHERE emergency_contraflow_allowed) AS contraflow_allowed_edges,
            (SELECT count(*) FROM public.roads WHERE is_blocked) AS blocked_edges,
            (SELECT count(*) FROM public.roads WHERE is_emergency_corridor) AS corridor_edges,
            (SELECT count(*) FROM public.ambulances) AS ambulances,
            (SELECT count(*) FROM public.hospitals) AS hospitals,
            (SELECT count(*) FROM public.emergencies) AS incidents,
            (SELECT count(*) FROM public.dispatches) AS dispatches,
            (SELECT count(*) FROM public.emergency_events) AS emergency_events,
            (SELECT count(*) FROM public.users) AS users,
            (SELECT round((sum(distance_m)/1000.0)::numeric, 1) FROM public.roads) AS total_road_km
    """))).mappings().first()

    clean_url = settings.DATABASE_URL
    if "@" in clean_url:
        clean_url = f"{clean_url.split('://')[0]}://***:***@{clean_url.split('@')[1]}"

    return {
        "status": "connected",
        "operational_rdbms": "PostgreSQL 18 + PostGIS 3.6 + pgRouting 4.0 (emergency_db)",
        "sqlite_in_use": False,
        "database_url_redacted": clean_url,
        "diagnostics": row,
        "verified_counts": {k: (float(v) if k == "total_road_km" else int(v or 0)) for k, v in dict(counts).items()},
    }


@app.get("/api/v1/gis/roads-overlay")
async def get_roads_overlay(filter_type: str = "arterial", db: AsyncSession = Depends(get_db)):
    where_map = {
        "arterial": "highway IN ('trunk', 'primary')",
        "congested": "traffic_multiplier >= 2.0 AND NOT is_blocked",
        "blocked": "is_blocked = TRUE",
        "corridors": "is_emergency_corridor = TRUE",
        "oneway": "is_oneway = TRUE",
    }
    where_clause = where_map.get(filter_type, where_map["arterial"])
    res = await db.execute(text(f"""
        SELECT road_id, name, highway, distance_m, traffic_multiplier,
               is_blocked, is_oneway, emergency_contraflow_allowed, is_emergency_corridor,
               ST_AsGeoJSON(geom)::json AS geometry
        FROM public.roads
        WHERE geom IS NOT NULL AND {where_clause}
        LIMIT 2500
    """))
    features = [
        {
            "type": "Feature",
            "geometry": r["geometry"],
            "properties": {
                "road_id": r["road_id"],
                "name": r["name"] or f"{r['highway']} road",
                "highway": r["highway"],
                "distance_m": round(float(r["distance_m"] or 0), 1),
                "traffic_multiplier": float(r["traffic_multiplier"] or 1.0),
                "is_blocked": bool(r["is_blocked"]),
                "is_oneway": bool(r["is_oneway"]),
                "emergency_contraflow_allowed": bool(r["emergency_contraflow_allowed"]),
                "is_emergency_corridor": bool(r["is_emergency_corridor"]),
            },
        }
        for r in res.mappings().all()
    ]
    return {"type": "FeatureCollection", "filter": filter_type, "count": len(features), "features": features}


# ============================================================================
# HOSPITALS (public.hospitals)
# ============================================================================
@app.get("/api/v1/hospitals")
async def get_hospitals(city: Optional[str] = None, trauma_only: bool = False, db: AsyncSession = Depends(get_db)):
    clauses = ["1=1"]
    params: Dict[str, Any] = {}
    if city:
        clauses.append("LOWER(city) = LOWER(:city)")
        params["city"] = city
    if trauma_only:
        clauses.append("has_trauma_care = TRUE")

    res = await db.execute(
        text(f"""
            SELECT hospital_id::text AS id, hospital_code, name, latitude, longitude,
                   available_beds, total_beds, icu_available, trauma_beds_available,
                   emergency_dept_capacity, trauma_level, has_helipad, nearest_node_id,
                   osm_id, has_icu, has_trauma_care, has_cardiology, contact_number,
                   city, service_status, service_notes, attributes_simulated
            FROM public.hospitals
            WHERE {' AND '.join(clauses)}
            ORDER BY trauma_level ASC, icu_available DESC, name ASC
        """),
        params,
    )
    return [dict(r) for r in res.mappings().all()]


# ============================================================================
# AMBULANCES (public.ambulances)
# ============================================================================
@app.get("/api/v1/ambulances")
async def get_ambulances(db: AsyncSession = Depends(get_db)):
    res = await db.execute(text("""
        SELECT ambulance_id::text AS id, ambulance_code, call_sign, registration_number,
               vehicle_type, status, latitude, longitude, current_node_id,
               height_meters, weight_tons, width_meters, driver_name,
               fuel_percent, capabilities, last_location_update AS updated_at
        FROM public.ambulances
        ORDER BY ambulance_code
    """))
    return [dict(r) for r in res.mappings().all()]


@app.patch("/api/v1/ambulances/{ambulance_id}/status")
async def update_ambulance_status(
    ambulance_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: Dict[str, Any] = Depends(require_roles("DISPATCHER", "AMBULANCE_OPERATOR")),
):
    new_status = (payload.get("status") or "").upper()
    res = await db.execute(
        text("""
            UPDATE public.ambulances
            SET status = :st, last_location_update = NOW()
            WHERE ambulance_id::text = :aid OR ambulance_code = :aid
            RETURNING ambulance_id::text AS id, ambulance_code, call_sign, status
        """),
        {"st": new_status, "aid": ambulance_id},
    )
    row = res.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Ambulance not found")
    await db.commit()
    return dict(row)


# ============================================================================
# EMERGENCIES (public.emergencies + public.emergency_events)
# ============================================================================
def _classify_priority(incident_type: str, people: int, req_prio: Optional[str]) -> tuple[str, int, bool]:
    if req_prio in ("P1", "P2", "P3", "P4"):
        return req_prio, {"P1": 95, "P2": 75, "P3": 50, "P4": 25}[req_prio], False
    low = (incident_type or "").lower()
    if any(k in low for k in ("cardiac", "stroke", "unconscious", "severe trauma", "bleeding", "fire")):
        return "P1", 95, False
    if people >= 3 or any(k in low for k in ("accident", "collision", "breathing", "chest")):
        return "P2", 78, False
    return "P3", 50, False


@app.get("/api/v1/incidents")
async def get_incidents(db: AsyncSession = Depends(get_db)):
    res = await db.execute(text("""
        SELECT e.emergency_id::text AS id, e.incident_code, e.incident_type,
               e.severity AS priority, e.priority_score, e.people_affected,
               e.description, e.needs_review, e.status, e.latitude, e.longitude,
               e.nearest_node_id, e.caller_name, e.caller_phone,
               e.assigned_ambulance_id::text AS assigned_ambulance_id,
               e.target_hospital_id::text AS target_hospital_id,
               e.eta_seconds, e.remaining_distance_m, e.created_at AS reported_at,
               e.active_leg,
               CASE WHEN e.status NOT IN ('COMPLETED','CANCELLED') THEN e.active_route_json ELSE NULL END AS active_route_json,
               a.call_sign AS ambulance_callsign,
               h.name AS hospital_name
        FROM public.emergencies e
        LEFT JOIN public.ambulances a ON a.ambulance_id = e.assigned_ambulance_id
        LEFT JOIN public.hospitals h ON h.hospital_id = e.target_hospital_id
        ORDER BY CASE e.severity WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 ELSE 4 END,
                 e.created_at DESC
    """))
    return [dict(r) for r in res.mappings().all()]


@app.post("/api/v1/incidents/create")
async def create_emergency(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """Persists emergency directly into public.emergencies & public.emergency_events in emergency_db."""
    lat = float(payload.get("latitude", 15.3647))
    lon = float(payload.get("longitude", 75.1240))
    incident_type = payload.get("incident_type", "Acute Cardiac Arrest")
    description = payload.get("description", "")
    people = int(payload.get("people_affected", 1))
    caller_name = payload.get("caller_name") or (user["name"] if user else "Emergency Caller")
    caller_phone = payload.get("caller_phone", "112")
    loc_source = payload.get("location_source", "CITIZEN_PORTAL")
    priority, p_score, needs_review = _classify_priority(incident_type, people, payload.get("priority"))

    nearest = await find_nearest_road_node(db, lat, lon)
    if not nearest:
        raise HTTPException(status_code=400, detail="Location outside Hubballi-Dharwad road network")
    inc_node, _ = nearest
    inc_code = f"EMG_{int(datetime.utcnow().timestamp() * 1000)}"
    reporter_uuid = user["sub"] if user else None
    reporter_email = user["email"] if user else "anonymous@iers.gov.in"

    row = (await db.execute(
        text("""
            INSERT INTO public.emergencies (
                incident_code, reported_by, reported_by_email, location,
                latitude, longitude, nearest_node_id, incident_type,
                severity, priority_score, people_affected, description,
                status, caller_name, caller_phone, needs_review, location_source
            ) VALUES (
                :code, CAST(:ruid AS uuid), :remail, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                :lat, :lon, :nid, :itype,
                :sev, :pscore, :ppl, :desc,
                'RECEIVED', :cname, :cphone, :rev, :ls
            )
            RETURNING emergency_id::text AS id, incident_code, severity, status
        """),
        {
            "code": inc_code, "ruid": reporter_uuid, "remail": reporter_email,
            "lat": lat, "lon": lon, "nid": str(inc_node), "itype": incident_type,
            "sev": priority, "pscore": p_score, "ppl": people, "desc": description,
            "cname": caller_name, "cphone": caller_phone, "rev": needs_review, "ls": loc_source,
        },
    )).mappings().first()

    await db.execute(
        text("""
            INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by, changed_by_email, remarks)
            VALUES (CAST(:eid AS uuid), NULL, 'RECEIVED', CAST(:ruid AS uuid), :remail, :rem)
        """),
        {
            "eid": row["id"], "ruid": reporter_uuid, "remail": reporter_email,
            "rem": f"Emergency reported ({priority}) at {lat:.5f}, {lon:.5f}",
        },
    )
    await db.commit()
    await ws_manager.broadcast({"type": "EMERGENCY_REPORTED", "incident_id": row["id"], "priority": priority})

    # Automatic backend spatial ranking, ambulance assignment, hospital selection, and live movement
    auto_assigned = None
    if payload.get("auto_assign", True) and inc_node:
        try:
            from app.services.live_simulator import _rank_best_ambulance, _select_best_hospital
            from app.routers.workflow import _active_sim_tasks, _run_route_telemetry_sim, stop_telemetry_sim
            import asyncio as _asyncio

            ranked = await _rank_best_ambulance(db, lat, lon, int(inc_node), priority)
            hosp_choice = await _select_best_hospital(db, lat, lon, int(inc_node), priority)
            if ranked and hosp_choice:
                amb, leg1 = ranked
                hosp, _leg2 = hosp_choice
                aid, call_sign = amb["ambulance_id"], amb["call_sign"]
                hid, hname = hosp["hospital_id"], hosp["name"]
                eta_s = max(15, int(round(leg1["total_duration_seconds"])))

                locked = (await db.execute(
                    text("SELECT status FROM public.ambulances WHERE ambulance_id = CAST(:aid AS uuid) FOR UPDATE"),
                    {"aid": aid},
                )).scalar()
                if locked == "AVAILABLE":
                    await db.execute(
                        text("UPDATE public.ambulances SET status = 'ASSIGNED' WHERE ambulance_id = CAST(:aid AS uuid)"),
                        {"aid": aid},
                    )
                    disp_id = (await db.execute(
                        text("""
                            INSERT INTO public.dispatches (emergency_id, ambulance_id, hospital_id, status)
                            VALUES (CAST(:eid AS uuid), CAST(:aid AS uuid), CAST(:hid AS uuid), 'ACTIVE')
                            RETURNING dispatch_id::text
                        """),
                        {"eid": row["id"], "aid": aid, "hid": hid},
                    )).scalar()
                    await db.execute(
                        text("""
                            UPDATE public.emergencies
                            SET assigned_ambulance_id = CAST(:aid AS uuid),
                                target_hospital_id = CAST(:hid AS uuid),
                                status = 'ASSIGNED', active_leg = 'LEG_1',
                                active_route_json = CAST(:rjson AS jsonb),
                                eta_seconds = :eta, remaining_distance_m = :rem,
                                dispatched_at = NOW()
                            WHERE emergency_id = CAST(:eid AS uuid)
                        """),
                        {"aid": aid, "hid": hid, "rjson": json.dumps(leg1), "eta": eta_s, "rem": leg1["total_distance_meters"], "eid": row["id"]},
                    )
                    await db.execute(
                        text("""
                            INSERT INTO public.route_history (dispatch_id, algorithm, route_geom, distance_m, estimated_time_s, network_version)
                            VALUES (CAST(:did AS uuid), 'ASTAR', ST_SetSRID(ST_GeomFromGeoJSON(:gjson), 4326), :dm, :ts, 'hubballi-auto-dispatch')
                        """),
                        {"did": disp_id, "gjson": json.dumps(leg1["geojson"]["geometry"]), "dm": leg1["total_distance_meters"], "ts": leg1["total_duration_seconds"]},
                    )
                    await db.execute(
                        text("""
                            INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by_email, remarks)
                            VALUES (CAST(:eid AS uuid), 'RECEIVED', 'ASSIGNED', 'auto-dispatch@iers.gov.in', :rem)
                        """),
                        {"eid": row["id"], "rem": f"Auto-assigned {call_sign} -> {hname} (ETA {eta_s}s via pgRouting A*)"},
                    )
                    await db.commit()

                    await ws_manager.broadcast({
                        "type": "DISPATCH_ASSIGNED",
                        "incident_id": row["id"],
                        "dispatch_id": disp_id,
                        "ambulance_id": aid,
                        "ambulance_callsign": call_sign,
                        "hospital_id": hid,
                        "hospital_name": hname,
                        "eta_seconds": eta_s,
                        "remaining_distance_m": leg1["total_distance_meters"],
                        "route_coords": leg1["coordinates"],
                        "leg": "LEG_1",
                    })
                    if leg1.get("coordinates"):
                        stop_telemetry_sim(aid)
                        _active_sim_tasks[aid] = _asyncio.create_task(
                            _run_route_telemetry_sim(row["id"], aid, leg1["coordinates"], leg1["total_distance_meters"], "LEG_1")
                        )
                    auto_assigned = {"dispatch_id": disp_id, "ambulance_id": aid, "ambulance_callsign": call_sign, "hospital_name": hname, "eta_seconds": eta_s}
        except Exception as exc:
            print(f"[AutoDispatch] Failed for {row['id']}: {exc}")

    return {
        "status": "ASSIGNED" if auto_assigned else "RECEIVED",
        "incident_id": row["id"],
        "incident_code": row["incident_code"],
        "priority": priority,
        "auto_dispatch": auto_assigned,
    }


@app.patch("/api/v1/incidents/{incident_id}/status")
async def update_incident_status(
    incident_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: Dict[str, Any] = Depends(require_roles("DISPATCHER", "AMBULANCE_OPERATOR")),
):
    new_status = (payload.get("status") or "").upper()
    cur = (await db.execute(
        text("SELECT emergency_id::text, status, assigned_ambulance_id::text FROM public.emergencies WHERE emergency_id::text = :iid OR incident_code = :iid"),
        {"iid": incident_id},
    )).mappings().first()
    if not cur:
        raise HTTPException(status_code=404, detail="Emergency not found")

    eid = cur["emergency_id"]
    await db.execute(
        text("UPDATE public.emergencies SET status = :st, resolved_at = CASE WHEN CAST(:st AS text) IN ('COMPLETED','CANCELLED') THEN NOW() ELSE resolved_at END WHERE emergency_id = CAST(:eid AS uuid)"),
        {"st": new_status, "eid": eid},
    )
    if new_status in ("COMPLETED", "CANCELLED") and cur["assigned_ambulance_id"]:
        await db.execute(
            text("UPDATE public.ambulances SET status = 'AVAILABLE', last_location_update = NOW() WHERE ambulance_id = CAST(:aid AS uuid)"),
            {"aid": cur["assigned_ambulance_id"]},
        )
        await db.execute(
            text("UPDATE public.dispatches SET status = :st WHERE emergency_id = CAST(:eid AS uuid) AND status = 'ACTIVE'"),
            {"st": new_status, "eid": eid},
        )
    await db.execute(
        text("""
            INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by, changed_by_email, remarks)
            VALUES (CAST(:eid AS uuid), :old, :new, CAST(:uid AS uuid), :em, :rem)
        """),
        {"eid": eid, "old": cur["status"], "new": new_status, "uid": user["sub"], "em": user["email"], "rem": payload.get("remarks") or f"Updated by {user['role']}"},
    )
    await db.commit()
    return {"incident_id": eid, "old_status": cur["status"], "new_status": new_status}


# ============================================================================
# ROUTING & TRAFFIC SIMULATION (public.roads)
# ============================================================================
@app.post("/api/v1/routing/compare")
async def compare_normal_vs_ambulance(payload: dict, db: AsyncSession = Depends(get_db)):
    sn = await find_nearest_road_node(db, float(payload["start_lat"]), float(payload["start_lon"]))
    en = await find_nearest_road_node(db, float(payload["end_lat"]), float(payload["end_lon"]))
    algo = (payload.get("algorithm") or "DIJKSTRA").upper()
    vh = float(payload.get("vehicle_height", 2.4))
    vw = float(payload.get("vehicle_width", 2.2))
    normal_route = await compute_pgrouting_path(db, sn[0], en[0], algorithm=algo, vehicle_mode="NORMAL", vehicle_height=vh, vehicle_width=vw)
    amb_route = await compute_pgrouting_path(db, sn[0], en[0], algorithm=algo, vehicle_mode="AMBULANCE", vehicle_height=vh, vehicle_width=vw)
    saved_s = round(normal_route["total_duration_seconds"] - amb_route["total_duration_seconds"], 1) if (normal_route and amb_route) else None
    return {
        "algorithm": algo, "start_node": sn[0], "end_node": en[0],
        "vehicle_height": vh, "vehicle_width": vw,
        "time_saved_seconds": saved_s,
        "normal_vehicle": normal_route, "ambulance": amb_route,
    }


@app.get("/api/v1/traffic/summary")
async def get_traffic_summary(db: AsyncSession = Depends(get_db)):
    row = (await db.execute(text("""
        SELECT
            count(*) FILTER (WHERE traffic_multiplier <= 1.2 AND NOT is_blocked) AS free_flow_roads,
            count(*) FILTER (WHERE traffic_multiplier > 1.2 AND traffic_multiplier < 2.2 AND NOT is_blocked) AS moderate_roads,
            count(*) FILTER (WHERE traffic_multiplier >= 2.2 AND NOT is_blocked) AS congested_roads,
            count(*) FILTER (WHERE is_blocked) AS closed_roads,
            count(*) FILTER (WHERE is_emergency_corridor) AS emergency_corridors
        FROM public.roads
    """))).mappings().first()
    return {**TRAFFIC_SIM_STATE, "stats": {k: int(v or 0) for k, v in dict(row).items()}}


@app.post("/api/v1/traffic/simulate")
async def simulate_traffic(payload: dict, db: AsyncSession = Depends(get_db), _: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    level = (payload.get("level") or "MODERATE").upper()
    mult_map = {"FREE_FLOW": 1.0, "MODERATE": 1.6, "RUSH_HOUR": 2.8, "SEVERE": 3.8}
    m = mult_map.get(level, 1.6)
    await db.execute(text("UPDATE public.roads SET traffic_multiplier = :m, current_travel_time_s = GREATEST(travel_time_s * :m, 0.5) WHERE highway IN ('trunk','primary','secondary','tertiary')"), {"m": m})
    await db.commit()
    TRAFFIC_SIM_STATE.update({"mode": level, "multiplier": m, "updated_at": datetime.utcnow().isoformat() + "Z"})
    return await get_traffic_summary(db)


@app.post("/api/v1/traffic/toggle-emergency-corridor")
async def toggle_corridor(payload: dict, db: AsyncSession = Depends(get_db), _: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    active = bool(payload.get("active", True))
    await db.execute(text("UPDATE public.roads SET is_emergency_corridor = :a WHERE highway IN ('trunk','primary')"), {"a": active})
    await db.commit()
    return {"emergency_corridor_active": active}


@app.post("/api/v1/simulation/start")
async def api_start_simulation(payload: dict = {}, _: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    from app.services.live_simulator import start_simulation
    return await start_simulation(
        max_concurrent=int(payload.get("max_concurrent", 4)),
        spawn_interval_s=int(payload.get("spawn_interval_s", 6)),
        speed_multiplier=float(payload.get("speed_multiplier", 2.0)),
    )


@app.post("/api/v1/simulation/pause")
async def api_pause_simulation(_: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    from app.services.live_simulator import pause_simulation
    return await pause_simulation()


@app.post("/api/v1/simulation/resume")
async def api_resume_simulation(_: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    from app.services.live_simulator import resume_simulation
    return await resume_simulation()


@app.post("/api/v1/simulation/config")
async def api_config_simulation(payload: dict = {}, _: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    from app.services.live_simulator import update_simulation_config
    return await update_simulation_config(
        speed_multiplier=payload.get("speed_multiplier"),
        max_concurrent=payload.get("max_concurrent"),
        spawn_interval_s=payload.get("spawn_interval_s"),
    )


@app.post("/api/v1/simulation/stop")
async def api_stop_simulation(_: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    from app.services.live_simulator import stop_simulation
    return await stop_simulation()


@app.post("/api/v1/simulation/reset")
async def api_reset_simulation(_: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    from app.services.live_simulator import reset_demo_scenario
    return await reset_demo_scenario()


@app.get("/api/v1/simulation/status")
async def api_simulation_status():
    from app.services.live_simulator import get_simulation_status
    return get_simulation_status()


@app.post("/api/v1/traffic/road-closure")
async def toggle_road_closure(payload: dict, db: AsyncSession = Depends(get_db), _: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    road_id = int(payload["road_id"])
    blocked = bool(payload.get("is_blocked", True))
    await db.execute(text("UPDATE public.roads SET is_blocked = :b WHERE road_id = :rid"), {"b": blocked, "rid": road_id})
    await db.commit()
    return {"road_id": road_id, "is_blocked": blocked}


@app.post("/api/v1/traffic/reset")
async def reset_traffic(db: AsyncSession = Depends(get_db), _: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    await db.execute(text("UPDATE public.roads SET is_blocked = FALSE, is_emergency_corridor = FALSE, traffic_multiplier = 1.0, current_travel_time_s = GREATEST(travel_time_s, 0.5)"))
    await db.commit()
    TRAFFIC_SIM_STATE.update({"mode": "FREE_FLOW", "multiplier": 1.0})
    return await get_traffic_summary(db)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
