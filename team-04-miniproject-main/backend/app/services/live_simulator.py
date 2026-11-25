"""
Continuous Real-Time Ambulance Movement & End-to-End Mission Simulation Engine (IERS).

Implements the complete 11-state mission lifecycle backed by PostgreSQL + PostGIS + pgRouting:
  AVAILABLE -> ASSIGNED -> EN_ROUTE_TO_EMERGENCY -> ARRIVED_AT_EMERGENCY
  -> PICKUP_IN_PROGRESS -> PATIENT_ONBOARD -> EN_ROUTE_TO_HOSPITAL
  -> ARRIVED_AT_HOSPITAL -> HANDOVER_IN_PROGRESS -> COMPLETED -> AVAILABLE

Features:
- Spatial candidate ranking by actual road-network ETA (pgRouting A* / Dijkstra) + vehicle suitability.
- Hospital suitability selection (road-network ETA + ICU/bed capacity + trauma level).
- Configurable simulation speed (1x, 2x, 5x, 10x), pause/resume/stop, max concurrent, spawn interval.
- Periodic DB persistence (location history every 3rd step + every state transition in emergency_events).
- Explicit Reset Demo action (stopping never deletes historical DB records).
- Real-time WebSocket broadcasts for Dispatcher, Operator, and Citizen portals.
"""
import asyncio
import json
import random
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

from sqlalchemy import text

from app.core.auth import hash_password
from app.core.database import AsyncSessionLocal
from app.services.pgrouting_service import compute_pgrouting_path

SIM_CITIZENS = [
    ("citizen2@iers.gov.in", "Aarav Kulkarni", "Vidyanagar"),
    ("citizen3@iers.gov.in", "Priya Deshpande", "Gokul Road"),
    ("citizen4@iers.gov.in", "Rohan Patil", "Keshwapur"),
    ("citizen5@iers.gov.in", "Sneha Joshi", "Unkal Lake"),
    ("citizen6@iers.gov.in", "Vikram Naik", "Deshpande Nagar"),
    ("citizen7@iers.gov.in", "Ananya Hegde", "Shirur Park"),
    ("citizen8@iers.gov.in", "Karthik Shenoy", "Old Hubballi"),
    ("citizen9@iers.gov.in", "Meera Nadkarni", "Navanagar"),
]

EMERGENCY_TEMPLATES = [
    ("P1", "CARDIAC", "Acute Cardiac Arrest"),
    ("P1", "TRAUMA", "Multi-Vehicle Road Traffic Accident"),
    ("P1", "STROKE", "Suspected Acute Ischemic Stroke"),
    ("P2", "RESPIRATORY", "Severe Respiratory Distress"),
    ("P2", "OBSTETRIC", "High-Risk Obstetric Emergency"),
    ("P2", "TRAUMA", "Industrial Construction Fall Trauma"),
    ("P3", "MEDICAL", "Hypertensive Crisis & Chest Pain"),
]

_sim_running: bool = False
_sim_spawning: bool = False
_sim_paused: bool = False
_sim_loop_task: Optional[asyncio.Task] = None
_active_mission_tasks: Dict[str, asyncio.Task] = {}
_activity_feed: Deque[Dict[str, Any]] = deque(maxlen=25)
_stats: Dict[str, Any] = {
    "started_at": None,
    "spawned_count": 0,
    "completed_count": 0,
    "max_concurrent": 4,
    "spawn_interval_s": 6,
    "speed_multiplier": 2.0,  # 1, 2, 5, 10
}


def _record_feed(event_type: str, message: str, incident_code: str = "", ambulance: str = ""):
    entry = {
        "ts": datetime.utcnow().strftime("%H:%M:%S"),
        "type": event_type,
        "incident_code": incident_code,
        "ambulance": ambulance,
        "message": message,
    }
    _activity_feed.appendleft(entry)
    return entry


