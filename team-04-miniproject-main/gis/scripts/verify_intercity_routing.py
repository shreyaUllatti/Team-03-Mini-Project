import psycopg2
import networkx as nx

conn = psycopg2.connect(
    host='localhost', port=5434, dbname='iers_db',
    user='iers_user', password='iers_dev_local'
)
cur = conn.cursor()

print('Reading road segments for topological graph...')
cur.execute('SELECT source, target, distance_m, travel_time_s, highway FROM iers.roads')
G = nx.Graph()

for s, t, d, time_s, hw in cur:
    if s and t:
        w = time_s if (time_s and time_s > 0) else (d / 10.0 if d else 5.0)
        G.add_edge(s, t, weight=w, distance=d, highway=hw)

cur.close()
conn.close()

print(f'Graph constructed: {G.number_of_nodes()} vertices, {G.number_of_edges()} edges.')

# Check components
components = list(nx.connected_components(G))
print(f'Connected components: {len(components)}')
giant = max(components, key=len)
print(f'Giant connected component: {len(giant)} vertices ({len(giant)/G.number_of_nodes()*100:.1f}%).')

# Verify nodes in Hubballi (lat 15.36) and Dharwad (lat 15.46) belong to the giant component
conn2 = psycopg2.connect(
    host='localhost', port=5434, dbname='iers_db',
    user='iers_user', password='iers_dev_local'
)
cur2 = conn2.cursor()

# Find major trunk/primary node in Dharwad
cur2.execute('''
    SELECT r.source, r.name, r.highway, ST_Y(n.location) as lat, ST_X(n.location) as lon
    FROM iers.roads r
    JOIN iers.road_nodes n ON n.node_id = r.source
    WHERE r.highway IN ('trunk', 'primary', 'secondary')
      AND ST_Y(n.location) > 15.45
    LIMIT 1
''')
dharwad_node, d_name, d_hw, d_lat, d_lon = cur2.fetchone()

# Find major trunk/primary node in Hubballi
cur2.execute('''
    SELECT r.source, r.name, r.highway, ST_Y(n.location) as lat, ST_X(n.location) as lon
    FROM iers.roads r
    JOIN iers.road_nodes n ON n.node_id = r.source
    WHERE r.highway IN ('trunk', 'primary', 'secondary')
      AND ST_Y(n.location) < 15.37
    LIMIT 1
''')
hubli_node, h_name, h_hw, h_lat, h_lon = cur2.fetchone()

cur2.close()
conn2.close()

print(f'Dharwad anchor node: {dharwad_node} ({d_name}, {d_hw}) @ [{d_lat:.4f}, {d_lon:.4f}]')
print(f'Hubballi anchor node: {hubli_node} ({h_name}, {h_hw}) @ [{h_lat:.4f}, {h_lon:.4f}]')

in_dharwad = dharwad_node in giant
in_hubli = hubli_node in giant
print(f'Dharwad node in giant component: {in_dharwad}')
print(f'Hubballi node in giant component: {in_hubli}')

if in_dharwad and in_hubli:
    path = nx.shortest_path(G, source=hubli_node, target=dharwad_node, weight='weight')
    total_dist = sum(G[u][v].get('distance', 0) for u, v in zip(path[:-1], path[1:]))
    total_time = sum(G[u][v].get('weight', 0) for u, v in zip(path[:-1], path[1:]))
    print(f'>>> ROUTE VERIFIED: Hubballi -> Dharwad corridor connected!')
    print(f'    Hops: {len(path)} vertices')
    print(f'    Total distance: {total_dist/1000.0:.2f} km')
    print(f'    Total travel time: {total_time/60.0:.1f} minutes')
