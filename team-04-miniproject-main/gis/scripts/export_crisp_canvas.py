import sys
from qgis.core import (
    QgsApplication, QgsProject, QgsMapSettings,
    QgsMapRendererSequentialJob, QgsRectangle,
    QgsLineSymbol, QgsSingleSymbolRenderer,
    QgsMarkerSymbol, QgsFillSymbol
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QImage, QColor

app = QgsApplication([], False)
app.initQgis()

prj = QgsProject.instance()
prj.read('C:/Projects/Intelligent-Emergency-Response/gis/qgis/Intelligent_Emergency_Response.qgz')

# Retrieve and style layers directly in memory for crisp visibility
layers_to_render = []

for l in prj.mapLayers().values():
    name = l.name()
    if '40,394' in name:
        # Roads layer: single symbol with visible high-contrast dark slate color
        sym = QgsLineSymbol.createSimple({'color': '51,65,85,255', 'width': '0.7', 'line_style': 'solid'})
        l.setRenderer(QgsSingleSymbolRenderer(sym))
        l.triggerRepaint()
        layers_to_render.append(l)
        print('Styled roads layer:', name)
    elif '2.5km' in name:
        # Buffers: light red/coral fill
        sym = QgsFillSymbol.createSimple({'color': '239,68,68,30', 'outline_color': '239,68,68,180', 'outline_width': '0.8'})
        l.setRenderer(QgsSingleSymbolRenderer(sym))
        l.triggerRepaint()
        layers_to_render.append(l)
        print('Styled buffers layer:', name)
    elif 'Hospitals' in name:
        # Hospitals: prominent red cross/circle
        sym = QgsMarkerSymbol.createSimple({'name': 'cross2', 'color': '220,38,38,255', 'size': '8', 'outline_color': '255,255,255,255', 'outline_width': '1.0'})
        l.setRenderer(QgsSingleSymbolRenderer(sym))
        l.triggerRepaint()
        layers_to_render.append(l)
        print('Styled hospitals layer:', name)
    elif 'Fleet' in name:
        # Fleet: lime/amber circles
        sym = QgsMarkerSymbol.createSimple({'name': 'circle', 'color': '184,244,50,255', 'size': '7', 'outline_color': '17,18,21,255', 'outline_width': '1.2'})
        l.setRenderer(QgsSingleSymbolRenderer(sym))
        l.triggerRepaint()
        layers_to_render.append(l)
        print('Styled fleet layer:', name)

# Render crisp canvas
settings = QgsMapSettings()
settings.setLayers(layers_to_render)
settings.setOutputSize(QSize(2400, 1800))
settings.setBackgroundColor(QColor(245, 246, 249))

# Extent of Hubballi and Dharwad metropolitan area
extent = QgsRectangle(74.9135, 15.2093, 75.3113, 15.6164)
settings.setExtent(extent)
settings.setDestinationCrs(prj.crs())

job = QgsMapRendererSequentialJob(settings)
job.start()
job.waitForFinished()

img = job.renderedImage()
out_path = 'C:/Projects/Intelligent-Emergency-Response/backend/app/static/qgis_canvas.png'
img.save(out_path)
print(f'Crisp QGIS map exported: {out_path} (Size: {img.width()}x{img.height()})')

app.exitQgis()
