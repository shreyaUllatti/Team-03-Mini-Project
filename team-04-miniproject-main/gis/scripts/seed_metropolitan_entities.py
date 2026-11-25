"""Seed real OSM hospitals (preserving exact coordinates), snap ambulances/hospitals
to iers.road_nodes via PostGIS KNN, and seed role-based user accounts."""
import hashlib
import json
import os
import secrets
import psycopg2

DB_DSN = "host=localhost port=5434 dbname=iers_db user=iers_user password=iers_dev_local"
OSM_HOSPITALS_PATH = r"C:\Projects\Intelligent-Emergency-Response\gis\data\osm_hospitals_hubballi_dharwad.json"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256$120000${salt}${dk.hex()}"


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    # 1. Load real OSM hospitals and select verified major medical facilities (excluding veterinary/OPD/scan/mental-only duplicates)
    with open(OSM_HOSPITALS_PATH, "r", encoding="utf-8") as f:
        osm_data = json.load(f)

    exclude_kw = ("veterinary", "homeopathic", "opd", "scan centre", "department of", "infectious", "landmark", "clinic")
    seen_names = set()
    selected = []
    for feat in osm_data["features"]:
        name = (feat.get("name") or "").strip()
        if not name:
            continue
        low = name.lower()
        if any(k in low for k in exclude_kw):
            continue
        if low in seen_names:
            continue
        seen_names.add(low)
        # Prioritize emergency=yes or well-known multi-specialty / government / medical college hospitals
        is_major = (
            feat.get("emergency") == "yes"
            or any(k in low for k in ("kims", "sdm", "kle", "district", "government hospital", "trauma", "multispecialty", "super speciality", "general hospital", "esi", "tatwadarsha", "vivekananda", "shreya", "balaji", "shakuntala"))
        )
        if is_major:
            selected.append(feat)

    # Cap to 20 well-distributed real OSM hospitals across Hubballi & Dharwad
    selected = selected[:20]

    # Update existing 4 hospitals with capability metadata & real KNN node
    cur.execute("""
        UPDATE iers.hospitals
        SET has_icu = TRUE,
            has_trauma_care = (trauma_level = 1),
            has_cardiology = (trauma_level = 1),
            city = CASE WHEN latitude >= 15.41 THEN 'Dharwad' ELSE 'Hubballi' END,
            attributes_simulated = TRUE
    """)

    inserted_hosp = 0
    for idx, feat in enumerate(selected, start=5):
        name = feat["name"].strip()
        lat = float(feat["lat"])
        lon = float(feat["lon"])
        osm_id = f"{feat['osm_type'][0]}{feat['osm_id']}"
        # Skip if very close (<250m) to an already existing hospital
        cur.execute("""
            SELECT hospital_id FROM iers.hospitals
            WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 250)
            LIMIT 1
        """, (lon, lat))
        if cur.fetchone():
            continue

        # Snap to nearest real road node via PostGIS KNN
        cur.execute("""
            SELECT node_id FROM iers.road_nodes
            ORDER BY location <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
            LIMIT 1
        """, (lon, lat))
        node_row = cur.fetchone()
        nearest_node = str(node_row[0]) if node_row else None

        low = name.lower()
        is_t1 = any(k in low for k in ("kims", "sdm", "kle", "trauma", "super speciality", "district"))
        beds = 300 if is_t1 else 120
        icu = 24 if is_t1 else 10
        city = "Dharwad" if lat >= 15.41 else "Hubballi"
        hid = f"HOSP_{idx:02d}"

        cur.execute("""
            INSERT INTO iers.hospitals (
                hospital_id, name, latitude, longitude, total_beds, icu_available,
                trauma_level, has_helipad, geom, nearest_node_id, osm_id,
                has_icu, has_trauma_care, has_cardiology, contact_number, city, attributes_simulated
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s,
                %s, %s, %s, %s, %s, TRUE
            ) ON CONFLICT (hospital_id) DO NOTHING
        """, (
            hid, name, lat, lon, beds, icu,
            1 if is_t1 else 2, is_t1, lon, lat, nearest_node, osm_id,
            True, is_t1, is_t1, feat.get("phone") or "+91-836-2372200", city
        ))
        inserted_hosp += 1

    # Re-snap ALL hospitals & ambulances to exact nearest PostGIS road_node
    cur.execute("""
        UPDATE iers.hospitals h
        SET nearest_node_id = (
            SELECT n.node_id::text FROM iers.road_nodes n
            ORDER BY n.location <-> h.geom LIMIT 1
        )
    """)

    cur.execute("""
        UPDATE iers.ambulances a
        SET current_node_id = (
            SELECT n.node_id::text FROM iers.road_nodes n
            ORDER BY n.location <-> a.geom LIMIT 1
        ),
        registration_number = COALESCE(registration_number, 'KA-25-G-' || LPAD(RIGHT(ambulance_id, 2), 4, '0')),
        capabilities = CASE
            WHEN vehicle_type = 'ALS' THEN '["ALS","DEFIBRILLATOR","VENTILATOR","TRAUMA_KIT"]'::jsonb
            WHEN vehicle_type = 'BLS' THEN '["BLS","OXYGEN","FIRST_AID"]'::jsonb
            ELSE '["RAPID_RESPONSE","AED","FIRST_AID"]'::jsonb
        END
    """)

    # 2. Seed Role-Based Users
    users = [
        ("USR_ADMIN", "System Administrator", "admin@iers.gov.in", "admin123", "ADMIN", None),
        ("USR_DISP", "Metro Chief Dispatcher", "dispatcher@iers.gov.in", "dispatch123", "DISPATCHER", None),
        ("USR_CREW1", "ALS-01 Paramedic Lead", "crew1@iers.gov.in", "crew123", "AMBULANCE_CREW", "AMB_01"),
        ("USR_HOSP1", "KIMS Trauma Coordinator", "hospital1@iers.gov.in", "hospital123", "HOSPITAL_STAFF", "HOSP_01"),
    ]
    for uid, name, email, pw, role, entity_id in users:
        cur.execute("""
            INSERT INTO iers.users (user_id, name, email, password_hash, role, assigned_entity_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE
            SET name = EXCLUDED.name, role = EXCLUDED.role, assigned_entity_id = EXCLUDED.assigned_entity_id
        """, (uid, name, email, hash_password(pw), role, entity_id))

    conn.commit()

    cur.execute("SELECT count(*) FROM iers.hospitals")
    h_cnt = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM iers.ambulances")
    a_cnt = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM iers.users")
    u_cnt = cur.fetchone()[0]
    cur.execute("SELECT count(*) FILTER (WHERE is_oneway), count(*) FILTER (WHERE emergency_contraflow_allowed) FROM iers.roads")
    ow, cf = cur.fetchone()

    print(f"Seed complete: hospitals={h_cnt} (+{inserted_hosp} real OSM), ambulances={a_cnt}, users={u_cnt}, oneway_edges={ow}, emergency_contraflow_edges={cf}")
    conn.close()


if __name__ == "__main__":
    main()
