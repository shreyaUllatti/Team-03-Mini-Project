# Intelligent Emergency Response System (IERS)

An autonomous emergency fleet allocation, vehicle-constrained routing, and real-time GIS dispatch system built with **FastAPI**, **NetworkX**, **Leaflet.js**, and **Tailwind CSS**.

---

## 🌟 Key Features

1. **Constrained A* Routing Engine**:
   - Accounts for physical vehicle specifications (height, width, weight).
   - Rejects routes with low bridge clearances or narrow cobblestone alleys that fail clearance requirements.
   - Calculates realistic travel times and distances across Metropolitan GIS networks.

2. **Multi-Criteria Concurrent Ambulance Allocation**:
   - Triage severity matching (ALS, BLS, Rapid Flyer).
   - Real-time hospital ICU and bed availability tracking.
   - Thread-safe and asyncio lock protected to eliminate double-dispatch race conditions.

3. **Dynamic Traffic Simulation**:
   - Models live arterial congestion and rush hour spikes.
   - Dynamic green emergency corridor toggling to reduce response times.

4. **Modern UI/UX Dispatch Dashboard**:
   - Styled after modern logistics and telematics platforms (e.g. GlobeTrans / Koryear).
   - Live Leaflet map visualization with fleet status, route overlays, and dispatch telemetry.
   - Real-time updates via WebSockets.

---

## 🚀 Quickstart Guide

### 1. Backend Setup
```bash
cd backend
# Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start FastAPI Server
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2. Access the Application
Open your browser and navigate to:
```
http://127.0.0.1:8000
```
- API Documentation: `http://127.0.0.1:8000/docs`
- Interactive Map & Dispatch UI: `http://127.0.0.1:8000/`

### 3. Run Automated Tests
```bash
cd backend
$env:PYTHONPATH = "."
.\venv\Scripts\pytest.exe -v
```
