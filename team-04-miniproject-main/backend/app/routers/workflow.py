"""
IERS Complete 7-Stage Workflow — Unified onto emergency_db (schema: public)
Writes directly to public.emergencies, public.dispatches, public.ambulances,
public.emergency_events, public.route_history, public.ambulance_location_history, public.complaints.
"""
import asyncio
import json
import math
from datetime import datetime
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db, AsyncSessionLocal
from app.core.auth import require_roles
from app.services.pgrouting_service import compute_pgrouting_path

router = APIRouter(prefix="/api/v1", tags=["End-to-End Workflow"])

workflow_dispatch_lock = asyncio.Lock()
_active_sim_tasks: Dict[str, asyncio.Task] = {}
_ws_broadcaster = None


def register_ws_broadcaster(fn):
    global _ws_broadcaster
    _ws_broadcaster = fn


async def _broadcast(msg: dict):
    if _ws_broadcaster:
        await _ws_broadcaster(msg)


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return round((math.atan2(lon2 - lon1, lat2 - lat1) * 180.0 / math.pi + 360.0) % 360.0, 1)


def stop_telemetry_sim(ambulance_id: str):
    t = _active_sim_tasks.pop(ambulance_id, None)
    if t and not t.done():
        t.cancel()


async def _run_route_telemetry_sim(emergency_id: str, ambulance_id: str, coordinates: List[List[float]], total_dist_m: float, leg_name: str):
    if not coordinates or len(coordinates) < 2:
        return
    step_count = min(18, len(coordinates) - 1)
    indices = [int(round(i * (len(coordinates) - 1) / step_count)) for i in range(step_count + 1)]
    try:
        for step_idx in range(1, len(indices)):
            await asyncio.sleep(1.0)
            p_prev = coordinates[indices[step_idx - 1]]
            p_curr = coordinates[indices[step_idx]]
            lat, lon = float(p_curr[0]), float(p_curr[1])
            brg = _bearing_deg(p_prev[0], p_prev[1], lat, lon)
            frac_left = max(0.0, 1.0 - (step_idx / float(step_count)))
            rem_dist = round(total_dist_m * frac_left, 1)
            eta_s = max(0, int(round((step_count - step_idx) * 1.0)))

            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("""
                        UPDATE public.ambulances
                        SET latitude = :lat, longitude = :lon, current_speed_kmh = 52.0,
                            current_location = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                            last_location_update = NOW()
                        WHERE ambulance_id = CAST(:aid AS uuid)
                    """),
                    {"lat": lat, "lon": lon, "aid": ambulance_id},
                )
                await db.execute(
                    text("UPDATE public.emergencies SET eta_seconds = :eta, remaining_distance_m = :rem WHERE emergency_id = CAST(:eid AS uuid)"),
                    {"eta": eta_s, "rem": rem_dist, "eid": emergency_id},
                )
                await db.execute(
                    text("""
                        INSERT INTO public.ambulance_location_history
                            (ambulance_id, latitude, longitude, speed_kmh, bearing_deg, is_simulated, geom)
                        VALUES (CAST(:aid AS uuid), :lat, :lon, 52.0, :brg, TRUE, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                    """),
                    {"aid": ambulance_id, "lat": lat, "lon": lon, "brg": brg},
                )
                await db.commit()

            await _broadcast({
                "type": "AMBULANCE_LOCATION", "incident_id": emergency_id, "ambulance_id": ambulance_id,
                "leg": leg_name, "latitude": lat, "longitude": lon, "bearing_deg": brg,
                "remaining_distance_m": rem_dist, "eta_seconds": eta_s, "is_simulated": True,
            })
    except asyncio.CancelledError:
        pass


