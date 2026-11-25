from qgis.core import QgsApplication, QgsSettings

app = QgsApplication([], False)
app.initQgis()

# Create QgsSettings with specific ini file or test default
s = QgsSettings()
print('Default QgsSettings fileName:', s.fileName())

app.exitQgis()
