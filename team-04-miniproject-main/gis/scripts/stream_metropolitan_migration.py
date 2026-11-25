import psycopg2
import sys

src_conn = psycopg2.connect(
    host='localhost', port=5432, dbname='emergency_db',
    user='postgres', password='Ankush@2007'
)
dst_conn = psycopg2.connect(
    host='localhost', port=5434, dbname='iers_db',
    user='iers_user', password='iers_dev_local'
)

print('Connected to source (5432) and destination (5434).')

def copy_table(src_tbl, dst_tbl, cols):
    src_cur = src_conn.cursor('read_cursor')
    dst_cur = dst_conn.cursor()
    
    col_str = ', '.join(f'"{c}"' for c in cols)
    src_cur.execute(f'SELECT {col_str} FROM public.{src_tbl}')
    
    placeholders = ', '.join(['%s'] * len(cols))
    insert_sql = f'INSERT INTO iers.{dst_tbl} ({col_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
    
    batch = []
    count = 0
    for row in src_cur:
        batch.append(row)
        if len(batch) >= 1000:
            dst_cur.executemany(insert_sql, batch)
            dst_conn.commit()
            count += len(batch)
            print(f'Migrated {count} rows into iers.{dst_tbl}...')
            batch = []
    if batch:
        dst_cur.executemany(insert_sql, batch)
        dst_conn.commit()
        count += len(batch)
    
    print(f'Finished {dst_tbl}: {count} total rows.')
    src_cur.close()
    dst_cur.close()

# 1. Road nodes
copy_table('road_nodes', 'road_nodes', ['node_id', 'location'])

# 2. Roads
road_cols = [
    'road_id', 'osm_id', 'name', 'highway', 'other_tags', 'geom',
    'distance_m', 'speed_limit', 'travel_time_s', 'reverse_cost',
    'is_blocked', 'source', 'target', 'traffic_level',
    'traffic_multiplier', 'current_travel_time_s'
]
copy_table('roads', 'roads', road_cols)

# 3. Roads raw
raw_cols = [
    'road_id', 'osm_id', 'name', 'highway', 'waterway', 'aerialway',
    'barrier', 'man_made', 'railway', 'z_order', 'other_tags', 'geom'
]
copy_table('roads_raw', 'roads_raw', raw_cols)

src_conn.close()
dst_conn.close()
print('Direct migration completed successfully.')
