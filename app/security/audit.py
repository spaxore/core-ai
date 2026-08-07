import os
import hashlib
import oracledb
from dotenv import load_dotenv

load_dotenv()

GENESIS_HASH = "0" * 64

def log_event(event_type: str, username: str = None, role: str = None, details: str = None, ip_address: str = None):
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

    cursor.execute("""
        INSERT INTO TT_AI_AUDIT_LOG (EVENT_TYPE, USERNAME, ROLE, DETAILS, IP_ADDRESS, PREV_HASH, ROW_HASH)
        VALUES (:event_type, :username, :role, :details, :ip_address, :prev_hash, :row_hash)
    """, event_type=event_type, username=username, role=role, details=details,
         ip_address=ip_address, prev_hash=prev_hash, row_hash=row_hash)

    conn.commit()
    cursor.close()
    conn.close()

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
