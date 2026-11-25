import sys
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer

app = QgsApplication([], False)
app.initQgis()

project = QgsProject.instance()
ok = project.read('C:/Projects/Intelligent-Emergency-Response/gis/qgis/Intelligent_Emergency_Response.qgs')
print(f'Project read success: {ok}')
print(f'Total layers loaded: {len(project.mapLayers())}')
for lid, layer in project.mapLayers().items():
    print(f' - Layer: {layer.name()}')
    print(f'   Valid: {layer.isValid()}')
    print(f'   Features: {layer.featureCount()}')
    if not layer.isValid():
        print(f'   Error: {layer.error().message()}')
        print(f'   Source: {layer.source()}')

app.exitQgis()
