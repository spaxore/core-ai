import ast
import os
import re
import hashlib
import oracledb
from dotenv import load_dotenv

load_dotenv()

GENESIS_HASH = "0" * 64

def log_event(event_type: str, username: str = None, role: str = None, details: str = None, ip_address: str = None):
    """
    Returns the new row's LOG_ID (via RETURNING INTO) so callers that need
    to link something to this specific audit entry can -- e.g. /investigate
    persisting full results keyed by the same ID as its own INVESTIGATE
    log line, instead of inventing a second ID scheme. This is purely an
    addition to what's returned; the insert itself, and therefore the hash
    chain, is unchanged.
    """
    conn = oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN")
    )
    cursor = conn.cursor()

    cursor.execute("""
        SELECT ROW_HASH FROM (
            SELECT ROW_HASH FROM TT_AI_AUDIT_LOG ORDER BY LOG_ID DESC
        ) WHERE ROWNUM = 1
    """)
    row = cursor.fetchone()
    prev_hash = row[0] if row and row[0] else GENESIS_HASH

    hash_input = f"{event_type}|{username}|{role}|{details}|{ip_address}|{prev_hash}"
    row_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    new_log_id = cursor.var(int)
    cursor.execute("""
        INSERT INTO TT_AI_AUDIT_LOG (EVENT_TYPE, USERNAME, ROLE, DETAILS, IP_ADDRESS, PREV_HASH, ROW_HASH)
        VALUES (:event_type, :username, :role, :details, :ip_address, :prev_hash, :row_hash)
        RETURNING LOG_ID INTO :new_log_id
    """, event_type=event_type, username=username, role=role, details=details,
         ip_address=ip_address, prev_hash=prev_hash, row_hash=row_hash, new_log_id=new_log_id)

    conn.commit()
    cursor.close()
    conn.close()

    return new_log_id.getvalue()[0]

def get_recent_events(limit: int = 20):
    conn = oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN")
    )
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM (
            SELECT LOG_ID, EVENT_TYPE, USERNAME, ROLE, DETAILS, IP_ADDRESS, CREATED_AT
            FROM TT_AI_AUDIT_LOG
            ORDER BY LOG_ID DESC
        ) WHERE ROWNUM <= :limit
    """, limit=limit)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "log_id": r[0],
            "event_type": r[1],
            "username": r[2],
            "role": r[3],
            "details": r[4],
            "ip_address": r[5],
            "created_at": r[6].isoformat() if r[6] else None
        }
        for r in rows
    ]


def _extract_field(details: str, key: str):
    """
    Pulls one key=value pair out of an INVESTIGATE audit log's DETAILS
    string (see the f-string in app/main.py's /investigate handler --
    this parser exists to match that exact format, not a general-purpose
    one). Non-greedy {...} handling is needed for evidence_coverage,
    whose value is itself a dict containing commas -- a naive
    split-on-comma would cut it in half.
    """
    match = re.search(rf"{key}=(\{{.*?\}}|[^,]*)", details or "")
    if not match:
        return None
    value = match.group(1).strip()
    return None if value == "None" else value


def _parse_investigation_details(details: str) -> dict:
    evidence_coverage_raw = _extract_field(details, "evidence_coverage")
    evidence_coverage = None
    if evidence_coverage_raw:
        try:
            evidence_coverage = ast.literal_eval(evidence_coverage_raw)
        except (ValueError, SyntaxError):
            evidence_coverage = None

    rows_returned_raw = _extract_field(details, "rows_returned")

    return {
        "category": _extract_field(details, "category"),
        "msisdn": _extract_field(details, "msisdn"),
        "da_value": _extract_field(details, "da_value"),
        "target_amount": _extract_field(details, "target_amount"),
        "target_volume_gb": _extract_field(details, "target_volume_gb"),
        "search_tier": _extract_field(details, "search_tier"),
        "match_confidence": _extract_field(details, "match_confidence"),
        "evidence_coverage": evidence_coverage,
        "rows_returned": int(rows_returned_raw) if rows_returned_raw and rows_returned_raw.isdigit() else None,
    }


def get_investigation_summary(log_id: int):
    """
    Direct by-ID lookup of one INVESTIGATE audit row, parsed the same way
    as get_investigation_history()'s rows. Deliberately does NOT apply the
    REDTEAM_EXEMPT_USERS exclusion that list view does -- that exclusion
    exists to keep attack-testing noise out of the browsable list, not to
    make an existing, already-persisted ticket unreachable by its own ID
    (e.g. if a real detail record happens to belong to a redteam_runner
    call). Used by GET /investigations/{log_id} to build the detail view.
    """
    conn = oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN")
    )
    cursor = conn.cursor()
    cursor.execute("""
        SELECT LOG_ID, USERNAME, ROLE, DETAILS, CREATED_AT
        FROM TT_AI_AUDIT_LOG
        WHERE LOG_ID = :log_id AND EVENT_TYPE = 'INVESTIGATE'
    """, log_id=log_id)
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None:
        return None

    row_log_id, username, role, details, created_at = row
    parsed = _parse_investigation_details(details)
    return {
        "log_id": row_log_id,
        "username": username,
        "role": role,
        "created_at": created_at.isoformat() if created_at else None,
        **parsed,
    }


def get_investigation_history(limit: int = 50, category: str = None, msisdn: str = None):
    """
    Read-only list over INVESTIGATE events already in the tamper-evident
    audit log -- no new table, no change to log_event()'s hash-chain
    write path. DETAILS is free text (shared across every event type),
    so this filters to INVESTIGATE specifically and parses that one
    known, self-produced format back into structured fields for the
    history UI, rather than exposing the raw string.

    Excludes REDTEAM_EXEMPT_USERS (redteam_runner) -- that account exists
    only to fire ARC/llm-redteam attacks without tripping Auto-Lock, so
    its runs are attack traffic, not real investigation work, and would
    otherwise flood this list with noise for the agents actually using it.

    category/msisdn filters are applied as a DETAILS LIKE match before
    parsing (cheap, index-free but fine at this scale) -- exact enough
    since both fields are logged in a fixed key=value shape.
    """
    conn = oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN")
    )
    cursor = conn.cursor()

    # Lazy import: lockout.py imports log_event from this module at load
    # time, so a top-level import here would be circular.
    from app.security.lockout import REDTEAM_EXEMPT_USERS

    where_clauses = ["EVENT_TYPE = 'INVESTIGATE'"]
    params = {"limit": limit}

    exempt_users = sorted(REDTEAM_EXEMPT_USERS)
    if exempt_users:
        excl_binds = [f":excl_user_{i}" for i in range(len(exempt_users))]
        where_clauses.append(f"USERNAME NOT IN ({', '.join(excl_binds)})")
        for i, exempt_username in enumerate(exempt_users):
            params[f"excl_user_{i}"] = exempt_username

    if category:
        where_clauses.append("DETAILS LIKE :category_pattern")
        params["category_pattern"] = f"%category={category},%"
    if msisdn:
        where_clauses.append("DETAILS LIKE :msisdn_pattern")
        params["msisdn_pattern"] = f"%msisdn={msisdn},%"

    query = f"""
        SELECT * FROM (
            SELECT LOG_ID, USERNAME, ROLE, DETAILS, CREATED_AT
            FROM TT_AI_AUDIT_LOG
            WHERE {" AND ".join(where_clauses)}
            ORDER BY LOG_ID DESC
        ) WHERE ROWNUM <= :limit
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # Lazy imports for the same reason as REDTEAM_EXEMPT_USERS above --
    # neither sibling module imports audit.py, but keeping the pattern
    # consistent (and avoiding a module-load-order dependency on a
    # sibling package from a security/ one) is deliberate.
    from app.services.investigation_results import get_result_log_ids, get_superseded_map
    from app.ai.case_memory import get_verified_case_status_map

    log_ids = [r[0] for r in rows]
    detailed_ids = get_result_log_ids(log_ids)
    verified_status_by_log_id = get_verified_case_status_map(log_ids)
    superseded_by_log_id_map = get_superseded_map(log_ids)

    history = []
    for log_id, username, role, details, created_at in rows:
        parsed = _parse_investigation_details(details)
        # Corrected takes priority over validated/rejected -- a ticket
        # that's been re-investigated is no longer "the current answer"
        # regardless of what status it carried before the correction.
        superseded_by_log_id = superseded_by_log_id_map.get(log_id)
        verification_status = "corrected" if superseded_by_log_id else verified_status_by_log_id.get(log_id)
        history.append({
            "log_id": log_id,
            "username": username,
            "role": role,
            "created_at": created_at.isoformat() if created_at else None,
            "has_detail": log_id in detailed_ids,
            "verification_status": verification_status,
            "superseded_by_log_id": superseded_by_log_id,
            **parsed,
        })
    return history