@router.get("/workflow/analyze/{incident_id}")
async def analyze_emergency_spatial(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    _: Dict[str, Any] = Depends(require_roles("DISPATCHER", "AMBULANCE_OPERATOR")),
):
    inc = (await db.execute(
        text("SELECT emergency_id::text AS id, incident_type, severity AS priority, latitude, longitude, nearest_node_id FROM public.emergencies WHERE emergency_id::text = :iid OR incident_code = :iid"),
        {"iid": incident_id},
    )).mappings().first()
    if not inc or not inc["nearest_node_id"]:
        raise HTTPException(status_code=404, detail="Emergency or snapped road node not found")
    inc_node = int(inc["nearest_node_id"])

    ambs = (await db.execute(
        text("""
            SELECT a.ambulance_id::text AS id, a.ambulance_code, a.call_sign, a.vehicle_type, a.status,
                   ST_Y(a.current_location::geometry) AS latitude,
                   ST_X(a.current_location::geometry) AS longitude,
                   (SELECT n.node_id FROM public.road_nodes n ORDER BY n.location <-> a.current_location::geometry LIMIT 1) AS current_node_id,
                   a.height_meters, a.width_meters, a.weight_tons, a.capabilities
            FROM public.ambulances a
            WHERE a.status = 'AVAILABLE'
        """)
    )).mappings().all()

    ranked_ambulances = []
    for a in ambs:
        route = await compute_pgrouting_path(
            db, int(a["current_node_id"]), inc_node, algorithm="ASTAR", vehicle_mode="AMBULANCE",
            vehicle_height=float(a["height_meters"] or 2.4), vehicle_width=float(a["width_meters"] or 2.2), vehicle_weight=float(a["weight_tons"] or 3.5),
        )
        if not route:
            continue
        eta_s = max(12, int(round(route["total_duration_seconds"])))
        cap_bonus = 0 if (inc["priority"] == "P1" and a["vehicle_type"] == "ALS") else 60
        ranked_ambulances.append({
            "ambulance_id": a["id"], "ambulance_code": a["ambulance_code"], "call_sign": a["call_sign"],
            "vehicle_type": a["vehicle_type"], "status": a["status"], "latitude": a["latitude"], "longitude": a["longitude"],
            "capabilities": a["capabilities"], "distance_m": route["total_distance_meters"], "eta_seconds": eta_s,
            "sort_score": eta_s + cap_bonus,
            "reason": f"Network ETA {eta_s}s ({route['total_distance_km']} km)" + (" + ALS match" if inc["priority"] == "P1" and a["vehicle_type"] == "ALS" else ""),
            "route": route,
        })
    ranked_ambulances.sort(key=lambda x: x["sort_score"])
    for idx, item in enumerate(ranked_ambulances, start=1):
        item["rank"] = idx

    hosps = (await db.execute(
        text("""
            SELECT hospital_id::text AS id, hospital_code, name, city, latitude, longitude, nearest_node_id,
                   total_beds, icu_available, trauma_level, has_trauma_care, has_cardiology, attributes_simulated
            FROM public.hospitals
            WHERE nearest_node_id IS NOT NULL AND service_status = 'OPERATIONAL' AND icu_available > 0
            ORDER BY location <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) LIMIT 6
        """),
        {"lat": inc["latitude"], "lon": inc["longitude"]},
    )).mappings().all()

    ranked_hospitals = []
    for h in hosps:
        route = await compute_pgrouting_path(db, inc_node, int(h["nearest_node_id"]), algorithm="ASTAR", vehicle_mode="AMBULANCE")
        if not route:
            continue
        eta_s = max(15, int(round(route["total_duration_seconds"])))
        score = 1000.0 - eta_s * 0.5 + (180.0 if inc["priority"] == "P1" and h["has_trauma_care"] else 0.0) + (40.0 if h["has_cardiology"] else 0.0)
        ranked_hospitals.append({
            "hospital_id": h["id"], "hospital_code": h["hospital_code"], "name": h["name"], "city": h["city"],
            "total_beds": h["total_beds"], "icu_available": h["icu_available"], "trauma_level": h["trauma_level"],
            "distance_m": route["total_distance_meters"], "eta_seconds": eta_s, "suitability_score": round(score, 1),
            "reason": f"Network ETA {eta_s}s ({route['total_distance_km']} km) · {h['icu_available']} ICU beds",
            "route": route,
        })
    ranked_hospitals.sort(key=lambda x: x["suitability_score"], reverse=True)
    for idx, item in enumerate(ranked_hospitals, start=1):
        item["rank"] = idx

    return {"incident": dict(inc), "ranked_ambulances": ranked_ambulances, "ranked_hospitals": ranked_hospitals}


