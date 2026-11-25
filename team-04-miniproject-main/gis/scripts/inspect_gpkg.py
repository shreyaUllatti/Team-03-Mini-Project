import sqlite3

for gpkg in ['campus_roads_export.gpkg', 'roads_raw.gpkg']:
    p = f'C:/Users/acer/Documents/{gpkg}'
    try:
        conn = sqlite3.connect(p)
        cur = conn.cursor()
        cur.execute("SELECT table_name, data_type FROM gpkg_contents;")
        rows = cur.fetchall()
        print(f"=== {gpkg} tables ===")
        for r in rows:
            table_name = r[0]
            print(r)
            cur.execute(f"PRAGMA table_info({table_name});")
            print("  Columns:", [col[1] for col in cur.fetchall()])
            cur.execute(f"SELECT COUNT(*) FROM {table_name};")
            print("  Count:", cur.fetchone()[0])
            cur.execute(f"SELECT * FROM {table_name} LIMIT 2;")
            sample = cur.fetchall()
            print("  Sample row:", sample)
        conn.close()
    except Exception as e:
        print(f"Error reading {gpkg}: {e}")
