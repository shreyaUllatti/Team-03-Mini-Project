import sys
from qgis.core import (
    QgsApplication, QgsProject, QgsMapSettings,
    QgsMapRendererSequentialJob, QgsRectangle
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QImage, QColor

app = QgsApplication([], False)
app.initQgis()

project = QgsProject.instance()
project.read('C:/Projects/Intelligent-Emergency-Response/gis/qgis/Intelligent_Emergency_Response.qgz')

settings = QgsMapSettings()
settings.setLayers(list(project.mapLayers().values()))
settings.setOutputSize(QSize(2560, 1600))
# High-fashion light neutral canvas background matching reference
settings.setBackgroundColor(QColor(246, 247, 249))

# Metropolitan extent spanning Hubballi and Dharwad
extent = QgsRectangle(74.9135, 15.2093, 75.3113, 15.6164)
settings.setExtent(extent)
settings.setDestinationCrs(project.crs())

job = QgsMapRendererSequentialJob(settings)
job.start()
job.waitForFinished()

img = job.renderedImage()
out_backend = 'C:/Projects/Intelligent-Emergency-Response/backend/app/static/qgis_canvas.png'
saved = img.save(out_backend)
print(f'QGIS direct canvas render exported: {saved} ({out_backend})')

app.exitQgis()