@router.post("/workflow/assign/{incident_id}")
async def dispatcher_assign_ambulance(
    incident_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: Dict[str, Any] = Depends(require_roles("DISPATCHER")),
):
    """Transactionally creates public.dispatches record, reserves public.ambulances, and updates public.emergencies."""
    ambulance_id = payload.get("ambulance_id")
    hospital_id = payload.get("hospital_id")
    override_reason = (payload.get("override_reason") or "").strip()

    async with workflow_dispatch_lock:
        inc = (await db.execute(
            text("SELECT emergency_id::text, status, nearest_node_id FROM public.emergencies WHERE emergency_id::text = :iid OR incident_code = :iid"),
            {"iid": incident_id},
        )).mappings().first()
        if not inc:
            raise HTTPException(status_code=404, detail="Emergency not found")
        eid = inc["emergency_id"]

        amb = (await db.execute(
            text("""
                SELECT a.ambulance_id::text, a.call_sign, a.status,
                       (SELECT n.node_id FROM public.road_nodes n ORDER BY n.location <-> a.current_location::geometry LIMIT 1) AS current_node_id,
                       a.height_meters, a.width_meters, a.weight_tons
                FROM public.ambulances a
                WHERE a.ambulance_id::text = :aid OR a.ambulance_code = :aid
            """),
            {"aid": ambulance_id},
        )).mappings().first()
        if not amb or amb["status"] != "AVAILABLE":
            raise HTTPException(status_code=409, detail="Selected ambulance is not AVAILABLE")
        aid = amb["ambulance_id"]

        hosp = (await db.execute(
            text("SELECT hospital_id::text, name, nearest_node_id FROM public.hospitals WHERE hospital_id::text = :hid OR hospital_code = :hid"),
            {"hid": hospital_id},
        )).mappings().first()
        if not hosp:
            raise HTTPException(status_code=404, detail="Hospital not found")
        hid = hosp["hospital_id"]

        leg1 = await compute_pgrouting_path(
            db, int(amb["current_node_id"]), int(inc["nearest_node_id"]), algorithm="ASTAR", vehicle_mode="AMBULANCE",
            vehicle_height=float(amb["height_meters"] or 2.4), vehicle_width=float(amb["width_meters"] or 2.2), vehicle_weight=float(amb["weight_tons"] or 3.5),
        )
        if not leg1:
            raise HTTPException(status_code=400, detail="No viable road route")

        eta_s = max(12, int(round(leg1["total_duration_seconds"])))

        # 1. Reserve ambulance in public.ambulances
        await db.execute(text("UPDATE public.ambulances SET status = 'ASSIGNED', last_location_update = NOW() WHERE ambulance_id = CAST(:aid AS uuid)"), {"aid": aid})

        # 2. Create dispatch record in public.dispatches
        disp = (await db.execute(
            text("""
                INSERT INTO public.dispatches (emergency_id, ambulance_id, hospital_id, status)
                VALUES (CAST(:eid AS uuid), CAST(:aid AS uuid), CAST(:hid AS uuid), 'ACTIVE')
                RETURNING dispatch_id::text
            """),
            {"eid": eid, "aid": aid, "hid": hid},
        )).first()
        dispatch_id = disp[0]

        # 3. Update public.emergencies
        await db.execute(
            text("""
                UPDATE public.emergencies
                SET assigned_ambulance_id = CAST(:aid AS uuid), target_hospital_id = CAST(:hid AS uuid),
                    status = 'ASSIGNED', active_leg = 'LEG_1',
                    active_route_json = CAST(:rjson AS jsonb),
                    eta_seconds = :eta, remaining_distance_m = :rem,
                    override_reason = :ovr, dispatched_at = NOW()
                WHERE emergency_id = CAST(:eid AS uuid)
            """),
            {"aid": aid, "hid": hid, "rjson": json.dumps(leg1), "eta": eta_s, "rem": leg1["total_distance_meters"], "ovr": override_reason, "eid": eid},
        )

        # 4. Log public.emergency_events & public.route_history
        await db.execute(
            text("""
                INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by, changed_by_email, remarks)
                VALUES (CAST(:eid AS uuid), :old, 'ASSIGNED', CAST(:uid AS uuid), :em, :rem)
            """),
            {"eid": eid, "old": inc["status"], "uid": user["sub"], "em": user["email"], "rem": f"Assigned {amb['call_sign']} -> {hosp['name']} ({eta_s}s)"},
        )
        await db.execute(
            text("""
                INSERT INTO public.route_history (dispatch_id, algorithm, route_geom, distance_m, estimated_time_s, network_version)
                VALUES (CAST(:did AS uuid), 'ASTAR', ST_SetSRID(ST_GeomFromGeoJSON(:gjson), 4326), :dm, :ts, 'hubballi-dharwad-v1')
            """),
            {"did": dispatch_id, "gjson": json.dumps(leg1["geojson"]["geometry"]), "dm": leg1["total_distance_meters"], "ts": leg1["total_duration_seconds"]},
        )
        await db.commit()

    await _broadcast({"type": "DISPATCH_ASSIGNED", "incident_id": eid, "dispatch_id": dispatch_id, "ambulance_id": aid, "eta_seconds": eta_s})
    # Start live route movement immediately on manual assignment so Citizen & Dispatcher maps show movement right away
    if leg1 and leg1.get("coordinates"):
        stop_telemetry_sim(aid)
        _active_sim_tasks[aid] = asyncio.create_task(_run_route_telemetry_sim(eid, aid, leg1["coordinates"], leg1["total_distance_meters"], "LEG_1"))
    return {"status": "ASSIGNED", "dispatch_id": dispatch_id, "incident_id": eid, "ambulance_id": aid, "hospital_id": hid, "leg1_route": leg1, "eta_seconds": eta_s}


