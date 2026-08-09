import os
from datetime import datetime, timedelta
import oracledb
from dotenv import load_dotenv
from app.security.audit import log_event

load_dotenv()

ALERT_THRESHOLD = 3
WINDOW_MINUTES = 15
LOCK_DURATION_MINUTES = 15

REDTEAM_EXEMPT_USERS = {"redteam_runner"}


def _get_connection():
    return oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN")
    )


def is_locked(username: str) -> bool:
    if username in REDTEAM_EXEMPT_USERS:
        return False

    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT LOCKED_UNTIL FROM TT_AI_USERS WHERE USERNAME = :username",
        username=username
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None or row[0] is None:
        return False

    return row[0] > datetime.now()


def check_and_apply_lockout(username: str, role: str, ip_address: str = None):
    if username in REDTEAM_EXEMPT_USERS:
        return

    conn = _get_connection()
    cursor = conn.cursor()

    window_start = datetime.now() - timedelta(minutes=WINDOW_MINUTES)
    cursor.execute("""
        SELECT COUNT(*) FROM TT_AI_AUDIT_LOG
        WHERE USERNAME = :username
        AND EVENT_TYPE = 'SECURITY_ALERT'
        AND CREATED_AT >= :window_start
    """, username=username, window_start=window_start)

    alert_count = cursor.fetchone()[0]

    if alert_count >= ALERT_THRESHOLD:
        lock_until = datetime.now() + timedelta(minutes=LOCK_DURATION_MINUTES)
        cursor.execute("""
            UPDATE TT_AI_USERS SET LOCKED_UNTIL = :lock_until WHERE USERNAME = :username
        """, lock_until=lock_until, username=username)
        conn.commit()

        log_event(
            "SECURITY_LOCKOUT",
            username=username,
            role=role,
            details=f"Account locked until {lock_until.isoformat()} after {alert_count} SECURITY_ALERT events in {WINDOW_MINUTES} min",
            ip_address=ip_address
        )

    cursor.close()
    conn.close()