async def _broadcast(payload: dict):
    try:
        from app.main import ws_manager
        await ws_manager.broadcast(payload)
    except Exception as exc:
        print(f"[LiveSim] Broadcast error: {exc}")


async def _wait_if_paused(seconds: float):
    """Sleep scaled by speed_multiplier while honoring pause/stop."""
    speed = max(0.5, float(_stats.get("speed_multiplier", 2.0)))
    remaining = max(0.15, seconds / speed)
    step = 0.2
    while remaining > 0 and _sim_running:
        if _sim_paused:
            await asyncio.sleep(0.25)
            continue
        dt = min(step, remaining)
        await asyncio.sleep(dt)
        remaining -= dt


async def ensure_simulated_citizens():
    """Idempotently seed multiple Hubballi citizen accounts into public.users."""
    pw_hash = hash_password("citizen123")
    async with AsyncSessionLocal() as db:
        for email, full_name, _area in SIM_CITIZENS:
            await db.execute(
                text("""
                    INSERT INTO public.users (email, password_hash, name, role, is_active)
                    VALUES (:email, :pw, :name, 'CITIZEN', TRUE)
                    ON CONFLICT (email) DO NOTHING
                """),
                {"email": email, "pw": pw_hash, "name": full_name},
            )
        await db.commit()


