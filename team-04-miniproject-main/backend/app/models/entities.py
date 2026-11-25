from sqlalchemy import Column, Integer, BigInteger, String, Float, Boolean, DateTime, Enum, Text
from geoalchemy2 import Geometry
from geoalchemy2.shape import to_shape
from app.core.database import Base
from datetime import datetime
import enum

def _safe_geom_to_geojson(geom):
    if geom is None:
        return None
    try:
        return to_shape(geom).__geo_interface__
    except Exception:
        return None

class VehicleType(str, enum.Enum):
    ALS = 'ALS'
    BLS = 'BLS'
    RAPID_FLYER = 'FLYER'
    FLYER = 'FLYER'
    HELI = 'HELI'

class AmbulanceStatus(str, enum.Enum):
    AVAILABLE = 'AVAILABLE'
    DISPATCHED = 'DISPATCHED'
    EN_ROUTE_INCIDENT = 'EN_ROUTE_INCIDENT'
    AT_SCENE = 'AT_SCENE'
    EN_ROUTE_HOSPITAL = 'EN_ROUTE_HOSPITAL'
    OFF_DUTY = 'OFF_DUTY'

class IncidentSeverity(str, enum.Enum):
    CRITICAL = 'CRITICAL'
    URGENT = 'URGENT'
    STANDARD = 'STANDARD'

class IncidentStatus(str, enum.Enum):
    REPORTED = 'REPORTED'
    ALLOCATED = 'ALLOCATED'
    IN_PROGRESS = 'IN_PROGRESS'
    RESOLVED = 'RESOLVED'
    CANCELLED = 'CANCELLED'

class RoadNode(Base):
    __tablename__ = 'road_nodes'
    __table_args__ = {'schema': 'iers'}

    node_id = Column(BigInteger, primary_key=True, index=True)
    location = Column(Geometry('POINT', srid=4326), nullable=False)

    @property
    def id(self):
        return str(self.node_id)

    def to_dict(self):
        return {
            'id': self.id,
            'node_id': self.node_id,
            'geom_geojson': _safe_geom_to_geojson(self.location)
        }

class RoadEdge(Base):
    __tablename__ = 'roads'
    __table_args__ = {'schema': 'iers'}

    road_id = Column(BigInteger, primary_key=True, index=True)
    osm_id = Column(String, nullable=True)
    name = Column(String, nullable=True)
    highway = Column(String, nullable=True)
    distance_m = Column(Float, nullable=False)
    speed_limit = Column(Float, default=40.0)
    travel_time_s = Column(Float, default=5.0)
    reverse_cost = Column(Float, default=5.0)
    is_blocked = Column(Boolean, default=False)
    source = Column(BigInteger, index=True)
    target = Column(BigInteger, index=True)
    geom = Column(Geometry('LINESTRING', srid=4326), nullable=True)

    @property
    def id(self):
        return str(self.road_id)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'highway': self.highway,
            'distance_m': self.distance_m,
            'travel_time_s': self.travel_time_s,
            'source': self.source,
            'target': self.target,
            'geom_geojson': _safe_geom_to_geojson(self.geom)
        }

class Hospital(Base):
    __tablename__ = 'hospitals'
    __table_args__ = {'schema': 'iers'}

    id = Column('hospital_id', String(64), primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    nearest_node_id = Column(String(64), nullable=True)
    total_beds = Column(Integer, default=50)
    icu_available = Column(Integer, default=10)
    trauma_level = Column(Integer, default=1)
    has_helipad = Column(Boolean, default=False)
    geom = Column(Geometry('POINT', srid=4326), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'nearest_node_id': self.nearest_node_id,
            'total_beds': self.total_beds,
            'icu_available': self.icu_available,
            'trauma_level': self.trauma_level,
            'has_helipad': self.has_helipad,
            'geom_geojson': _safe_geom_to_geojson(self.geom)
        }

class Ambulance(Base):
    __tablename__ = 'ambulances'
    __table_args__ = {'schema': 'iers'}

    id = Column('ambulance_id', String(64), primary_key=True, index=True)
    call_sign = Column(String(64), nullable=False, unique=True)
    vehicle_type = Column(
        Enum(VehicleType, values_callable=lambda x: [e.value for e in x], native_enum=False),
        default=VehicleType.BLS, nullable=False
    )
    status = Column(
        Enum(AmbulanceStatus, values_callable=lambda x: [e.value for e in x], native_enum=False),
        default=AmbulanceStatus.AVAILABLE, nullable=False
    )
    height_meters = Column(Float, default=2.4)
    weight_tons = Column(Float, default=3.5)
    width_meters = Column(Float, default=2.2)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    current_node_id = Column(String(64), nullable=True)
    assigned_hospital_id = Column(String(64), nullable=True)
    driver_name = Column(String(128), default='Paramedic Crew')
    fuel_percent = Column(Float, default=100.0)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    geom = Column(Geometry('POINT', srid=4326), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'call_sign': self.call_sign,
            'vehicle_type': self.vehicle_type.value if hasattr(self.vehicle_type, 'value') else str(self.vehicle_type),
            'status': self.status.value if hasattr(self.status, 'value') else str(self.status),
            'height_meters': self.height_meters,
            'weight_tons': self.weight_tons,
            'width_meters': self.width_meters,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'current_node_id': self.current_node_id,
            'assigned_hospital_id': self.assigned_hospital_id,
            'driver_name': self.driver_name,
            'fuel_percent': self.fuel_percent,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'geom_geojson': _safe_geom_to_geojson(self.geom)
        }

class Incident(Base):
    __tablename__ = 'incidents'
    __table_args__ = {'schema': 'iers'}

    id = Column('incident_id', String(64), primary_key=True, index=True)
    caller_name = Column(String(128), default='Emergency Caller')
    caller_phone = Column(String(32), default='911 / 112')
    incident_type = Column(String(64), default='Cardiac Arrest / Severe Trauma')
    severity = Column(
        Enum(IncidentSeverity, values_callable=lambda x: [e.value for e in x], native_enum=False),
        default=IncidentSeverity.CRITICAL, nullable=False
    )
    status = Column(
        Enum(IncidentStatus, values_callable=lambda x: [e.value for e in x], native_enum=False),
        default=IncidentStatus.REPORTED, nullable=False
    )
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    nearest_node_id = Column(String(64), nullable=True)
    assigned_ambulance_id = Column(String(64), nullable=True)
    target_hospital_id = Column(String(64), nullable=True)
    reported_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    geom = Column(Geometry('POINT', srid=4326), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'caller_name': self.caller_name,
            'caller_phone': self.caller_phone,
            'incident_type': self.incident_type,
            'severity': self.severity.value if hasattr(self.severity, 'value') else str(self.severity),
            'status': self.status.value if hasattr(self.status, 'value') else str(self.status),
            'latitude': self.latitude,
            'longitude': self.longitude,
            'nearest_node_id': self.nearest_node_id,
            'assigned_ambulance_id': self.assigned_ambulance_id,
            'target_hospital_id': self.target_hospital_id,
            'reported_at': self.reported_at.isoformat() if self.reported_at else None,
            'dispatched_at': self.dispatched_at.isoformat() if self.dispatched_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'notes': self.notes,
            'geom_geojson': _safe_geom_to_geojson(self.geom)
        }
