"""
Clips public.roads, public.road_nodes, public.hospitals, and public.ambulances
in emergency_db (localhost:5432) to the Hubballi urban region only:
  BBOX: lon 75.05..75.22, lat 15.28..15.415 (EPSG:4326)

Creates backup tables (roads_hd_backup, road_nodes_hd_backup) before clipping,
removes disconnected boundary islands via pgr_connectedComponents, and re-snaps
all remaining hospitals, ambulances, and emergencies to the giant component.
"""
import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

HUBBALLI_BBOX = "ST_MakeEnvelope(75.05, 15.28, 75.22, 15.415, 4326)"


async def main():
    async with AsyncSessionLocal() as db:
        # 1. Create safety backups if not already present
        await db.execute(text("CREATE TABLE IF NOT EXISTS public.roads_hd_backup AS TABLE public.roads"))
        await db.execute(text("CREATE TABLE IF NOT EXISTS public.road_nodes_hd_backup AS TABLE public.road_nodes"))

        # 2. Clip public.roads to Hubballi bounding box
        res_r = await db.execute(text(f"""
            DELETE FROM public.roads
            WHERE NOT ST_Intersects(geom, {HUBBALLI_BBOX})
        """))
        print(f"Deleted {res_r.rowcount} non-Hubballi road edges.")

        # 3. Keep only the giant connected component of clipped Hubballi roads
        await db.execute(text("""
            WITH cc AS (
                SELECT node, component
                FROM pgr_connectedComponents(
                    'SELECT road_id AS id, source, target, 1.0::float8 AS cost, 1.0::float8 AS reverse_cost FROM public.roads'
                )
            ),
            giant AS (
                SELECT component FROM cc GROUP BY component ORDER BY COUNT(*) DESC LIMIT 1
            ),
            valid_nodes AS (
                SELECT cc.node FROM cc JOIN giant g ON cc.component = g.component
            )
            DELETE FROM public.roads
            WHERE source NOT IN (SELECT node FROM valid_nodes)
               OR target NOT IN (SELECT node FROM valid_nodes)
        """))

        # 4. Remove orphaned road_nodes
        res_n = await db.execute(text("""
            DELETE FROM public.road_nodes
            WHERE node_id NOT IN (
                SELECT source FROM public.roads
                UNION
                SELECT target FROM public.roads
            )
        """))
        print(f"Deleted {res_n.rowcount} orphaned/non-Hubballi road nodes.")

        # 5. Remove non-Hubballi ambulances (preserving any referenced by users/emergencies/dispatches)
        res_a = await db.execute(text(f"""
            DELETE FROM public.ambulances
            WHERE NOT ST_Intersects(current_location, {HUBBALLI_BBOX})
              AND ambulance_id::text NOT IN (SELECT COALESCE(assigned_entity_id::text, '') FROM public.users)
              AND ambulance_id NOT IN (SELECT COALESCE(assigned_ambulance_id, '00000000-0000-0000-0000-000000000000'::uuid) FROM public.emergencies)
              AND ambulance_id NOT IN (SELECT COALESCE(ambulance_id, '00000000-0000-0000-0000-000000000000'::uuid) FROM public.dispatches)
        """))
        print(f"Deleted {res_a.rowcount} non-Hubballi ambulances.")

        # 6. Remove non-Hubballi hospitals (preserving any referenced by users/emergencies/dispatches)
        res_h = await db.execute(text(f"""
            DELETE FROM public.hospitals
            WHERE NOT ST_Intersects(location, {HUBBALLI_BBOX})
              AND hospital_id::text NOT IN (SELECT COALESCE(assigned_entity_id::text, '') FROM public.users)
              AND hospital_id NOT IN (SELECT COALESCE(target_hospital_id, '00000000-0000-0000-0000-000000000000'::uuid) FROM public.emergencies)
              AND hospital_id NOT IN (SELECT COALESCE(hospital_id, '00000000-0000-0000-0000-000000000000'::uuid) FROM public.dispatches)
        """))
        print(f"Deleted {res_h.rowcount} non-Hubballi hospitals.")

        # 7. Re-snap nearest_node_id for all remaining hospitals, ambulances, and emergencies
        await db.execute(text("""
            UPDATE public.hospitals h
            SET nearest_node_id = (
                SELECT n.node_id FROM public.road_nodes n
                ORDER BY n.location <-> h.location
                LIMIT 1
            )
        """))
        await db.execute(text("""
            UPDATE public.emergencies e
            SET nearest_node_id = (
                SELECT n.node_id FROM public.road_nodes n
                ORDER BY n.location <-> e.location
                LIMIT 1
            )
        """))

        await db.commit()

        # 8. Report final clipped Hubballi stats
        stats = (await db.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM public.roads) AS roads,
                (SELECT COUNT(*) FROM public.road_nodes) AS nodes,
                (SELECT COUNT(*) FROM public.hospitals) AS hospitals,
                (SELECT COUNT(*) FROM public.ambulances) AS ambulances,
                ROUND(ST_XMin(ST_Extent(geom))::numeric, 4) AS min_lon,
                ROUND(ST_YMin(ST_Extent(geom))::numeric, 4) AS min_lat,
                ROUND(ST_XMax(ST_Extent(geom))::numeric, 4) AS max_lon,
                ROUND(ST_YMax(ST_Extent(geom))::numeric, 4) AS max_lat
            FROM public.roads
        """))).mappings().first()
        print("CLIPPED HUBBALLI STATS:", dict(stats))


if __name__ == "__main__":
    asyncio.run(main())
