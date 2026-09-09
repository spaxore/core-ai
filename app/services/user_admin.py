"""
Account administration for TT_AI_USERS -- create, activate/deactivate,
change role, unlock, reset password. SECURITY_ANALYST-only, enforced by
the routes in app/main.py, not by this module.
"""
import os
import secrets
from datetime import datetime

import oracledb
from dotenv import load_dotenv

from app.security.auth import hash_password, validate_password_strength
from app.security.audit import get_user_activity

load_dotenv()

VALID_ROLES = {"SUPPORT_AGENT", "SECURITY_ANALYST"}

# Excludes visually-ambiguous characters (0/O, 1/l/I) -- this is read off
# a screen and typed or copy-pasted once, not memorized.
_PASSWORD_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789!@#$%"


def _get_connection():
    return oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN"),
    )


def generate_password(length: int = 12) -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def _get_lock_reason(cursor, username: str):
    """
    The most recent lockout event for this account, whichever mechanism
    caused it -- SECURITY_LOCKOUT (Gateway/AI-subversion) or LOGIN_LOCKOUT
    (brute-force). Returns the event's own DETAILS text, which already
    describes what triggered it, rather than re-deriving a summary.
    """
    cursor.execute("""
        SELECT * FROM (
            SELECT DETAILS FROM TT_AI_AUDIT_LOG
            WHERE USERNAME = :username AND EVENT_TYPE IN ('SECURITY_LOCKOUT', 'LOGIN_LOCKOUT')
            ORDER BY LOG_ID DESC
        ) WHERE ROWNUM = 1
    """, username=username)
    row = cursor.fetchone()
    return row[0] if row else None


def list_users():
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.USERNAME, u.ROLE, u.IS_ACTIVE, u.CREATED_AT, u.LOCKED_UNTIL,
               l.EMAIL_ADDRESS,
               (SELECT MAX(a.CREATED_AT) FROM TT_AI_AUDIT_LOG a
                WHERE a.USERNAME = u.USERNAME AND a.EVENT_TYPE = 'LOGIN_SUCCESS') AS LAST_ACTIVE
        FROM TT_AI_USERS u
        LEFT JOIN TT_AI_USER_EMAIL_LINKS l ON l.USERNAME = u.USERNAME
        ORDER BY u.CREATED_AT
    """)
    rows = cursor.fetchall()

    users = []
    for username, role, is_active, created_at, locked_until, email, last_active in rows:
        locked = bool(locked_until and locked_until > datetime.now())
        users.append({
            "username": username,
            "role": role,
            "active": bool(is_active),
            "created_at": created_at.isoformat() if created_at else None,
            # Real linked-email-account address (see app/services/email_account.py)
            # -- None when the agent never linked one, not fabricated.
            "email": email,
            # Real last successful login from the audit log -- None for a
            # user who was created but has never logged in yet.
            "last_active": last_active.isoformat() if last_active else None,
            "locked": locked,
            "lock_reason": _get_lock_reason(cursor, username) if locked else None,
        })

    cursor.close()
    conn.close()
    return users


def get_user_activity_admin(username: str, limit: int = 20):
    """Thin re-export so the admin routes don't need a separate import
    path -- same function Profile's Mon activité already uses, just
    callable for any username by an analyst rather than only the caller's
    own."""
    return get_user_activity(username, limit=limit)


def user_exists(username: str) -> bool:
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM TT_AI_USERS WHERE USERNAME = :username", username=username)
    exists = cursor.fetchone() is not None
    cursor.close()
    conn.close()
    return exists


def create_user(username: str, role: str, password: str):
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of: {sorted(VALID_ROLES)}")
    if user_exists(username):
        raise ValueError(f"Username '{username}' already exists.")
    validate_password_strength(password)

    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO TT_AI_USERS (USERNAME, PASSWORD_HASH, ROLE, IS_ACTIVE)
        VALUES (:username, :password_hash, :role, 1)
    """, username=username, password_hash=hash_password(password), role=role)
    conn.commit()
    cursor.close()
    conn.close()


def set_user_role(username: str, role: str):
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of: {sorted(VALID_ROLES)}")

    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE TT_AI_USERS SET ROLE = :role WHERE USERNAME = :username", role=role, username=username)
    updated = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    return updated


def set_user_active(username: str, active: bool):
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE TT_AI_USERS SET IS_ACTIVE = :is_active WHERE USERNAME = :username",
        is_active=1 if active else 0, username=username,
    )
    updated = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    return updated


def unlock_user(username: str):
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE TT_AI_USERS SET LOCKED_UNTIL = NULL WHERE USERNAME = :username", username=username)
    updated = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    return updated


def reset_password(username: str) -> str:
    new_password = generate_password()
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE TT_AI_USERS SET PASSWORD_HASH = :password_hash WHERE USERNAME = :username",
        password_hash=hash_password(new_password), username=username,
    )
    updated = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    if not updated:
        raise ValueError(f"No user found with username '{username}'.")
    return new_password
