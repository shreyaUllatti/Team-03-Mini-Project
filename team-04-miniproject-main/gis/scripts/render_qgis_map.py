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
settings.setOutputSize(QSize(1600, 1200))
settings.setBackgroundColor(QColor(15, 23, 42)) # Slate 900 dark background

# Full bounding box of Hubballi campus corridor
extent = QgsRectangle(75.1000, 15.3500, 75.1350, 15.3950)
settings.setExtent(extent)
settings.setDestinationCrs(project.crs())

job = QgsMapRendererSequentialJob(settings)
job.start()
job.waitForFinished()

img = job.renderedImage()
out_path = 'C:/Projects/Intelligent-Emergency-Response/gis/qgis/qgis_verified_render.png'
saved = img.save(out_path)
print(f'Rendered map image saved: {saved} ({out_path}, size: {img.width()}x{img.height()})')

app.exitQgis()
