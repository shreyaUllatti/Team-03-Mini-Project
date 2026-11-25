"""Fetch real hospitals/clinics inside the Hubballi-Dharwad road-network bbox from OpenStreetMap (Overpass)."""
import json, urllib.request, urllib.parse

BBOX = (15.2093, 74.9135, 15.6164, 75.3113)  # S, W, N, E  == ST_Extent(iers.roads)
q = f"""
[out:json][timeout:60];
(
  nwr["amenity"="hospital"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  nwr["healthcare"="hospital"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out center tags;
"""
req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                             data=urllib.parse.urlencode({"data": q}).encode(),
                             headers={"User-Agent": "IERS-academic-project/1.0"})
with urllib.request.urlopen(req, timeout=90) as r:
    data = json.load(r)

out = []
for e in data["elements"]:
    lat = e.get("lat") or e.get("center", {}).get("lat")
    lon = e.get("lon") or e.get("center", {}).get("lon")
    t = e.get("tags", {})
    if lat is None:
        continue
    out.append({"osm_type": e["type"], "osm_id": e["id"], "name": t.get("name"), "lat": lat, "lon": lon,
                "emergency": t.get("emergency"), "beds": t.get("beds"), "operator": t.get("operator"),
                "operator_type": t.get("operator:type"), "phone": t.get("phone") or t.get("contact:phone"),
                "addr_city": t.get("addr:city"), "healthcare_speciality": t.get("healthcare:speciality")})
dst = r"C:\Projects\Intelligent-Emergency-Response\gis\data\osm_hospitals_hubballi_dharwad.json"
json.dump({"source": "OpenStreetMap via Overpass API (ODbL)", "bbox_SWNE": BBOX, "query": q.strip(),
           "count": len(out), "features": out}, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("hospitals:", len(out), "named:", sum(1 for o in out if o["name"]))
for o in sorted(out, key=lambda x: x["name"] or "~")[:60]:
    print(f'  {o["osm_type"][0]}{o["osm_id"]:<12} {o["lat"]:.5f},{o["lon"]:.5f}  emerg={o["emergency"] or "-":<4} {o["name"]}')
