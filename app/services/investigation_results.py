"""
Full investigation results, persisted for the ticket detail view.

/investigate's response (evidence[], explanation, search_note) was
previously ephemeral -- returned once to the browser and never kept
anywhere. TT_AI_AUDIT_LOG's INVESTIGATE line only ever held a short
summary (search_tier, match_confidence, evidence_coverage, rows_returned),
which is enough for a dense history table but not enough to reopen a real
ticket and see what the AI actually said. This table closes that gap,
keyed by the same LOG_ID as the audit log's own INVESTIGATE row (see
log_event()'s RETURNING LOG_ID) rather than inventing a second ID scheme.

Only investigations with real evidence are persisted -- a not_found result
has nothing to show in a detail view beyond what the history row already
says, and the whole point of skipping it is not to fake a "case file" for
an empty result (see investigations/history's has_detail flag).
"""
import datetime
import json
import os

import oracledb
from dotenv import load_dotenv

load_dotenv()


def _json_default(value):
    # str() on a datetime/date produces "2026-08-02 00:00:00" (space
    # separator) -- the frontend's date formatter expects ISO's "T"
    # separator (what FastAPI's own JSON encoder produces on the live
    # /investigate response), so a plain str() fallback here silently
    # breaks date rendering only for evidence read back from storage.
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


def _get_connection():
    return oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN")
    )


def save_investigation_result(log_id, explanation, search_note, evidence, complaint_text=None):
    """
    complaint_text is the agent's original submission (already scanned by
    the Gateway at /investigate time, see app/main.py) -- persisted so a
    ticket can later become real case-memory precedent (see
    app/ai/case_memory.py's save_verified_case) without ever being
    reconstructed or faked from the classification labels.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO TT_AI_INVESTIGATION_RESULTS (LOG_ID, EXPLANATION, SEARCH_NOTE, EVIDENCE_JSON, COMPLAINT_TEXT)
        VALUES (:log_id, :explanation, :search_note, :evidence_json, :complaint_text)
    """, log_id=log_id, explanation=explanation, search_note=search_note,
         evidence_json=json.dumps(evidence, default=_json_default, ensure_ascii=False),
         complaint_text=complaint_text)
    conn.commit()
    cursor.close()
    conn.close()


def get_investigation_result(log_id):
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT EXPLANATION, SEARCH_NOTE, EVIDENCE_JSON, COMPLAINT_TEXT, SUPERSEDED_BY_LOG_ID
        FROM TT_AI_INVESTIGATION_RESULTS
        WHERE LOG_ID = :log_id
    """, log_id=log_id)
    row = cursor.fetchone()

    if row is None:
        cursor.close()
        conn.close()
        return None

    # LOBs must be read while the connection is still open -- the thin
    # driver streams them lazily, so closing the connection first (as the
    # code used to) raises DPY-1001 the moment .read() is called.
    explanation, search_note, evidence_json, complaint_text, superseded_by_log_id = row
    explanation = explanation.read() if explanation is not None else None
    search_note = search_note.read() if search_note is not None else None
    evidence_raw = evidence_json.read() if evidence_json is not None else None
    complaint_text = complaint_text.read() if complaint_text is not None else None

    cursor.close()
    conn.close()

    return {
        "explanation": explanation,
        "search_note": search_note,
        "evidence": json.loads(evidence_raw) if evidence_raw else [],
        "complaint_text": complaint_text,
        "superseded_by_log_id": superseded_by_log_id,
    }


def mark_superseded(log_id, new_log_id):
    """
    Records that this ticket's complaint text turned out to need a fix and
    was re-investigated for real (a fresh /investigate run, full Gateway
    scan + classification + search, not a patch) rather than mutating this
    row's own EXPLANATION/EVIDENCE_JSON in place -- TT_AI_INVESTIGATION_RESULTS
    is documented as "not regenerated or re-run", and the audit log this
    row is keyed to is append-only/tamper-evident, so nothing already
    logged is rewritten. This is purely a forward pointer for the detail
    view to say "corrected -> see INV-{new_log_id}", nothing more.
    Returns True if a row was actually updated.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE TT_AI_INVESTIGATION_RESULTS SET SUPERSEDED_BY_LOG_ID = :new_log_id WHERE LOG_ID = :log_id
    """, new_log_id=new_log_id, log_id=log_id)
    updated = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    return updated


def get_superseded_map(log_ids):
    """Which of these LOG_IDs were later corrected/re-investigated, and
    what they were superseded by -- used by get_investigation_history()
    to show a Statut column without an N+1 query per row."""
    if not log_ids:
        return {}

    conn = _get_connection()
    cursor = conn.cursor()
    binds = {f"id_{i}": lid for i, lid in enumerate(log_ids)}
    placeholders = ", ".join(f":{k}" for k in binds)
    cursor.execute(f"""
        SELECT LOG_ID, SUPERSEDED_BY_LOG_ID FROM TT_AI_INVESTIGATION_RESULTS
        WHERE LOG_ID IN ({placeholders}) AND SUPERSEDED_BY_LOG_ID IS NOT NULL
    """, binds)
    result = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    return result


def get_result_log_ids(log_ids):
    """Which of these LOG_IDs actually have a persisted result -- used by
    get_investigation_history() to set has_detail per row without an N+1
    query per history row."""
    if not log_ids:
        return set()

    conn = _get_connection()
    cursor = conn.cursor()
    binds = {f"id_{i}": lid for i, lid in enumerate(log_ids)}
    placeholders = ", ".join(f":{k}" for k in binds)
    cursor.execute(f"""
        SELECT LOG_ID FROM TT_AI_INVESTIGATION_RESULTS WHERE LOG_ID IN ({placeholders})
    """, binds)
    result = {r[0] for r in cursor.fetchall()}
    cursor.close()
    conn.close()
    return result
