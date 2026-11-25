"""
Real PostGIS + pgRouting (pgr_dijkstra & pgr_astar) service operating directly
on the 40,394-edge Hubballi-Dharwad metropolitan road network (iers.roads / iers.road_nodes).
"""
import json
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def find_nearest_road_node(db: AsyncSession, lat: float, lon: float) -> Optional[Tuple[int, float]]:
    """PostGIS KNN (<->) lookup for the closest vertex in iers.road_nodes."""
    res = await db.execute(
        text("""
            SELECT node_id,
                   ST_Distance(location::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS dist_m
            FROM public.road_nodes
            ORDER BY location <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
            LIMIT 1
        """),
        {"lat": lat, "lon": lon},
    )
    row = res.fetchone()
    if not row:
        return None
    return int(row[0]), float(row[1])


def _build_edge_sql(
    vehicle_mode: str,
    vehicle_height: float,
    vehicle_width: float,
    vehicle_weight: float,
    penalized_edges: Optional[List[int]] = None,
    include_astar_coords: bool = False,
) -> str:
    """
    Constructs the inner SQL query passed to pgRouting.
    - NORMAL mode: respects all one-way roads (reverse_cost = -1).
    - AMBULANCE mode:
        * Emergency corridor edges get 40% travel-time relief (0.6x).
        * Authorized urban one-way streets (emergency_contraflow_allowed = TRUE)
          can be traversed in reverse with a 1.35x safety penalty.
        * Divided dual carriageways, expressways, bridges, and trunk highways
          remain strictly one-way (reverse_cost = -1) even for ambulances.
    - Blocked roads and edges violating physical clearance are excluded.
    """
    is_amb = vehicle_mode.upper() == "AMBULANCE"
    h = float(vehicle_height)
    w = float(vehicle_width)
    wt = float(vehicle_weight)

    base_cost = (
        "CASE WHEN is_emergency_corridor THEN current_travel_time_s * 0.6 ELSE current_travel_time_s END"
        if is_amb
        else "current_travel_time_s"
    )

    if penalized_edges:
        ids_csv = ",".join(str(int(e)) for e in penalized_edges)
        cost_expr = f"(CASE WHEN road_id IN ({ids_csv}) THEN ({base_cost}) * 2.5 ELSE ({base_cost}) END)"
    else:
        cost_expr = f"({base_cost})"

    if is_amb:
        rev_expr = (
            f"CASE "
            f"WHEN NOT is_oneway THEN {cost_expr} "
            f"WHEN emergency_contraflow_allowed THEN ({cost_expr}) * 1.35 "
            f"ELSE -1 END"
        )
    else:
        rev_expr = f"CASE WHEN is_oneway THEN -1 ELSE {cost_expr} END"

    coords_cols = (
        ", ST_X(ST_StartPoint(geom)) AS x1, ST_Y(ST_StartPoint(geom)) AS y1, "
        "ST_X(ST_EndPoint(geom)) AS x2, ST_Y(ST_EndPoint(geom)) AS y2"
        if include_astar_coords
        else ""
    )

    return (
        f"SELECT road_id AS id, source, target, "
        f"{cost_expr} AS cost, {rev_expr} AS reverse_cost{coords_cols} "
        f"FROM public.roads "
        f"WHERE NOT is_blocked "
        f"AND COALESCE(max_height_m, 4.5) >= {h} "
        f"AND COALESCE(max_width_m, 6.0) >= {w} "
        f"AND COALESCE(max_weight_t, 25.0) >= {wt}"
    )


