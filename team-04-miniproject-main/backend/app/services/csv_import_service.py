"""
Hospital Bulk CSV Import Service
- UTF-8 CSV parsing with formula-injection protection
- Auto column mapping + custom mapping
- Strict validation & cross-hospital ownership enforcement (never trusts CSV hospital_id)
- Preserves real hospital geographical coordinates (never overwrites lat/lon/geom)
- Transactional persistence to iers.hospitals, iers.hospital_capacity_history, iers.hospital_csv_imports
"""
import csv
import io
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_ROWS = 500

SUPPORTED_FIELDS = {
    "hospital_id": {"required": False, "type": "str", "aliases": ["hospital_id", "hosp_id", "id", "facility_id"]},
    "total_beds": {"required": True, "type": "int", "aliases": ["total_beds", "beds", "general_beds", "bed_capacity"]},
    "icu_available": {"required": True, "type": "int", "aliases": ["icu_available", "icu_beds", "icu", "available_icu"]},
    "trauma_beds_available": {"required": False, "type": "int", "aliases": ["trauma_beds_available", "trauma_beds", "trauma"]},
    "emergency_dept_capacity": {"required": False, "type": "int", "aliases": ["emergency_dept_capacity", "ed_capacity", "er_capacity"]},
    "has_icu": {"required": False, "type": "bool", "aliases": ["has_icu", "icu_facility"]},
    "has_trauma_care": {"required": False, "type": "bool", "aliases": ["has_trauma_care", "trauma_care", "trauma_facility"]},
    "has_cardiology": {"required": False, "type": "bool", "aliases": ["has_cardiology", "cardiology"]},
    "service_status": {"required": False, "type": "str", "aliases": ["service_status", "status"]},
    "service_notes": {"required": False, "type": "str", "aliases": ["service_notes", "notes", "remarks"]},
}

VALID_BOOL_TRUE = {"true", "yes", "1", "y", "on"}
VALID_BOOL_FALSE = {"false", "no", "0", "n", "off"}
VALID_SERVICE_STATUS = {"OPERATIONAL", "LIMITED", "DIVERTING", "MAINTENANCE"}


def sanitize_cell(val: Any) -> str:
    s = ("" if val is None else str(val)).strip()
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        s = "'" + s
    return s


def parse_bool(raw: str) -> Tuple[Optional[bool], Optional[str]]:
    if raw == "":
        return None, None
    low = raw.strip().lower()
    if low in VALID_BOOL_TRUE:
        return True, None
    if low in VALID_BOOL_FALSE:
        return False, None
    return None, f"Invalid boolean value '{raw}' (use true/false/yes/no/1/0)"


def parse_nonneg_int(raw: str, field: str, required: bool) -> Tuple[Optional[int], Optional[str]]:
    if raw == "":
        if required:
            return None, f"Missing required field '{field}'"
        return None, None
    try:
        v = int(raw.strip())
        if v < 0:
            return None, f"'{field}' must be a non-negative integer (got {v})"
        return v, None
    except ValueError:
        return None, f"'{field}' must be an integer (got '{raw}')"