@router.post("/workflow/crew-action/{incident_id}")
async def crew_workflow_action(
    incident_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: Dict[str, Any] = Depends(require_roles("AMBULANCE_OPERATOR", "DISPATCHER")),
):
    action = (payload.get("action") or "").upper()
    inc = (await db.execute(
        text("""
            SELECT e.emergency_id::text, e.status, e.assigned_ambulance_id::text, e.nearest_node_id,
                   e.active_route_json, h.nearest_node_id AS hosp_node_id
            FROM public.emergencies e
            LEFT JOIN public.hospitals h ON h.hospital_id = e.target_hospital_id
            WHERE e.emergency_id::text = :iid OR e.incident_code = :iid
        """),
        {"iid": incident_id},
    )).mappings().first()
    if not inc or not inc["assigned_ambulance_id"]:
        raise HTTPException(status_code=404, detail="Assigned emergency not found")
    eid, aid = inc["emergency_id"], inc["assigned_ambulance_id"]

    new_status = None
    leg2_route = None
    if action == "ACCEPT_AND_START":
        new_status = "EN_ROUTE_TO_EMERGENCY"
        route = inc["active_route_json"]
        if route and route.get("coordinates"):
            stop_telemetry_sim(aid)
            _active_sim_tasks[aid] = asyncio.create_task(_run_route_telemetry_sim(eid, aid, route["coordinates"], route["total_distance_meters"], "LEG_1"))
    elif action == "ARRIVED_AT_EMERGENCY":
        stop_telemetry_sim(aid); new_status = "ARRIVED_AT_EMERGENCY"
    elif action == "PATIENT_PICKED_UP":
        stop_telemetry_sim(aid); new_status = "PATIENT_PICKED_UP"
        if inc["nearest_node_id"] and inc["hosp_node_id"]:
            leg2_route = await compute_pgrouting_path(db, int(inc["nearest_node_id"]), int(inc["hosp_node_id"]), algorithm="ASTAR", vehicle_mode="AMBULANCE")
            if leg2_route:
                await db.execute(
                    text("UPDATE public.emergencies SET active_leg = 'LEG_2', active_route_json = CAST(:rjson AS jsonb), eta_seconds = :eta, remaining_distance_m = :rem WHERE emergency_id = CAST(:eid AS uuid)"),
                    {"rjson": json.dumps(leg2_route), "eta": max(15, int(round(leg2_route["total_duration_seconds"]))), "rem": leg2_route["total_distance_meters"], "eid": eid},
                )
    elif action == "START_HOSPITAL_JOURNEY":
        new_status = "EN_ROUTE_TO_HOSPITAL"
        route = inc["active_route_json"]
        if route and route.get("coordinates"):
            stop_telemetry_sim(aid)
            _active_sim_tasks[aid] = asyncio.create_task(_run_route_telemetry_sim(eid, aid, route["coordinates"], route["total_distance_meters"], "LEG_2"))
    elif action == "ARRIVED_AT_HOSPITAL":
        stop_telemetry_sim(aid); new_status = "ARRIVED_AT_HOSPITAL"
    elif action == "SUBMIT_COMPLETION":
        stop_telemetry_sim(aid); new_status = "PENDING_VERIFICATION"
        await db.execute(text("UPDATE public.emergencies SET verification_status = 'PENDING' WHERE emergency_id = CAST(:eid AS uuid)"), {"eid": eid})
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    await db.execute(text("UPDATE public.emergencies SET status = :st WHERE emergency_id = CAST(:eid AS uuid)"), {"st": new_status, "eid": eid})
    await db.execute(text("UPDATE public.ambulances SET status = :st, last_location_update = NOW() WHERE ambulance_id = CAST(:aid AS uuid)"), {"st": new_status, "aid": aid})
    await db.execute(
        text("INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by, changed_by_email, remarks) VALUES (CAST(:eid AS uuid), :old, :new, CAST(:uid AS uuid), :em, :rem)"),
        {"eid": eid, "old": inc["status"], "new": new_status, "uid": user["sub"], "em": user["email"], "rem": f"Crew action: {action}"},
    )
    await db.commit()
    return {"incident_id": eid, "status": new_status, "leg2_route": leg2_route}


