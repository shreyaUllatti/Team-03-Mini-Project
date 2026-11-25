"""End-to-end integration test for the 7-stage IERS workflow, two-leg routing,
dispatcher verification, complaints, and zero-OSM basemap verification."""
import json
import os
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"


def _req(path, method="GET", body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=25) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw.startswith("{") or raw.startswith("[") else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, (json.loads(raw) if raw.startswith("{") else raw)


def _login(email, password):
    st, data = _req("/api/v1/auth/login", "POST", {"email": email, "password": password})
    assert st == 200
    return data["access_token"], data["user"]


def test_complete_7_stage_workflow_and_complaints():
    tok_cit, _ = _login("citizen@iers.gov.in", "citizen123")
    tok_disp, _ = _login("dispatcher@iers.gov.in", "dispatch123")
    tok_op, _ = _login("operator1@iers.gov.in", "operator123")

    _req("/api/v1/ambulances/AMB_01/status", "PATCH", {"status": "AVAILABLE"}, token=tok_disp)

    st, created = _req(
        "/api/v1/incidents/create",
        "POST",
        {
            "incident_type": "Acute Cardiac Arrest",
            "people_affected": 1,
            "latitude": 15.3647,
            "longitude": 75.1240,
            "description": "End-to-end pytest verification",
            "location_source": "CITIZEN_PORTAL",
        },
        token=tok_cit,
    )
    assert st == 200
    inc_id = created["incident_id"]

    _req("/api/v1/ambulances/AMB_01/status", "PATCH", {"status": "AVAILABLE"}, token=tok_disp)

    st, analysis = _req(f"/api/v1/workflow/analyze/{inc_id}", token=tok_disp)
    assert st == 200
    assert len(analysis["ranked_ambulances"]) >= 1
    assert len(analysis["ranked_hospitals"]) >= 1
    assert analysis["ranked_ambulances"][0]["eta_seconds"] > 0
    assert analysis["ranked_hospitals"][0]["eta_seconds"] > 0

    chosen_hosp = analysis["ranked_hospitals"][0]["hospital_id"]

    st, assigned = _req(
        f"/api/v1/workflow/assign/{inc_id}",
        "POST",
        {"ambulance_id": "AMB_01", "hospital_id": chosen_hosp, "override_reason": "Closest ALS unit verified"},
        token=tok_disp,
    )
    assert st == 200
    assert assigned["status"] == "ASSIGNED"
    assert len(assigned["leg1_route"]["coordinates"]) > 2

    st, r1 = _req(f"/api/v1/workflow/crew-action/{inc_id}", "POST", {"action": "ACCEPT_AND_START"}, token=tok_op)
    assert st == 200 and r1["status"] == "EN_ROUTE_TO_EMERGENCY"

    st, r2 = _req(f"/api/v1/workflow/crew-action/{inc_id}", "POST", {"action": "ARRIVED_AT_EMERGENCY"}, token=tok_op)
    assert st == 200 and r2["status"] == "ARRIVED_AT_EMERGENCY"

    st, r3 = _req(f"/api/v1/workflow/crew-action/{inc_id}", "POST", {"action": "PATIENT_PICKED_UP"}, token=tok_op)
    assert st == 200 and r3["status"] == "PATIENT_PICKED_UP"
    assert r3["leg2_route"] is not None and len(r3["leg2_route"]["coordinates"]) > 2

    st, r4 = _req(f"/api/v1/workflow/crew-action/{inc_id}", "POST", {"action": "START_HOSPITAL_JOURNEY"}, token=tok_op)
    assert st == 200 and r4["status"] == "EN_ROUTE_TO_HOSPITAL"

    st, r5 = _req(f"/api/v1/workflow/crew-action/{inc_id}", "POST", {"action": "ARRIVED_AT_HOSPITAL"}, token=tok_op)
    assert st == 200 and r5["status"] == "ARRIVED_AT_HOSPITAL"

    st, r6 = _req(f"/api/v1/workflow/crew-action/{inc_id}", "POST", {"action": "SUBMIT_COMPLETION"}, token=tok_op)
    assert st == 200 and r6["status"] == "PENDING_VERIFICATION"

    st, ver = _req(
        f"/api/v1/workflow/verify/{inc_id}",
        "POST",
        {"decision": "APPROVE", "notes": "Handover verified"},
        token=tok_disp,
    )
    assert st == 200 and ver["status"] == "COMPLETED"

    st, ambs = _req("/api/v1/ambulances", token=tok_disp)
    amb1 = next(a for a in ambs if a.get("ambulance_code") == "AMB_01" or a["id"] == "AMB_01")
    assert amb1["status"] == "AVAILABLE"

    st, cmp = _req(
        "/api/v1/complaints",
        "POST",
        {"incident_id": inc_id, "category": "RESPONSE_DELAY", "description": "Test complaint"},
        token=tok_cit,
    )
    assert st == 200
    st, res_cmp = _req(
        f"/api/v1/complaints/{cmp['complaint_id']}",
        "PATCH",
        {"status": "RESOLVED", "dispatcher_response": "Reviewed and logged"},
        token=tok_disp,
    )
    assert st == 200 and res_cmp["status"] == "RESOLVED"


def test_no_openstreetmap_basemap_in_frontend():
    frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "index.html"))
    with open(frontend_path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "tile.openstreetmap.org" not in html
    assert "/tiles/{z}/{x}/{y}.png" in html