async def _transition_state(
    eid: str,
    aid: Optional[str],
    old_status: str,
    new_status: str,
    remarks: str,
    incident_code: str = "",
    call_sign: str = "",
    extra_broadcast: Optional[dict] = None,
):
    """Atomically persist state transition in emergencies, ambulances, and emergency_events."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE public.emergencies SET status = :st WHERE emergency_id = CAST(:eid AS uuid)"),
            {"st": new_status, "eid": eid},
        )
        if aid:
            amb_st = "AVAILABLE" if new_status == "COMPLETED" else new_status
            await db.execute(
                text("UPDATE public.ambulances SET status = :st WHERE ambulance_id = CAST(:aid AS uuid)"),
                {"st": amb_st, "aid": aid},
            )
        await db.execute(
            text("""
                INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by_email, remarks)
                VALUES (CAST(:eid AS uuid), :old, :new, 'auto-dispatch@iers.gov.in', :rem)
            """),
            {"eid": eid, "old": old_status, "new": new_status, "rem": remarks},
        )
        await db.commit()

    feed_entry = _record_feed(new_status, remarks, incident_code, call_sign)
    msg = {
        "type": "CREW_STATUS_UPDATE",
        "incident_id": eid,
        "incident_code": incident_code,
        "ambulance_id": aid,
        "ambulance_callsign": call_sign,
        "status": new_status,
        "feed": feed_entry,
    }
    if extra_broadcast:
        msg.update(extra_broadcast)
    await _broadcast(msg)


async def _drive_leg(
    eid: str,
    aid: str,
    call_sign: str,
    coords: List[List[float]],
    total_dist_m: float,
    leg_name: str,
    stage_status: str,
):
    """Step an ambulance smoothly along real pgRouting coordinates with periodic DB writes."""
    if not coords:
        return
    max_steps = 30
    stride = max(1, len(coords) // max_steps)
    sampled = coords[::stride]
    if sampled[-1] != coords[-1]:
        sampled.append(coords[-1])

    total_pts = len(sampled)
    for idx, pt in enumerate(sampled):
        if not _sim_running:
            return
        while _sim_paused and _sim_running:
            await asyncio.sleep(0.25)
        if not _sim_running:
            return

        lat, lon = float(pt[0]), float(pt[1])
        frac = (idx + 1) / total_pts
        rem_m = max(0.0, total_dist_m * (1.0 - frac))
        eta_s = max(0, int(rem_m / 12.0))
        progress_pct = round(frac * 100.0, 1)

        # Periodic DB persistence (every 3rd step + final point) to avoid per-frame write flooding
        if idx % 3 == 0 or idx == total_pts - 1:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("""
                        UPDATE public.ambulances
                        SET current_location = ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision), CAST(:lat AS double precision)), 4326),
                            last_location_update = NOW()
                        WHERE ambulance_id = CAST(:aid AS uuid)
                    """),
                    {"lon": lon, "lat": lat, "aid": aid},
                )
                await db.execute(
                    text("""
                        INSERT INTO public.ambulance_location_history (ambulance_id, latitude, longitude, is_simulated)
                        VALUES (CAST(:aid AS uuid), :lat, :lon, TRUE)
                    """),
                    {"aid": aid, "lon": lon, "lat": lat},
                )
                await db.execute(
                    text("""
                        UPDATE public.emergencies
                        SET eta_seconds = :eta, remaining_distance_m = :rem
                        WHERE emergency_id = CAST(:eid AS uuid)
                    """),
                    {"eta": eta_s, "rem": round(rem_m, 1), "eid": eid},
                )
                await db.commit()

        speed = max(0.5, float(_stats.get("speed_multiplier", 2.0)))
        step_ms = int(max(220, 1600 / speed))
        await _broadcast({
            "type": "AMBULANCE_LOCATION",
            "ambulance_id": aid,
            "ambulance_callsign": call_sign,
            "incident_id": eid,
            "lat": lat,
            "lon": lon,
            "eta_seconds": eta_s,
            "remaining_distance_m": round(rem_m, 1),
            "progress_pct": progress_pct,
            "leg": leg_name,
            "status": stage_status,
            "step_ms": step_ms,
            "is_simulated": True,
        })
        await _wait_if_paused(1.6)


async def _rank_best_ambulance(db, inc_lat: float, inc_lon: float, inc_node: int, priority: str):
    """Select top 3 spatially nearest AVAILABLE ambulances and rank by real pgRouting A* ETA + suitability."""
    candidates = (await db.execute(
        text("""
            SELECT a.ambulance_id::text, a.call_sign, a.vehicle_type,
                   (SELECT n.node_id FROM public.road_nodes n ORDER BY n.location <-> a.current_location::geometry LIMIT 1) AS amb_node_id
            FROM public.ambulances a
            WHERE a.status = 'AVAILABLE'
            ORDER BY a.current_location::geometry <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
            LIMIT 3
        """),
        {"lon": inc_lon, "lat": inc_lat},
    )).mappings().all()

    best = None
    best_score = 1e18
    for c in candidates:
        if not c["amb_node_id"]:
            continue
        route = await compute_pgrouting_path(
            db, int(c["amb_node_id"]), int(inc_node),
            algorithm="ASTAR", vehicle_mode="AMBULANCE",
        )
        if not route or not route.get("coordinates"):
            continue
        eta = float(route["total_duration_seconds"])
        # Prefer ALS/TRAUMA for P1 emergencies
        suitability_bonus = -30.0 if (priority == "P1" and (c["vehicle_type"] or "").upper() in ("ALS", "TRAUMA")) else 0.0
        score = eta + suitability_bonus
        if score < best_score:
            best_score = score
            best = (c, route)
    return best


async def _select_best_hospital(db, inc_lat: float, inc_lon: float, inc_node: int, priority: str):
    """Select most suitable Hubballi hospital using road-network ETA + ICU/bed capacity + trauma level."""
    candidates = (await db.execute(
        text("""
            SELECT hospital_id::text, name, nearest_node_id, icu_available, total_beds, trauma_level,
                   ST_Y(location::geometry) AS hlat, ST_X(location::geometry) AS hlon
            FROM public.hospitals
            WHERE nearest_node_id IS NOT NULL
              AND COALESCE(total_beds, 1) > 0
            ORDER BY location::geometry <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
            LIMIT 4
        """),
        {"lon": inc_lon, "lat": inc_lat},
    )).mappings().all()

    best = None
    best_score = 1e18
    for h in candidates:
        route = await compute_pgrouting_path(
            db, int(inc_node), int(h["nearest_node_id"]),
            algorithm="ASTAR", vehicle_mode="AMBULANCE",
        )
        if not route or not route.get("coordinates"):
            continue
        eta = float(route["total_duration_seconds"])
        icu = int(h["icu_available"] or 0)
        trauma = int(h["trauma_level"] or 3)
        # Penalize hospitals with 0 ICU beds for P1 emergencies
        cap_penalty = 180.0 if (priority == "P1" and icu <= 0) else 0.0
        trauma_bonus = -25.0 if (priority == "P1" and trauma <= 2) else 0.0
        score = eta + cap_penalty + trauma_bonus
        if score < best_score:
            best_score = score
            best = (h, route)
    return best


async def _run_autonomous_incident(eid: str):
    """Drives a simulated emergency through all 11 lifecycle states to completion."""
    aid = None
    call_sign = ""
    code = ""
    try:
        await _wait_if_paused(2.0)
        if not _sim_running:
            return

        async with AsyncSessionLocal() as db:
            inc = (await db.execute(
                text("""
                    SELECT emergency_id::text, incident_code, status, severity, nearest_node_id,
                           ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon
                    FROM public.emergencies
                    WHERE emergency_id = CAST(:eid AS uuid)
                """),
                {"eid": eid},
            )).mappings().first()
            if not inc or inc["status"] not in ("RECEIVED", "REPORTED") or not inc["nearest_node_id"]:
                return

            code = inc["incident_code"]
            ranked = await _rank_best_ambulance(db, float(inc["lat"]), float(inc["lon"]), int(inc["nearest_node_id"]), inc["severity"])
            if not ranked:
                return
            amb, leg1 = ranked
            aid = amb["ambulance_id"]
            call_sign = amb["call_sign"]

            # Atomically reserve ambulance (FOR UPDATE prevents double-assignment)
            locked = (await db.execute(
                text("SELECT status FROM public.ambulances WHERE ambulance_id = CAST(:aid AS uuid) FOR UPDATE"),
                {"aid": aid},
            )).scalar()
            if locked != "AVAILABLE":
                return

            eta1 = max(15, int(round(leg1["total_duration_seconds"])))
            await db.execute(
                text("UPDATE public.ambulances SET status = 'ASSIGNED' WHERE ambulance_id = CAST(:aid AS uuid)"),
                {"aid": aid},
            )
            disp_id = (await db.execute(
                text("""
                    INSERT INTO public.dispatches (emergency_id, ambulance_id, status)
                    VALUES (CAST(:eid AS uuid), CAST(:aid AS uuid), 'ACTIVE')
                    RETURNING dispatch_id::text
                """),
                {"eid": eid, "aid": aid},
            )).scalar()
            await db.execute(
                text("""
                    UPDATE public.emergencies
                    SET assigned_ambulance_id = CAST(:aid AS uuid),
                        status = 'ASSIGNED', active_leg = 'LEG_1',
                        active_route_json = CAST(:rjson AS jsonb),
                        eta_seconds = :eta, remaining_distance_m = :rem,
                        dispatched_at = NOW()
                    WHERE emergency_id = CAST(:eid AS uuid)
                """),
                {"aid": aid, "rjson": json.dumps(leg1), "eta": eta1, "rem": leg1["total_distance_meters"], "eid": eid},
            )
            await db.execute(
                text("""
                    INSERT INTO public.route_history (dispatch_id, algorithm, route_geom, distance_m, estimated_time_s, network_version)
                    VALUES (CAST(:did AS uuid), 'ASTAR', ST_SetSRID(ST_GeomFromGeoJSON(:gjson), 4326), :dm, :ts, 'hubballi-live-sim')
                """),
                {"did": disp_id, "gjson": json.dumps(leg1["geojson"]["geometry"]), "dm": leg1["total_distance_meters"], "ts": leg1["total_duration_seconds"]},
            )
            await db.execute(
                text("""
                    INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by_email, remarks)
                    VALUES (CAST(:eid AS uuid), 'RECEIVED', 'ASSIGNED', 'auto-dispatch@iers.gov.in', :rem)
                """),
                {"eid": eid, "rem": f"Assigned {call_sign} (Leg 1 ETA {eta1}s via pgRouting A*)"},
            )
            await db.commit()

        feed_entry = _record_feed("ASSIGNED", f"{call_sign} assigned to {code} (ETA {eta1}s)", code, call_sign)
        await _broadcast({
            "type": "DISPATCH_ASSIGNED",
            "incident_id": eid,
            "incident_code": code,
            "ambulance_id": aid,
            "ambulance_callsign": call_sign,
            "eta_seconds": eta1,
            "remaining_distance_m": leg1["total_distance_meters"],
            "route_coords": leg1["coordinates"],
            "leg": "LEG_1",
            "feed": feed_entry,
        })

        # 1. EN_ROUTE_TO_EMERGENCY (Leg 1)
        await _wait_if_paused(1.5)
        if not _sim_running:
            return
        await _transition_state(eid, aid, "ASSIGNED", "EN_ROUTE_TO_EMERGENCY", f"{call_sign} en route to {code}", code, call_sign)
        await _drive_leg(eid, aid, call_sign, leg1["coordinates"], leg1["total_distance_meters"], "LEG_1", "EN_ROUTE_TO_EMERGENCY")
        if not _sim_running:
            return

        # 2. ARRIVED_AT_EMERGENCY -> PICKUP_IN_PROGRESS -> PATIENT_ONBOARD
        await _transition_state(eid, aid, "EN_ROUTE_TO_EMERGENCY", "ARRIVED_AT_EMERGENCY", f"{call_sign} arrived at scene ({code})", code, call_sign)
        await _wait_if_paused(1.5)
        if not _sim_running:
            return
        await _transition_state(eid, aid, "ARRIVED_AT_EMERGENCY", "PICKUP_IN_PROGRESS", f"{call_sign} stabilizing & loading patient", code, call_sign)
        await _wait_if_paused(2.0)
        if not _sim_running:
            return
        await _transition_state(eid, aid, "PICKUP_IN_PROGRESS", "PATIENT_ONBOARD", f"Patient onboard {call_sign}; selecting suitable hospital", code, call_sign)

        # 3. Select best suitable hospital & compute NEW Leg 2 route
        async with AsyncSessionLocal() as db:
            hosp_choice = await _select_best_hospital(db, float(inc["lat"]), float(inc["lon"]), int(inc["nearest_node_id"]), inc["severity"])
            if not hosp_choice:
                return
            hosp, leg2 = hosp_choice
            hid = hosp["hospital_id"]
            hname = hosp["name"]
            eta2 = max(15, int(round(leg2["total_duration_seconds"])))

            await db.execute(
                text("UPDATE public.dispatches SET hospital_id = CAST(:hid AS uuid) WHERE dispatch_id = CAST(:did AS uuid)"),
                {"hid": hid, "did": disp_id},
            )
            await db.execute(
                text("""
                    UPDATE public.emergencies
                    SET target_hospital_id = CAST(:hid AS uuid),
                        status = 'EN_ROUTE_TO_HOSPITAL', active_leg = 'LEG_2',
                        active_route_json = CAST(:rjson AS jsonb),
                        eta_seconds = :eta, remaining_distance_m = :rem
                    WHERE emergency_id = CAST(:eid AS uuid)
                """),
                {"hid": hid, "rjson": json.dumps(leg2), "eta": eta2, "rem": leg2["total_distance_meters"], "eid": eid},
            )
            await db.execute(
                text("UPDATE public.ambulances SET status = 'EN_ROUTE_TO_HOSPITAL' WHERE ambulance_id = CAST(:aid AS uuid)"),
                {"aid": aid},
            )
            await db.execute(
                text("""
                    INSERT INTO public.route_history (dispatch_id, algorithm, route_geom, distance_m, estimated_time_s, network_version)
                    VALUES (CAST(:did AS uuid), 'ASTAR', ST_SetSRID(ST_GeomFromGeoJSON(:gjson), 4326), :dm, :ts, 'hubballi-live-sim-leg2')
                """),
                {"did": disp_id, "gjson": json.dumps(leg2["geojson"]["geometry"]), "dm": leg2["total_distance_meters"], "ts": leg2["total_duration_seconds"]},
            )
            await db.execute(
                text("""
                    INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by_email, remarks)
                    VALUES (CAST(:eid AS uuid), 'PATIENT_ONBOARD', 'EN_ROUTE_TO_HOSPITAL', 'auto-dispatch@iers.gov.in', :rem)
                """),
                {"eid": eid, "rem": f"{call_sign} transporting patient to {hname} (Leg 2 ETA {eta2}s)"},
            )
            await db.commit()

        feed_entry = _record_feed("EN_ROUTE_TO_HOSPITAL", f"{call_sign} -> {hname} (ETA {eta2}s)", code, call_sign)
        await _broadcast({
            "type": "CREW_STATUS_UPDATE",
            "incident_id": eid,
            "incident_code": code,
            "ambulance_id": aid,
            "ambulance_callsign": call_sign,
            "hospital_id": hid,
            "hospital_name": hname,
            "status": "EN_ROUTE_TO_HOSPITAL",
            "eta_seconds": eta2,
            "remaining_distance_m": leg2["total_distance_meters"],
            "route_coords": leg2["coordinates"],
            "leg": "LEG_2",
            "feed": feed_entry,
        })

        # 4. Drive Leg 2 to Hospital
        await _drive_leg(eid, aid, call_sign, leg2["coordinates"], leg2["total_distance_meters"], "LEG_2", "EN_ROUTE_TO_HOSPITAL")
        if not _sim_running:
            return

        # 5. ARRIVED_AT_HOSPITAL -> HANDOVER_IN_PROGRESS -> COMPLETED -> AVAILABLE
        await _transition_state(eid, aid, "EN_ROUTE_TO_HOSPITAL", "ARRIVED_AT_HOSPITAL", f"{call_sign} arrived at {hname}", code, call_sign)
        await _wait_if_paused(1.5)
        if not _sim_running:
            return
        await _transition_state(eid, aid, "ARRIVED_AT_HOSPITAL", "HANDOVER_IN_PROGRESS", f"Hospital handover in progress at {hname}", code, call_sign)
        await _wait_if_paused(2.0)
        if not _sim_running:
            return

        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE public.emergencies SET status = 'COMPLETED', resolved_at = NOW(), eta_seconds = 0, remaining_distance_m = 0 WHERE emergency_id = CAST(:eid AS uuid)"),
                {"eid": eid},
            )
            await db.execute(
                text("UPDATE public.ambulances SET status = 'AVAILABLE' WHERE ambulance_id = CAST(:aid AS uuid)"),
                {"aid": aid},
            )
            await db.execute(
                text("UPDATE public.dispatches SET status = 'COMPLETED' WHERE dispatch_id = CAST(:did AS uuid)"),
                {"did": disp_id},
            )
            await db.execute(
                text("""
                    INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by_email, remarks)
                    VALUES (CAST(:eid AS uuid), 'HANDOVER_IN_PROGRESS', 'COMPLETED', 'auto-dispatch@iers.gov.in', :rem)
                """),
                {"eid": eid, "rem": f"Handover confirmed at {hname}; {call_sign} returned to AVAILABLE"},
            )
            await db.commit()

        _stats["completed_count"] += 1
        feed_entry = _record_feed("COMPLETED", f"{code} completed at {hname}; {call_sign} AVAILABLE", code, call_sign)
        await _broadcast({
            "type": "INCIDENT_COMPLETED",
            "incident_id": eid,
            "incident_code": code,
            "ambulance_id": aid,
            "ambulance_callsign": call_sign,
            "feed": feed_entry,
        })
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        print(f"[LiveSim] Mission {eid} error: {exc}")
    finally:
        _active_mission_tasks.pop(eid, None)


async def _spawn_one_emergency() -> Optional[str]:
    """Create a random emergency from a random Hubballi citizen at a random Hubballi road node."""
    async with AsyncSessionLocal() as db:
        citizen = (await db.execute(
            text("SELECT user_id::text, email, name AS full_name FROM public.users WHERE role = 'CITIZEN' ORDER BY random() LIMIT 1")
        )).mappings().first()
        node = (await db.execute(
            text("SELECT node_id, ST_Y(location) AS lat, ST_X(location) AS lon FROM public.road_nodes ORDER BY random() LIMIT 1")
        )).mappings().first()
        if not citizen or not node:
            return None

        priority, _etype, title = random.choice(EMERGENCY_TEMPLATES)
        area = next((a for e, _n, a in SIM_CITIZENS if e == citizen["email"]), "Hubballi Central")
        code = f"SIM-{uuid.uuid4().hex[:6].upper()}"
        desc = f"{title} near {area} (Reported by {citizen['full_name']})"
        prio_score = 95 if priority == "P1" else (75 if priority == "P2" else 50)

        eid = (await db.execute(
            text("""
                INSERT INTO public.emergencies (
                    incident_code, reported_by, reported_by_email, location,
                    latitude, longitude, nearest_node_id, incident_type,
                    severity, priority_score, people_affected, description,
                    status, caller_name, caller_phone, needs_review, location_source
                ) VALUES (
                    :code, CAST(:uid AS uuid), :em,
                    ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision), CAST(:lat AS double precision)), 4326),
                    :lat, :lon, :nid, :title,
                    :prio, :pscore, 1, :desc,
                    'RECEIVED', :cname, '112', FALSE, 'SIMULATED_CITIZEN'
                )
                RETURNING emergency_id::text
            """),
            {
                "code": code, "uid": citizen["user_id"], "em": citizen["email"],
                "lon": float(node["lon"]), "lat": float(node["lat"]),
                "nid": str(node["node_id"]), "title": title,
                "prio": priority, "pscore": prio_score, "desc": desc,
                "cname": citizen["full_name"],
            },
        )).scalar()

        await db.execute(
            text("""
                INSERT INTO public.emergency_events (emergency_id, old_status, new_status, changed_by, changed_by_email, remarks)
                VALUES (CAST(:eid AS uuid), NULL, 'RECEIVED', CAST(:uid AS uuid), :em, :rem)
            """),
            {"eid": eid, "uid": citizen["user_id"], "em": citizen["email"], "rem": desc},
        )
        await db.commit()

    _stats["spawned_count"] += 1
    feed_entry = _record_feed("RECEIVED", f"New {priority} {title} near {area}", code, "")
    await _broadcast({
        "type": "NEW_EMERGENCY",
        "incident_id": eid,
        "incident_code": code,
        "priority": priority,
        "description": desc,
        "lat": float(node["lat"]),
        "lon": float(node["lon"]),
        "feed": feed_entry,
    })
    return eid


async def _simulation_loop():
    global _sim_spawning
    await ensure_simulated_citizens()
    while _sim_spawning:
        try:
            if _sim_paused:
                await asyncio.sleep(0.4)
                continue
            done_ids = [k for k, t in _active_mission_tasks.items() if t.done()]
            for k in done_ids:
                _active_mission_tasks.pop(k, None)

            if len(_active_mission_tasks) < _stats["max_concurrent"]:
                eid = await _spawn_one_emergency()
                if eid:
                    _active_mission_tasks[eid] = asyncio.create_task(_run_autonomous_incident(eid))
        except asyncio.CancelledError:
            break
        except Exception as exc:
            print(f"[LiveSim] Loop error: {exc}")
        await _wait_if_paused(float(_stats["spawn_interval_s"]))


async def start_simulation(
    max_concurrent: int = 4,
    spawn_interval_s: int = 6,
    speed_multiplier: float = 2.0,
) -> Dict[str, Any]:
    global _sim_running, _sim_spawning, _sim_paused, _sim_loop_task
    _stats["max_concurrent"] = max(1, min(8, int(max_concurrent)))
    _stats["spawn_interval_s"] = max(3, min(30, int(spawn_interval_s)))
    _stats["speed_multiplier"] = max(1.0, min(10.0, float(speed_multiplier)))
    _sim_paused = False
    _sim_running = True
    if _sim_spawning and _sim_loop_task and not _sim_loop_task.done():
        return get_simulation_status()
    _sim_spawning = True
    _stats["started_at"] = datetime.utcnow().isoformat() + "Z"
    _sim_loop_task = asyncio.create_task(_simulation_loop())
    return get_simulation_status()


async def pause_simulation() -> Dict[str, Any]:
    global _sim_paused
    if _sim_running:
        _sim_paused = True
    return get_simulation_status()


async def resume_simulation() -> Dict[str, Any]:
    global _sim_paused
    if _sim_running:
        _sim_paused = False
    return get_simulation_status()


async def update_simulation_config(
    speed_multiplier: Optional[float] = None,
    max_concurrent: Optional[int] = None,
    spawn_interval_s: Optional[int] = None,
) -> Dict[str, Any]:
    if speed_multiplier is not None:
        _stats["speed_multiplier"] = max(1.0, min(10.0, float(speed_multiplier)))
    if max_concurrent is not None:
        _stats["max_concurrent"] = max(1, min(8, int(max_concurrent)))
    if spawn_interval_s is not None:
        _stats["spawn_interval_s"] = max(3, min(30, int(spawn_interval_s)))
    return get_simulation_status()


async def stop_simulation() -> Dict[str, Any]:
    """Stop spawning NEW emergencies while letting already-dispatched ambulances finish their routes cleanly."""
    global _sim_spawning, _sim_paused, _sim_loop_task
    _sim_spawning = False
    _sim_paused = False
    if _sim_loop_task and not _sim_loop_task.done():
        _sim_loop_task.cancel()
    _sim_loop_task = None
    return get_simulation_status()


async def reset_demo_scenario() -> Dict[str, Any]:
    """Explicitly stop simulation, cancel in-flight SIM-* missions, and release all ambulances to AVAILABLE."""
    global _sim_running, _sim_spawning, _sim_paused
    await stop_simulation()
    _sim_running = False
    _sim_spawning = False
    _sim_paused = False
    for t in list(_active_mission_tasks.values()):
        if not t.done():
            t.cancel()
    _active_mission_tasks.clear()
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE public.emergencies SET status = 'COMPLETED', resolved_at = NOW() WHERE incident_code LIKE 'SIM-%' AND status NOT IN ('COMPLETED','CANCELLED')"))
        await db.execute(text("UPDATE public.dispatches SET status = 'COMPLETED' WHERE status = 'ACTIVE'"))
        await db.execute(text("UPDATE public.ambulances SET status = 'AVAILABLE'"))
        await db.commit()
    _stats["spawned_count"] = 0
    _stats["completed_count"] = 0
    _activity_feed.clear()
    _record_feed("RESET", "Demo scenario reset; all Hubballi ambulances returned to AVAILABLE")
    return get_simulation_status()


def get_simulation_status() -> Dict[str, Any]:
    return {
        "running": _sim_spawning,
        "paused": _sim_paused,
        "active_missions": len([t for t in _active_mission_tasks.values() if not t.done()]),
        "spawned_count": _stats["spawned_count"],
        "completed_count": _stats["completed_count"],
        "max_concurrent": _stats["max_concurrent"],
        "spawn_interval_s": _stats["spawn_interval_s"],
        "speed_multiplier": _stats["speed_multiplier"],
        "started_at": _stats["started_at"],
        "activity_feed": list(_activity_feed),
    }
