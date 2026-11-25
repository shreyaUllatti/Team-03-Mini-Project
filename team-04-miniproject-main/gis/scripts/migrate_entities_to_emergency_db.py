"""Migrate real OSM hospitals, ambulances, and 4 stakeholder users into
localhost:5432 / emergency_db / schema public (preserving all roads & nodes)."""
import json
import psycopg2

SRC_DSN = "host=localhost port=5434 dbname=iers_db user=iers_user password=iers_dev_local"
DST_DSN = "host=localhost port=5432 dbname=emergency_db user=postgres password=Ankush@2007"


def main():
    src = psycopg2.connect(SRC_DSN)
    dst = psycopg2.connect(DST_DSN)
    sc, dc = src.cursor(), dst.cursor()

    # 1. Hospitals -> public.hospitals (preserving real coordinates & snapping to public.road_nodes)
    sc.execute("""
        SELECT hospital_id, name, latitude, longitude, total_beds, icu_available,
               trauma_beds_available, emergency_dept_capacity, trauma_level, has_helipad,
               has_icu, has_trauma_care, has_cardiology, contact_number, osm_id, city,
               service_status, service_notes
        FROM iers.hospitals ORDER BY hospital_id
    """)
    hosp_map = {}
    for r in sc.fetchall():
        (hcode, name, lat, lon, tb, icu, trb, edc, tlv, heli, hicu, htr, hcar, phone, osm_id, city, sst, snt) = r
        dc.execute("SELECT node_id::text FROM public.road_nodes ORDER BY location <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326) LIMIT 1", (lon, lat))
        nid = dc.fetchone()[0]
        dc.execute("""
            INSERT INTO public.hospitals (
                hospital_code, name, location, latitude, longitude, available_beds, total_beds,
                icu_available, trauma_beds_available, emergency_dept_capacity, trauma_level,
                has_helipad, has_icu, has_trauma_care, has_cardiology, contact_number,
                nearest_node_id, osm_id, city, service_status, service_notes, attributes_simulated
            ) VALUES (
                %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, TRUE
            )
            ON CONFLICT (hospital_code) DO UPDATE SET name = EXCLUDED.name
            RETURNING hospital_id
        """, (hcode, name, lon, lat, lat, lon, tb, tb, icu, trb, edc, tlv, heli, hicu, htr, hcar, phone, nid, osm_id, city, sst, snt))
        hosp_map[hcode] = str(dc.fetchone()[0])

    # 2. Ambulances -> public.ambulances
    sc.execute("""
        SELECT ambulance_id, call_sign, registration_number, vehicle_type, status,
               latitude, longitude, height_meters, width_meters, weight_tons,
               driver_name, capabilities
        FROM iers.ambulances ORDER BY ambulance_id
    """)
    amb_map = {}
    for r in sc.fetchall():
        (acode, cs, reg, vt, st, lat, lon, h, w, wt, drv, caps) = r
        dc.execute("SELECT node_id::text FROM public.road_nodes ORDER BY location <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326) LIMIT 1", (lon, lat))
        nid = dc.fetchone()[0]
        dc.execute("""
            INSERT INTO public.ambulances (
                ambulance_code, registration_number, call_sign, current_location,
                latitude, longitude, status, ambulance_type, vehicle_type,
                capabilities, current_node_id, height_meters, width_meters, weight_tons, driver_name
            ) VALUES (
                %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                %s, %s, 'AVAILABLE', %s, %s,
                %s::jsonb, %s, %s, %s, %s, %s
            )
            ON CONFLICT (ambulance_code) DO UPDATE SET call_sign = EXCLUDED.call_sign
            RETURNING ambulance_id
        """, (acode, reg or f"KA-25-{acode}", cs, lon, lat, lat, lon, "Advanced" if vt == "ALS" else "Basic", vt, json.dumps(caps), nid, h, w, wt, drv))
        amb_map[acode] = str(dc.fetchone()[0])

    # 3. Users -> public.users
    sc.execute("SELECT name, email, password_hash, role, assigned_entity_id FROM iers.users")
    for name, email, pwh, role, eid in sc.fetchall():
        mapped_eid = hosp_map.get(eid) or amb_map.get(eid) or eid
        dc.execute("""
            INSERT INTO public.users (name, email, password_hash, role, assigned_entity_id, is_active)
            VALUES (%s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role, assigned_entity_id = EXCLUDED.assigned_entity_id
        """, (name, email, pwh, role, mapped_eid))

    dst.commit()
    for t in ["hospitals", "ambulances", "users", "emergencies", "dispatches", "emergency_events"]:
        dc.execute(f"SELECT count(*) FROM public.{t}")
        print(f"emergency_db.public.{t}: {dc.fetchone()[0]}")
    src.close()
    dst.close()


if __name__ == "__main__":
    main()
