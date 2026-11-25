import os
import zipfile
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer

qgs_content = '''<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis projectname="Intelligent Emergency Response System (IERS) - PostGIS Demonstration" version="3.44.15">
  <homePath path=""/>
  <title>Intelligent Emergency Response System (IERS) - Live PostGIS Project</title>
  <autotransactors>1</autotransactors>
  <dates>
    <created>2026-11-21T14:00:00</created>
  </dates>
  <mapcanvas name="theMapCanvas">
    <units>degrees</units>
    <extent>
      <xmin>75.1000</xmin>
      <ymin>15.3500</ymin>
      <xmax>75.1350</xmax>
      <ymax>15.3950</ymax>
    </extent>
    <rotation>0</rotation>
    <destinationsrs>
      <spatialrefsys>
        <wkt>GEOGCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],CS[ellipsoidal,2],AXIS["geodetic latitude (Lat)",north,ORDER[1],ANGLEUNIT["degree",0.0174532925199433]],AXIS["geodetic longitude (Lon)",east,ORDER[2],ANGLEUNIT["degree",0.0174532925199433]],ID["EPSG",4326]]</wkt>
        <proj4>+proj=longlat +datum=WGS84 +no_defs</proj4>
        <srsid>3452</srsid>
        <srid>4326</srid>
        <authid>EPSG:4326</authid>
        <description>WGS 84</description>
        <projectionacronym>longlat</projectionacronym>
        <ellipsoidacronym>EPSG:7030</ellipsoidacronym>
        <geographicflag>true</geographicflag>
      </spatialrefsys>
    </destinationsrs>
  </mapcanvas>
  <projectlayers>

    <!-- LAYER 1: Campus Boundary (PostGIS Polygon) -->
    <maplayer autoRefreshTime="0" hasScaleBasedVisibilityFlag="0" id="iers_campus_boundary" maxScale="0" minScale="1e+08" refreshOnNotifyEnabled="0" type="vector">
      <id>iers_campus_boundary</id>
      <datasource>dbname='iers_db' host=localhost port=5434 user='iers_user' password='iers_dev_local' sslmode=disable key='id' srid=4326 type=Polygon table="iers"."campus_boundary" (geom) sql=</datasource>
      <layername>1. Campus Zone Boundary (PostGIS)</layername>
      <srs>
        <spatialrefsys><srid>4326</srid><authid>EPSG:4326</authid></spatialrefsys>
      </srs>
      <renderer-v2 type="singleSymbol">
        <symbols>
          <symbol alpha="0.25" clip_to_extent="1" force_rhr="0" name="0" type="fill">
            <layer class="SimpleFill" locked="0" pass="0">
              <prop k="color" v="129,140,248,60"/>
              <prop k="outline_color" v="99,102,241,220"/>
              <prop k="outline_width" v="0.8"/>
              <prop k="outline_style" v="dash"/>
            </layer>
          </symbol>
        </symbols>
      </renderer-v2>
    </maplayer>

    <!-- LAYER 2: Hospital 500m Service Coverage Buffer (PostGIS Polygon View) -->
    <maplayer autoRefreshTime="0" hasScaleBasedVisibilityFlag="0" id="iers_hosp_coverage" maxScale="0" minScale="1e+08" refreshOnNotifyEnabled="0" type="vector">
      <id>iers_hosp_coverage</id>
      <datasource>dbname='iers_db' host=localhost port=5434 user='iers_user' password='iers_dev_local' sslmode=disable key='hospital_id' srid=4326 type=Polygon table="iers"."v_hospital_coverage_500m" (coverage_geom) sql=</datasource>
      <layername>2. Hospital 500m Service Buffer (PostGIS View)</layername>
      <srs>
        <spatialrefsys><srid>4326</srid><authid>EPSG:4326</authid></spatialrefsys>
      </srs>
      <renderer-v2 type="singleSymbol">
        <symbols>
          <symbol alpha="0.2" clip_to_extent="1" force_rhr="0" name="0" type="fill">
            <layer class="SimpleFill" locked="0" pass="0">
              <prop k="color" v="239,68,68,50"/>
              <prop k="outline_color" v="239,68,68,220"/>
              <prop k="outline_width" v="0.8"/>
              <prop k="outline_style" v="dot"/>
            </layer>
          </symbol>
        </symbols>
      </renderer-v2>
    </maplayer>

    <!-- LAYER 3: Road Network Edges (PostGIS 2,267 Segments with Physical Clearance) -->
    <maplayer autoRefreshTime="0" hasScaleBasedVisibilityFlag="0" id="iers_road_edges" maxScale="0" minScale="1e+08" refreshOnNotifyEnabled="0" type="vector">
      <id>iers_road_edges</id>
      <datasource>dbname='iers_db' host=localhost port=5434 user='iers_user' password='iers_dev_local' sslmode=disable key='edge_id' srid=4326 type=LineString table="iers"."road_network_edges" (geom) sql=</datasource>
      <layername>3. Road Network Edges (2,267 Segments - PostGIS)</layername>
      <srs>
        <spatialrefsys><srid>4326</srid><authid>EPSG:4326</authid></spatialrefsys>
      </srs>
      <renderer-v2 type="categorizedSymbol" attr="is_emergency_corridor">
        <categories>
          <category value="true" label="Priority Emergency Green Corridor" symbol="corridor_sym"/>
          <category value="false" label="Standard Metropolitan Road" symbol="std_road_sym"/>
        </categories>
        <symbols>
          <symbol alpha="1" clip_to_extent="1" force_rhr="0" name="corridor_sym" type="line">
            <layer class="SimpleLine" locked="0" pass="1">
              <prop k="line_color" v="16,185,129,255"/>
              <prop k="line_width" v="1.5"/>
              <prop k="line_style" v="solid"/>
            </layer>
          </symbol>
          <symbol alpha="0.8" clip_to_extent="1" force_rhr="0" name="std_road_sym" type="line">
            <layer class="SimpleLine" locked="0" pass="0">
              <prop k="line_color" v="71,85,105,255"/>
              <prop k="line_width" v="0.6"/>
              <prop k="line_style" v="solid"/>
            </layer>
          </symbol>
        </symbols>
      </renderer-v2>
    </maplayer>

    <!-- LAYER 4: Road Network Nodes (PostGIS 1,282 Intersections) -->
    <maplayer autoRefreshTime="0" hasScaleBasedVisibilityFlag="0" id="iers_road_nodes" maxScale="0" minScale="50000" refreshOnNotifyEnabled="0" type="vector">
      <id>iers_road_nodes</id>
      <datasource>dbname='iers_db' host=localhost port=5434 user='iers_user' password='iers_dev_local' sslmode=disable key='node_id' srid=4326 type=Point table="iers"."road_network_nodes" (geom) sql=</datasource>
      <layername>4. Road Intersections (1,282 Nodes - PostGIS)</layername>
      <srs>
        <spatialrefsys><srid>4326</srid><authid>EPSG:4326</authid></spatialrefsys>
      </srs>
      <renderer-v2 type="singleSymbol">
        <symbols>
          <symbol alpha="0.75" clip_to_extent="1" force_rhr="0" name="0" type="marker">
            <layer class="SimpleMarker" locked="0" pass="0">
              <prop k="color" v="148,163,184,200"/>
              <prop k="size" v="1.8"/>
              <prop k="outline_color" v="15,23,42,255"/>
              <prop k="outline_width" v="0.3"/>
            </layer>
          </symbol>
        </symbols>
      </renderer-v2>
    </maplayer>

    <!-- LAYER 5: Hospitals & Trauma Hubs (PostGIS Points) -->
    <maplayer autoRefreshTime="0" hasScaleBasedVisibilityFlag="0" id="iers_hospitals" maxScale="0" minScale="1e+08" refreshOnNotifyEnabled="0" type="vector">
      <id>iers_hospitals</id>
      <datasource>dbname='iers_db' host=localhost port=5434 user='iers_user' password='iers_dev_local' sslmode=disable key='hospital_id' srid=4326 type=Point table="iers"."hospitals" (geom) sql=</datasource>
      <layername>5. Hospitals &amp; Trauma Hubs (PostGIS)</layername>
      <srs>
        <spatialrefsys><srid>4326</srid><authid>EPSG:4326</authid></spatialrefsys>
      </srs>
      <renderer-v2 type="singleSymbol">
        <symbols>
          <symbol alpha="1" clip_to_extent="1" force_rhr="0" name="0" type="marker">
            <layer class="SimpleMarker" locked="0" pass="0">
              <prop k="color" v="239,68,68,255"/>
              <prop k="size" v="6.0"/>
              <prop k="name" v="cross"/>
              <prop k="outline_color" v="255,255,255,255"/>
              <prop k="outline_width" v="1.0"/>
            </layer>
          </symbol>
        </symbols>
      </renderer-v2>
    </maplayer>

    <!-- LAYER 6: Emergency Fleet Ambulances (PostGIS Points) -->
    <maplayer autoRefreshTime="0" hasScaleBasedVisibilityFlag="0" id="iers_ambulances" maxScale="0" minScale="1e+08" refreshOnNotifyEnabled="0" type="vector">
      <id>iers_ambulances</id>
      <datasource>dbname='iers_db' host=localhost port=5434 user='iers_user' password='iers_dev_local' sslmode=disable key='ambulance_id' srid=4326 type=Point table="iers"."ambulances" (geom) sql=</datasource>
      <layername>6. Emergency Fleet (ALS / BLS / Flyer - PostGIS)</layername>
      <srs>
        <spatialrefsys><srid>4326</srid><authid>EPSG:4326</authid></spatialrefsys>
      </srs>
      <renderer-v2 type="categorizedSymbol" attr="vehicle_type">
        <categories>
          <category value="ALS" label="Advanced Life Support (ALS)" symbol="als_sym"/>
          <category value="BLS" label="Basic Life Support (BLS)" symbol="bls_sym"/>
          <category value="FLYER" label="Rapid Flyer" symbol="flyer_sym"/>
        </categories>
        <symbols>
          <symbol alpha="1" clip_to_extent="1" force_rhr="0" name="als_sym" type="marker">
            <layer class="SimpleMarker" locked="0" pass="0">
              <prop k="color" v="245,158,11,255"/>
              <prop k="size" v="5.0"/>
              <prop k="name" v="square"/>
              <prop k="outline_color" v="255,255,255,255"/>
              <prop k="outline_width" v="1.0"/>
            </layer>
          </symbol>
          <symbol alpha="1" clip_to_extent="1" force_rhr="0" name="bls_sym" type="marker">
            <layer class="SimpleMarker" locked="0" pass="0">
              <prop k="color" v="59,130,246,255"/>
              <prop k="size" v="4.5"/>
              <prop k="name" v="circle"/>
              <prop k="outline_color" v="255,255,255,255"/>
              <prop k="outline_width" v="1.0"/>
            </layer>
          </symbol>
          <symbol alpha="1" clip_to_extent="1" force_rhr="0" name="flyer_sym" type="marker">
            <layer class="SimpleMarker" locked="0" pass="0">
              <prop k="color" v="16,185,129,255"/>
              <prop k="size" v="4.0"/>
              <prop k="name" v="triangle"/>
              <prop k="outline_color" v="255,255,255,255"/>
              <prop k="outline_width" v="1.0"/>
            </layer>
          </symbol>
        </symbols>
      </renderer-v2>
    </maplayer>

  </projectlayers>
</qgis>'''

qgs_path = 'C:/Projects/Intelligent-Emergency-Response/gis/qgis/Intelligent_Emergency_Response.qgs'
qgz_path = 'C:/Projects/Intelligent-Emergency-Response/gis/qgis/Intelligent_Emergency_Response.qgz'

with open(qgs_path, 'w', encoding='utf-8') as f:
    f.write(qgs_content)

with zipfile.ZipFile(qgz_path, 'w', zipfile.ZIP_DEFLATED) as z:
    z.writestr('Intelligent_Emergency_Response.qgs', qgs_content.encode('utf-8'))

print('QGS and QGZ project files successfully written.')

# Now verify with QgsApplication
app = QgsApplication([], False)
app.initQgis()

project = QgsProject.instance()
ok = project.read(qgs_path)
print(f'Project read: {ok}, Total layers: {len(project.mapLayers())}')

all_valid = True
for lid, layer in project.mapLayers().items():
    print(f' - {layer.name()}: Valid={layer.isValid()}, Features={layer.featureCount()}')
    if not layer.isValid():
        all_valid = False
        print(f'   Error: {layer.error().message()}')

print(f'All 6 PostGIS layers valid: {all_valid}')
app.exitQgis()
