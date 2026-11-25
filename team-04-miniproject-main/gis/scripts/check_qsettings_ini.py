from qgis.PyQt.QtCore import QSettings

qs = QSettings('C:/Users/acer/AppData/Roaming/QGIS/QGIS3/profiles/default/QGIS/QGIS3.ini', QSettings.IniFormat)
qs.beginGroup('PostgreSQL/connections')
print('Child groups:', qs.childGroups())
for g in qs.childGroups():
    qs.beginGroup(g)
    print(f'Group [{g}]:')
    for k in qs.childKeys():
        print(f'  {k} = {qs.value(k)}')
    qs.endGroup()
qs.endGroup()
