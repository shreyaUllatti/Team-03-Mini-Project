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
settings.setOutputSize(QSize(2000, 1600))
settings.setBackgroundColor(QColor(15, 23, 42)) # Slate 900 dark background

# Full metropolitan extent spanning Hubballi and Dharwad
extent = QgsRectangle(74.9135, 15.2093, 75.3113, 15.6164)
settings.setExtent(extent)
settings.setDestinationCrs(project.crs())

job = QgsMapRendererSequentialJob(settings)
job.start()
job.waitForFinished()

img = job.renderedImage()
out_path = 'C:/Projects/Intelligent-Emergency-Response/gis/qgis/qgis_metropolitan_verified_render.png'
saved = img.save(out_path)
print(f'Metropolitan map render saved: {saved} ({out_path}, size: {img.width()}x{img.height()})')

app.exitQgis()
