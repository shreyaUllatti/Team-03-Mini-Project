"""
PyQGIS On-Demand XYZ Tile Server — Connected directly to emergency_db (public.roads)
- Exact EPSG:3857 (Web Mercator) tile rendering for 100% pixel-accurate Leaflet alignment
- Pixel-unit road hierarchy (no oversized mm-unit thick black lines)
- 3-tier multi-scale subset filtering (z<=10 highways, z=11-13 city, z>=14 street)
- Zoom-dependent curved PAL labels with mergeLines=True and collision decluttering
"""
import math
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from qgis.core import (
    QgsApplication,
    QgsProject,
    QgsVectorLayer,
    QgsMapSettings,
    QgsMapRendererSequentialJob,
    QgsRectangle,
    QgsCoordinateReferenceSystem,
    QgsLineSymbol,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QSize, QBuffer, QIODevice
from qgis.PyQt.QtGui import QColor, QFont

CACHE_DIR = "C:/Projects/Intelligent-Emergency-Response/gis/qgis/tile_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

app = QgsApplication([], False)
app.initQgis()

project = QgsProject.instance()
CRS_3857 = QgsCoordinateReferenceSystem("EPSG:3857")
project.setCrs(CRS_3857)

uri = (
    "dbname='emergency_db' host=localhost port=5432 user='postgres' password='Ankush@2007' "
    "sslmode=disable key='road_id' srid=4326 type=LineString table=\"public\".\"roads\" (geom) sql="
)
roads_lyr = QgsVectorLayer(uri, "Hubballi-Dharwad Roads (emergency_db)", "postgres")
print(f"[QGIS-TILES] Loaded public.roads from emergency_db: valid={roads_lyr.isValid()}", flush=True)

# Pixel-unit cartographic road hierarchy (crisp, never oversized mm-unit blobs)
cats = [
    ("trunk", "National / Trunk Highway", "#D97706", "3.4"),
    ("trunk_link", "Trunk Link", "#D97706", "2.2"),
    ("primary", "Primary Arterial", "#334155", "2.4"),
    ("primary_link", "Primary Link", "#334155", "1.7"),
    ("secondary", "Secondary Road", "#64748B", "1.7"),
    ("secondary_link", "Secondary Link", "#64748B", "1.3"),
    ("tertiary", "Tertiary Road", "#94A3B8", "1.2"),
    ("tertiary_link", "Tertiary Link", "#94A3B8", "1.0"),
    ("unclassified", "Local Road", "#CBD5E1", "0.9"),
    ("residential", "Residential Street", "#CBD5E1", "0.75"),
    ("service", "Service Lane", "#E2E8F0", "0.6"),
    ("living_street", "Living Street", "#E2E8F0", "0.6"),
]
renderer_cats = []
for val, label, color, width_px in cats:
    sym = QgsLineSymbol.createSimple({
        "color": color,
        "width": width_px,
        "width_unit": "Pixel",
        "line_style": "solid",
        "capstyle": "round",
        "joinstyle": "round",
    })
    renderer_cats.append(QgsRendererCategory(val, sym, label))
default_sym = QgsLineSymbol.createSimple({"color": "#CBD5E1", "width": "0.7", "width_unit": "Pixel", "line_style": "solid"})
renderer_cats.append(QgsRendererCategory("", default_sym, "Other"))
roads_lyr.setRenderer(QgsCategorizedSymbolRenderer("highway", renderer_cats))

# Curved PAL labels with mergeLines=True, minFeatureSize=35mm, repeatDistance=0
pal = QgsPalLayerSettings()
pal.fieldName = "name"
pal.enabled = True
pal.placement = QgsPalLayerSettings.Curved
pal.mergeLines = True
pal.repeatDistance = 0
pal.minFeatureSize = 35

fmt = QgsTextFormat()
font = QFont("Inter", 8)
font.setBold(True)
fmt.setFont(font)
fmt.setSize(8)
fmt.setColor(QColor("#1E293B"))

buf = QgsTextBufferSettings()
buf.setEnabled(True)
buf.setSize(1.2)
buf.setColor(QColor("#FFFFFF"))
fmt.setBuffer(buf)
pal.setFormat(fmt)

roads_lyr.setLabeling(QgsVectorLayerSimpleLabeling(pal))
roads_lyr.setLabelsEnabled(True)

project.addMapLayer(roads_lyr)
render_layers = [roads_lyr]

RENDER_LOCK = threading.Lock()
ORIGIN_SHIFT = 20037508.342789244


def tile_to_3857_bbox(z: int, x: int, y: int) -> QgsRectangle:
    n = 2.0 ** z
    tile_size = (2.0 * ORIGIN_SHIFT) / n
    xmin = -ORIGIN_SHIFT + x * tile_size
    xmax = -ORIGIN_SHIFT + (x + 1) * tile_size
    ymax = ORIGIN_SHIFT - y * tile_size
    ymin = ORIGIN_SHIFT - (y + 1) * tile_size
    return QgsRectangle(xmin, ymin, xmax, ymax)


def render_tile_png(z: int, x: int, y: int) -> bytes:
    cache_path = os.path.join(CACHE_DIR, f"v5_{z}_{x}_{y}.png")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()

    bbox = tile_to_3857_bbox(z, x, y)
    if z <= 10:
        subset = "highway IN ('trunk','trunk_link','primary','primary_link')"
    elif z <= 13:
        subset = "highway IN ('trunk','trunk_link','primary','primary_link','secondary','secondary_link','tertiary')"
    else:
        subset = ""

    with RENDER_LOCK:
        roads_lyr.setSubsetString(subset)
        settings = QgsMapSettings()
        settings.setTransformContext(project.transformContext())
        settings.setLayers(render_layers)
        settings.setOutputSize(QSize(256, 256))
        settings.setDestinationCrs(CRS_3857)
        settings.setExtent(bbox)
        settings.setBackgroundColor(QColor(248, 249, 250))
        settings.setFlag(QgsMapSettings.Antialiasing, True)
        settings.setFlag(QgsMapSettings.DrawLabeling, z >= 14)

        job = QgsMapRendererSequentialJob(settings)
        job.start()
        job.waitForFinished()
        img = job.renderedImage()

        qbuf = QBuffer()
        qbuf.open(QIODevice.WriteOnly)
        img.save(qbuf, "PNG")
        data = bytes(qbuf.data())
        qbuf.close()

    try:
        with open(cache_path, "wb") as f:
            f.write(data)
    except Exception:
        pass
    return data


class TileHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","engine":"PyQGIS","crs":"EPSG:3857","unit":"Pixel"}')
            return

        parts = self.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "tiles" and parts[3].endswith(".png"):
            try:
                z, x, y = int(parts[1]), int(parts[2]), int(parts[3][:-4])
                if z < 8 or z > 18:
                    self.send_error(400, "Zoom out of range")
                    return
                png = render_tile_png(z, x, y)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(png)
                return
            except Exception as e:
                self.send_error(500, str(e))
                return
        self.send_error(404, "Not Found")


if __name__ == "__main__":
    port = int(os.environ.get("QGIS_TILE_PORT", "8001"))
    server = ThreadingHTTPServer(("127.0.0.1", port), TileHandler)
    print(f"[QGIS-TILES] Serving EPSG:3857 Pixel-styled tiles on http://127.0.0.1:{port}/tiles/{{z}}/{{x}}/{{y}}.png", flush=True)
    try:
        server.serve_forever()
    finally:
        app.exitQgis()
