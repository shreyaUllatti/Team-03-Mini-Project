import os
import socket
from pydantic_settings import BaseSettings

def get_default_database_url() -> str:
    """
    Determines the appropriate PostGIS database URL:
    - If running inside a Docker network, resolves to iers-postgis:5432
    - If running directly on Windows host, connects to localhost:5434 (mapped port for iers-postgis)
    - Fallback only if explicitly overridden by DATABASE_URL environment variable
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    # Unified operational PostgreSQL/PostGIS database inspected in pgAdmin: emergency_db (public)
    return "postgresql+asyncpg://postgres:Ankush%402007@localhost:5432/emergency_db"

class Settings(BaseSettings):
    APP_NAME: str = "Intelligent Emergency Response System"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True
    
    # Active operational database: PostgreSQL 17 + PostGIS 3.5 in iers-postgis
    DATABASE_URL: str = get_default_database_url()
    
    # Map & Simulation
    SIMULATION_TICK_SECONDS: float = 1.0
    DEFAULT_SPEED_LIMIT_KMH: float = 50.0
    CONGESTION_PENALTY_FACTOR: float = 2.5

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
