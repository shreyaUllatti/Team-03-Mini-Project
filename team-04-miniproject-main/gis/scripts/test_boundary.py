import sys
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer

app = QgsApplication([], False)
app.initQgis()

layer = QgsVectorLayer('C:/Projects/Intelligent-Emergency-Response/gis/data/kle_campus.gpkg|layername=campus_boundary', 'Boundary', 'ogr')
print(f'Absolute path layer valid: {layer.isValid()}, features: {layer.featureCount()}')

app.exitQgis()