def auto_detect_mapping(headers: List[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    norm_headers = {h.strip().lower(): h for h in headers}
    for db_field, meta in SUPPORTED_FIELDS.items():
        for alias in meta["aliases"]:
            if alias in norm_headers:
                mapping[db_field] = norm_headers[alias]
                break
    return mapping


def get_sample_csv(hospital_id: str) -> str:
    return (
        "hospital_id,total_beds,icu_available,trauma_beds_available,emergency_dept_capacity,has_icu,has_trauma_care,has_cardiology,service_status,service_notes\n"
        f"{hospital_id},650,42,18,30,true,true,true,OPERATIONAL,Morning shift capacity update\n"
    )


def parse_and_validate_csv(
    csv_text: str,
    auth_hospital_id: str,
    custom_mapping: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    raw_bytes = csv_text.encode("utf-8")
    if len(raw_bytes) > MAX_FILE_BYTES:
        raise ValueError(f"CSV exceeds maximum file size of {MAX_FILE_BYTES // (1024*1024)} MB")

    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []
    if not headers:
        raise ValueError("CSV file has no header row")

    mapping = custom_mapping if custom_mapping else auto_detect_mapping(headers)
    rows = list(reader)
    if len(rows) > MAX_ROWS:
        raise ValueError(f"CSV exceeds maximum row limit of {MAX_ROWS} rows")

    valid_rows: List[Dict[str, Any]] = []
    invalid_rows: List[Dict[str, Any]] = []
    seen_keys = set()
    duplicate_count = 0

    for idx, raw_row in enumerate(rows, start=2):  # 1-based + header
        errors: List[str] = []

        def get_col(field_name: str) -> str:
            col = mapping.get(field_name)
            if not col or col not in raw_row:
                return ""
            return (raw_row.get(col) or "").strip()

        row_hid = get_col("hospital_id")
        if row_hid and row_hid != auth_hospital_id:
            errors.append(
                f"Cross-hospital access denied: CSV hospital_id '{row_hid}' does not match authenticated hospital '{auth_hospital_id}'"
            )

        total_beds, e1 = parse_nonneg_int(get_col("total_beds"), "total_beds", True)
        icu_avail, e2 = parse_nonneg_int(get_col("icu_available"), "icu_available", True)
        trauma_beds, e3 = parse_nonneg_int(get_col("trauma_beds_available"), "trauma_beds_available", False)
        ed_cap, e4 = parse_nonneg_int(get_col("emergency_dept_capacity"), "emergency_dept_capacity", False)
        for e in (e1, e2, e3, e4):
            if e:
                errors.append(e)

        if total_beds is not None and icu_avail is not None and icu_avail > total_beds:
            errors.append(f"icu_available ({icu_avail}) cannot exceed total_beds ({total_beds})")
        if total_beds is not None and trauma_beds is not None and trauma_beds > total_beds:
            errors.append(f"trauma_beds_available ({trauma_beds}) cannot exceed total_beds ({total_beds})")

        has_icu, eb1 = parse_bool(get_col("has_icu"))
        has_trauma, eb2 = parse_bool(get_col("has_trauma_care"))
        has_cardio, eb3 = parse_bool(get_col("has_cardiology"))
        for e in (eb1, eb2, eb3):
            if e:
                errors.append(e)

        svc_status = get_col("service_status").upper() or "OPERATIONAL"
        if svc_status not in VALID_SERVICE_STATUS:
            errors.append(f"Invalid service_status '{svc_status}' (allowed: {', '.join(sorted(VALID_SERVICE_STATUS))})")

        notes = sanitize_cell(get_col("service_notes"))

        dedup_key = (auth_hospital_id, total_beds, icu_avail, trauma_beds, ed_cap, svc_status, notes)
        is_dup = dedup_key in seen_keys
        if is_dup:
            duplicate_count += 1
            errors.append("Duplicate row detected in uploaded CSV")
        else:
            seen_keys.add(dedup_key)

        record = {
            "row_number": idx,
            "hospital_id": auth_hospital_id,
            "total_beds": total_beds,
            "icu_available": icu_avail,
            "trauma_beds_available": trauma_beds,
            "emergency_dept_capacity": ed_cap,
            "has_icu": has_icu,
            "has_trauma_care": has_trauma,
            "has_cardiology": has_cardio,
            "service_status": svc_status,
            "service_notes": notes,
        }

        if errors:
            invalid_rows.append({"row_number": idx, "errors": errors, "raw": record})
        else:
            valid_rows.append(record)

    return {
        "headers": headers,
        "mapping": mapping,
        "supported_fields": list(SUPPORTED_FIELDS.keys()),
        "total_rows": len(rows),
        "valid_count": len(valid_rows),
        "invalid_count": len(invalid_rows),
        "duplicate_count": duplicate_count,
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
    }


async def execute_hospital_csv_import(
    db: AsyncSession,
    csv_text: str,
    filename: str,
    auth_hospital_id: str,
    uploaded_by: str,
    import_mode: str = "UPDATE_EXISTING",
    custom_mapping: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    mode = "INSERT_NEW" if import_mode.upper() == "INSERT_NEW" else "UPDATE_EXISTING"
    parsed = parse_and_validate_csv(csv_text, auth_hospital_id, custom_mapping)
    import_id = f"IMP_{int(datetime.utcnow().timestamp() * 1000)}"

    # If there are invalid rows, abort transactionally and record failed import audit
    if parsed["invalid_count"] > 0 or parsed["valid_count"] == 0:
        status = "FAILED_VALIDATION"
        await db.execute(
            text("""
                INSERT INTO public.hospital_csv_imports (
                    import_id, hospital_id, uploaded_by, original_filename, import_mode,
                    total_rows, successful_rows, failed_rows, status, error_summary
                ) VALUES (
                    :iid, CAST(:hid AS uuid), :ub, :fn, :mode,
                    :tot, 0, :fail, :st, CAST(:err AS jsonb)
                )
            """),
            {
                "iid": import_id, "hid": auth_hospital_id, "ub": uploaded_by,
                "fn": sanitize_cell(filename), "mode": mode,
                "tot": parsed["total_rows"], "fail": parsed["invalid_count"],
                "st": status, "err": json.dumps(parsed["invalid_rows"][:50]),
            },
        )
        await db.commit()
        return {
            "import_id": import_id,
            "status": status,
            "total_rows": parsed["total_rows"],
            "successful_rows": 0,
            "failed_rows": parsed["invalid_count"],
            "errors": parsed["invalid_rows"],
        }

    # Transactional update of authenticated hospital + capacity history (never overwrites coordinates!)
    applied = 0
    for rec in parsed["valid_rows"]:
        await db.execute(
            text("""
                UPDATE public.hospitals
                SET total_beds = :tb,
                    available_beds = :tb,
                    icu_available = :icu,
                    trauma_beds_available = COALESCE(:trb, trauma_beds_available),
                    emergency_dept_capacity = COALESCE(:edc, emergency_dept_capacity),
                    has_icu = COALESCE(:hicu, has_icu),
                    has_trauma_care = COALESCE(:htr, has_trauma_care),
                    has_cardiology = COALESCE(:hcar, has_cardiology),
                    service_status = :sst,
                    service_notes = :snt
                WHERE hospital_id = CAST(:hid AS uuid)
            """),
            {
                "tb": rec["total_beds"], "icu": rec["icu_available"],
                "trb": rec["trauma_beds_available"], "edc": rec["emergency_dept_capacity"],
                "hicu": rec["has_icu"], "htr": rec["has_trauma_care"], "hcar": rec["has_cardiology"],
                "sst": rec["service_status"], "snt": rec["service_notes"],
                "hid": auth_hospital_id,
            },
        )
        await db.execute(
            text("""
                INSERT INTO public.hospital_capacity_history (
                    hospital_id, changed_by, total_beds, icu_available,
                    trauma_beds_available, emergency_dept_capacity, service_status, remarks
                ) VALUES (CAST(:hid AS uuid), :cb, :tb, :icu, :trb, :edc, :sst, :rem)
            """),
            {
                "hid": auth_hospital_id, "cb": uploaded_by,
                "tb": rec["total_beds"], "icu": rec["icu_available"],
                "trb": rec["trauma_beds_available"], "edc": rec["emergency_dept_capacity"],
                "sst": rec["service_status"], "rem": f"CSV Import {import_id}: {rec['service_notes']}",
            },
        )
        applied += 1

    await db.execute(
        text("""
            INSERT INTO public.hospital_csv_imports (
                import_id, hospital_id, uploaded_by, original_filename, import_mode,
                total_rows, successful_rows, failed_rows, status, error_summary
            ) VALUES (
                :iid, CAST(:hid AS uuid), :ub, :fn, :mode, :tot, :ok, 0, 'COMPLETED', '[]'::jsonb
            )
        """),
        {
            "iid": import_id, "hid": auth_hospital_id, "ub": uploaded_by,
            "fn": sanitize_cell(filename), "mode": mode,
            "tot": parsed["total_rows"], "ok": applied,
        },
    )
    await db.commit()
    return {
        "import_id": import_id,
        "status": "COMPLETED",
        "total_rows": parsed["total_rows"],
        "successful_rows": applied,
        "failed_rows": 0,
        "errors": [],
    }