async def compute_pgrouting_path(
    db: AsyncSession,
    start_node: int,
    end_node: int,
    algorithm: str = "DIJKSTRA",
    vehicle_mode: str = "AMBULANCE",
    vehicle_height: float = 2.4,
    vehicle_width: float = 2.2,
    vehicle_weight: float = 3.5,
    penalized_edges: Optional[List[int]] = None,
) -> Optional[Dict[str, Any]]:
    """Executes real pgRouting pgr_dijkstra or pgr_astar and returns full road geometry & metrics."""
    algo = algorithm.upper()
    if algo not in ("DIJKSTRA", "ASTAR"):
        algo = "DIJKSTRA"
    vmode = "AMBULANCE" if vehicle_mode.upper() == "AMBULANCE" else "NORMAL"

    edge_sql = _build_edge_sql(
        vehicle_mode=vmode,
        vehicle_height=vehicle_height,
        vehicle_width=vehicle_width,
        vehicle_weight=vehicle_weight,
        penalized_edges=penalized_edges,
        include_astar_coords=(algo == "ASTAR"),
    )

    if algo == "ASTAR":
        pgr_call = "pgr_astar(CAST(:edge_sql AS text), CAST(:start_node AS bigint), CAST(:end_node AS bigint), directed := true, heuristic := 2)"
    else:
        pgr_call = "pgr_dijkstra(CAST(:edge_sql AS text), CAST(:start_node AS bigint), CAST(:end_node AS bigint), directed := true)"

    query = text(f"""
        SELECT
            d.seq,
            d.node,
            d.edge,
            d.cost AS step_time_s,
            r.source,
            r.target,
            r.name,
            r.highway,
            r.distance_m,
            r.is_oneway,
            r.emergency_contraflow_allowed,
            r.is_emergency_corridor,
            r.traffic_multiplier,
            ST_AsGeoJSON(
                CASE WHEN d.node = r.source THEN r.geom ELSE ST_Reverse(r.geom) END
            ) AS geom_json
        FROM {pgr_call} d
        JOIN public.roads r ON r.road_id = d.edge
        WHERE d.edge > 0
        ORDER BY d.seq
    """)

    res = await db.execute(
        query,
        {"edge_sql": edge_sql, "start_node": int(start_node), "end_node": int(end_node)},
    )
    rows = res.mappings().all()
    if not rows:
        return None

    coordinates: List[List[float]] = []  # [lat, lon] for Leaflet
    geojson_coords: List[List[float]] = []  # [lon, lat] for GeoJSON
    edge_ids: List[int] = []
    road_names: List[str] = []
    total_dist_m = 0.0
    total_time_s = 0.0
    contraflow_count = 0
    corridor_count = 0

    for row in rows:
        edge_ids.append(int(row["edge"]))
        total_dist_m += float(row["distance_m"] or 0.0)
        total_time_s += float(row["step_time_s"] or 0.0)

        traversed_reverse = int(row["node"]) != int(row["source"])
        if traversed_reverse and row["is_oneway"]:
            contraflow_count += 1
        if row["is_emergency_corridor"]:
            corridor_count += 1

        rname = row["name"] or f"{row['highway'] or 'road'} segment"
        if not road_names or road_names[-1] != rname:
            road_names.append(rname)

        g = json.loads(row["geom_json"])
        pts = g.get("coordinates", [])
        for idx, pt in enumerate(pts):
            lon, lat = float(pt[0]), float(pt[1])
            if idx == 0 and coordinates:
                # avoid duplicating shared vertex
                continue
            coordinates.append([lat, lon])
            geojson_coords.append([lon, lat])

    return {
        "algorithm": algo,
        "vehicle_mode": vmode,
        "start_node": int(start_node),
        "end_node": int(end_node),
        "edge_count": len(edge_ids),
        "edge_ids": edge_ids,
        "total_distance_meters": round(total_dist_m, 1),
        "total_distance_km": round(total_dist_m / 1000.0, 2),
        "total_duration_seconds": round(total_time_s, 1),
        "eta_minutes": round(total_time_s / 60.0, 1),
        "contraflow_edges_used": contraflow_count,
        "corridor_edges_used": corridor_count,
        "road_summary": road_names[:12],
        "coordinates": coordinates,
        "geojson": {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": geojson_coords},
            "properties": {
                "algorithm": algo,
                "vehicle_mode": vmode,
                "distance_km": round(total_dist_m / 1000.0, 2),
                "eta_minutes": round(total_time_s / 60.0, 1),
                "contraflow_edges_used": contraflow_count,
            },
        },
    }
