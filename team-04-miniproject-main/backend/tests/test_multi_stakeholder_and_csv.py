"""Integration tests for IERS 4-role RBAC, Hospital Bulk CSV Import, and BBOX GIS API."""
import json
import urllib.request
import urllib.error
import pytest

BASE = "http://127.0.0.1:8000"


def _req(path, method="GET", body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw.startswith("{") or raw.startswith("[") else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, (json.loads(raw) if raw.startswith("{") else raw)


def _login(email, password):
    st, data = _req("/api/v1/auth/login", "POST", {"email": email, "password": password})
    assert st == 200, f"Login failed for {email}: {data}"
    return data["access_token"], data["user"]


def test_four_stakeholder_roles_and_rbac():
    tok_cit, u_cit = _login("citizen@iers.gov.in", "citizen123")
    tok_disp, u_disp = _login("dispatcher@iers.gov.in", "dispatch123")
    tok_hosp, u_hosp = _login("hospital1@iers.gov.in", "hospital123")
    tok_op, u_op = _login("operator1@iers.gov.in", "operator123")

    assert u_cit["role"] == "CITIZEN"
    assert u_disp["role"] == "DISPATCHER"
    assert u_hosp["role"] == "HOSPITAL_STAFF"
    assert u_op["role"] == "AMBULANCE_OPERATOR"

    # Citizen cannot access dispatcher storage diagnostics or hospital staff facility
    st, _ = _req("/api/v1/system/storage-architecture", token=tok_cit)
    assert st == 403
    st, _ = _req("/api/v1/hospital/my-facility", token=tok_cit)
    assert st == 403

    # Hospital staff cannot access dispatcher traffic simulation or operator unit
    st, _ = _req("/api/v1/operator/my-unit", token=tok_hosp)
    assert st == 403

    # Dispatcher CAN access storage architecture (zero secrets)
    st, arch = _req("/api/v1/system/storage-architecture", token=tok_disp)
    assert st == 200
    assert len(arch["inventory"]) >= 10
    assert "password" not in json.dumps(arch).lower()


def test_hospital_csv_bulk_import_validation_and_security():
    tok_hosp, u_hosp = _login("hospital1@iers.gov.in", "hospital123")
    hid = u_hosp["assigned_entity_id"]

    # 1. Valid CSV preview & commit
    valid_csv = (
        "hospital_id,total_beds,icu_available,trauma_beds_available,emergency_dept_capacity,has_icu,has_trauma_care,has_cardiology,service_status,service_notes\n"
        f"{hid},650,44,18,30,true,true,true,OPERATIONAL,Automated pytest CSV import\n"
    )
    st, prev = _req("/api/v1/hospital/csv/preview", "POST", {"csv_text": valid_csv}, token=tok_hosp)
    assert st == 200
    assert prev["valid_count"] == 1 and prev["invalid_count"] == 0

    st, comm = _req(
        "/api/v1/hospital/csv/commit",
        "POST",
        {"csv_text": valid_csv, "filename": "kims_shift.csv", "import_mode": "UPDATE_EXISTING"},
        token=tok_hosp,
    )
    assert st == 200
    assert comm["status"] == "COMPLETED" and comm["successful_rows"] == 1

    # 2. Invalid row (icu_available > total_beds)
    bad_csv = f"hospital_id,total_beds,icu_available\n{hid},50,99\n"
    st, prev_bad = _req("/api/v1/hospital/csv/preview", "POST", {"csv_text": bad_csv}, token=tok_hosp)
    assert st == 200 and prev_bad["invalid_count"] == 1

    # 3. Duplicate row detection
    dup_csv = f"hospital_id,total_beds,icu_available\n{hid},650,40\n{hid},650,40\n"
    st, prev_dup = _req("/api/v1/hospital/csv/preview", "POST", {"csv_text": dup_csv}, token=tok_hosp)
    assert st == 200 and prev_dup["duplicate_count"] == 1

    # 4. Cross-hospital CSV manipulation attempt -> rejected
    cross_csv = "hospital_id,total_beds,icu_available\nHOSP_02,100,10\n"
    st, comm_cross = _req(
        "/api/v1/hospital/csv/commit",
        "POST",
        {"csv_text": cross_csv, "filename": "attack.csv", "import_mode": "UPDATE_EXISTING"},
        token=tok_hosp,
    )
    assert st == 200
    assert comm_cross["status"] == "FAILED_VALIDATION"
    assert comm_cross["successful_rows"] == 0


def test_bbox_zoom_dependent_gis_roads():
    st, fc_low = _req("/api/v1/gis/roads-bbox?min_lon=74.95&min_lat=15.30&max_lon=75.20&max_lat=15.50&zoom=10")
    assert st == 200
    assert fc_low["count"] > 0
    # Level 1 Metropolitan zoom (<=10) should only return trunk/primary highways
    assert all(f["properties"]["highway"] in ("trunk", "trunk_link", "primary", "primary_link") for f in fc_low["features"])
