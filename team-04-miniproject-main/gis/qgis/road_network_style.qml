<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis styleCategories="AllStyleCategories" version="3.44.15">
  <renderer-v2 type="categorizedSymbol" attr="highway">
    <categories>
      <category symbol="0" value="residential" label="Residential / Campus Street"/>
      <category symbol="1" value="service" label="Service Road / Access Lane"/>
      <category symbol="2" value="primary" label="Arterial Main Road"/>
    </categories>
    <symbols>
      <symbol alpha="1" type="line" name="0">
        <layer class="SimpleLine" pass="0">
          <prop k="line_color" v="100,116,139,255"/>
          <prop k="line_width" v="0.6"/>
        </layer>
      </symbol>
      <symbol alpha="1" type="line" name="1">
        <layer class="SimpleLine" pass="0">
          <prop k="line_color" v="148,163,184,255"/>
          <prop k="line_width" v="0.4"/>
        </layer>
      </symbol>
      <symbol alpha="1" type="line" name="2">
        <layer class="SimpleLine" pass="0">
          <prop k="line_color" v="234,88,12,255"/>
          <prop k="line_width" v="1.2"/>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
</qgis>
