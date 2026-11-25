from qgis.PyQt.QtCore import QSettings

qs = QSettings('C:/Users/acer/AppData/Roaming/QGIS/QGIS3/profiles/default/QGIS/QGIS3.ini', QSettings.IniFormat)
qs.beginGroup('PostgreSQL/connections/IERS PostGIS')
qs.setValue('service', '')
qs.setValue('host', 'localhost')
qs.setValue('port', '5434')
qs.setValue('database', 'iers_db')
qs.setValue('username', 'iers_user')
qs.setValue('password', 'iers_dev_local')
qs.setValue('authcfg', '')
qs.setValue('sslmode', 'SslDisable')
qs.setValue('publicOnly', False)
qs.setValue('geometryColumnsOnly', False)
qs.setValue('dontResolveType', False)
qs.setValue('allowGeometrylessTables', False)
qs.setValue('saveUsername', True)
qs.setValue('savePassword', True)
qs.setValue('estimatedMetadata', False)
qs.setValue('projectsInDatabase', False)
qs.setValue('metadataInDatabase', False)
qs.setValue('session_role', '')
qs.setValue('allowRasterOverviewTables', False)
qs.setValue('schema', 'iers')
qs.endGroup()

qs.beginGroup('PostgreSQL/connections')
qs.setValue('selected', 'IERS PostGIS')
qs.endGroup()

# Also ensure DB Manager and Browser have expanded path for IERS PostGIS
expanded = qs.value('browser/expandedPaths', '')
if 'pg:/IERS PostGIS' not in str(expanded):
    qs.setValue('browser/expandedPaths', f'{expanded}, pg:/IERS PostGIS/iers')

qs.sync()
print('Successfully configured IERS PostGIS in QGIS3.ini!')