# Ordinal mapping for a rough "average confidence" indicator on the empty
# state's stats strip. match_confidence is a HIGH/MEDIUM/LOW category, not
# a real number -- this is a simple 3-point scale (not a measured score)
# so an agent gets a quick sense of "mostly solid today" vs "mostly weak
# leads today", not a precise statistic.
_CONFIDENCE_SCORE = {"HIGH": 100, "MEDIUM": 50, "LOW": 0}


def get_investigation_stats():
    """
    Today's investigation count + a rough average-confidence percentage,
    for the New Investigation view's empty-state stats strip. Same
    INVESTIGATE-event/REDTEAM_EXEMPT_USERS filtering as
    get_investigation_history() -- reuses that parsing rather than a
    separate SQL aggregate, since the value only exists inside DETAILS as
    free text, same as everything else this module parses back out.
    """
    from app.security.lockout import REDTEAM_EXEMPT_USERS

    conn = oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN")
    )
    cursor = conn.cursor()

    where_clauses = ["EVENT_TYPE = 'INVESTIGATE'", "CREATED_AT >= TRUNC(SYSDATE)"]
    params = {}
    exempt_users = sorted(REDTEAM_EXEMPT_USERS)
    if exempt_users:
        excl_binds = [f":excl_user_{i}" for i in range(len(exempt_users))]
        where_clauses.append(f"USERNAME NOT IN ({', '.join(excl_binds)})")
        for i, exempt_username in enumerate(exempt_users):
            params[f"excl_user_{i}"] = exempt_username

    cursor.execute(f"""
        SELECT DETAILS FROM TT_AI_AUDIT_LOG WHERE {" AND ".join(where_clauses)}
    """, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    scores = []
    for (details,) in rows:
        confidence = _extract_field(details, "match_confidence")
        if confidence in _CONFIDENCE_SCORE:
            scores.append(_CONFIDENCE_SCORE[confidence])

    avg_confidence_pct = round(sum(scores) / len(scores)) if scores else None

    return {
        "investigations_today": len(rows),
        "avg_confidence_pct": avg_confidence_pct,
    }