@router.post("/workflow/verify/{incident_id}")
async def dispatcher_verify_completion(
    incident_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: Dict[str, Any] = Depends(require_roles("DISPATCHER")),
):
    decision = (payload.get("decision") or "APPROVE").upper()
    notes = (payload.get("notes") or "").strip()
    inc = (await db.execute(
        text("SELECT emergency_id::text, status, assigned_ambulance_id::text FROM public.emergencies WHERE emergency_id::text = :iid OR incident_code = :iid"),
        {"iid": incident_id},
    )).mappings().first()
    if not inc:
        raise HTTPException(status_code=404, detail="Emergency not found")
    eid, aid = inc["emergency_id"], inc["assigned_ambulance_id"]

    if decision == "APPROVE":
        new_st = "COMPLETED"
        await db.execute(text("UPDATE public.emergencies SET status = 'COMPLETED', verification_status = 'APPROVED', verified_by = :vb, verification_notes = :nt, resolved_at = NOW() WHERE emergency_id = CAST(:eid AS uuid)"), {"vb": user["email"], "nt": notes, "eid": eid})
        await db.execute(text("UPDATE public.dispatches SET status = 'COMPLETED' WHERE emergency_id = CAST(:eid AS uuid) AND status = 'ACTIVE'"), {"eid": eid})
        if aid:
            stop_telemetry_sim(aid)
            await db.execute(text("UPDATE public.ambulances SET status = 'AVAILABLE', last_location_update = NOW() WHERE ambulance_id = CAST(:aid AS uuid)"), {"aid": aid})
    else:
        new_st = "ARRIVED_AT_HOSPITAL"
        await db.execute(text("UPDATE public.emergencies SET status = 'ARRIVED_AT_HOSPITAL', verification_status = 'REJECTED', verified_by = :vb, verification_notes = :nt WHERE emergency_id = CAST(:eid AS uuid)"), {"vb": user["email"], "nt": notes, "eid": eid})

    await db.execute(
        text("INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by, changed_by_email, remarks) VALUES (CAST(:eid AS uuid), :old, :new, CAST(:uid AS uuid), :em, :rem)"),
        {"eid": eid, "old": inc["status"], "new": new_st, "uid": user["sub"], "em": user["email"], "rem": f"Dispatcher {decision}: {notes}"},
    )
    await db.commit()
    return {"incident_id": eid, "decision": decision, "status": new_st}


@router.post("/complaints")
async def create_complaint(payload: dict, db: AsyncSession = Depends(get_db), user: Dict[str, Any] = Depends(require_roles("CITIZEN"))):
    cid = f"CMP_{int(datetime.utcnow().timestamp() * 1000)}"
    await db.execute(
        text("INSERT INTO public.complaints (complaint_id, emergency_id, submitted_by, category, description) VALUES (:cid, CAST(:eid AS uuid), :sub, :cat, :desc)"),
        {"cid": cid, "eid": payload.get("incident_id") or None, "sub": user["email"], "cat": payload.get("category") or "RESPONSE_DELAY", "desc": payload.get("description") or ""},
    )
    await db.commit()
    return {"complaint_id": cid, "status": "OPEN"}


@router.get("/complaints")
async def list_complaints(db: AsyncSession = Depends(get_db), user: Dict[str, Any] = Depends(require_roles("CITIZEN", "DISPATCHER"))):
    if user["role"] == "CITIZEN":
        res = await db.execute(text("SELECT * FROM public.complaints WHERE submitted_by = :sub ORDER BY created_at DESC"), {"sub": user["email"]})
    else:
        res = await db.execute(text("SELECT * FROM public.complaints ORDER BY created_at DESC"))
    return [dict(r) for r in res.mappings().all()]


@router.patch("/complaints/{complaint_id}")
async def resolve_complaint(complaint_id: str, payload: dict, db: AsyncSession = Depends(get_db), _: Dict[str, Any] = Depends(require_roles("DISPATCHER"))):
    st = (payload.get("status") or "RESOLVED").upper()
    await db.execute(text("UPDATE public.complaints SET status = :st, dispatcher_response = :resp, resolved_at = CASE WHEN :st = 'RESOLVED' THEN NOW() ELSE resolved_at END WHERE complaint_id = :cid"), {"st": st, "resp": payload.get("dispatcher_response") or "Resolved", "cid": complaint_id})
    await db.commit()
    return {"complaint_id": complaint_id, "status": st}
