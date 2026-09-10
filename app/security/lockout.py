import os
from datetime import datetime, timedelta
import oracledb
from dotenv import load_dotenv
from app.security.audit import log_event

load_dotenv()

# Gateway (AI-subversion) lockout -- unchanged
ALERT_THRESHOLD = 3
WINDOW_MINUTES = 15
LOCK_DURATION_MINUTES = 15

# Login (brute-force) lockout -- separate mechanism, separate threshold,
# separate event type in the audit trail. Never conflated with the
# Gateway lockout above: this one is about credential guessing, the
# other is about AI subversion. Both write to the same LOCKED_UNTIL
# column, since either reason should equally block access everywhere.
LOGIN_ATTEMPT_THRESHOLD = 3
LOGIN_WINDOW_MINUTES = 15
LOGIN_LOCK_DURATION_MINUTES = 15

# Flagged-but-allowed (SECURITY_FLAG) escalation -- a third, independent
# mechanism. check_and_apply_lockout() above only reacts to SECURITY_ALERT
# (risk_score over the block threshold); a request scoring just under it
# is logged as SECURITY_FLAG and nothing ever acted on that before now.
# An attacker deliberately staying under the block threshold while
# iterating phrasing to find the Gateway's edge was invisible to lockout
# no matter how many attempts they made. Threshold set higher than the
# ALERT one (flags are a weaker, noisier signal -- flagging can also
# happen incidentally on legitimate complaints that merely mention a
# sensitive-sounding word) so this only fires on a real pattern of
# repeated near-misses, not one ambiguous complaint.
FLAG_THRESHOLD = 5
FLAG_WINDOW_MINUTES = 15
FLAG_LOCK_DURATION_MINUTES = 15

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


def is_account_active(username: str) -> bool:
    """Whether the account is currently enabled (IS_ACTIVE=1) -- checked on
    every authenticated request via get_current_user(), not just at
    /login. Previously IS_ACTIVE was only ever checked at login time, so
    deactivating a compromised or offboarded account (Utilisateurs ->
    Désactiver) blocked future logins but left that account's
    already-issued JWT working until it naturally expired -- up to
    ACCESS_TOKEN_EXPIRE_MINUTES later. No REDTEAM_EXEMPT_USERS bypass
    here, unlike is_locked() above: that exemption exists so an
    automated attack run doesn't get accidentally locked out mid-suite,
    but deactivation is always a deliberate admin action that should
    take effect regardless of which account it's applied to."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT IS_ACTIVE FROM TT_AI_USERS WHERE USERNAME = :username",
        username=username
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None:
        return False

    return bool(row[0])


def get_password_changed_at(username: str):
    """Returns the account's PASSWORD_CHANGED_AT (None if the password has
    never been changed since account creation, in which case there's
    nothing for a token to predate). Used by get_current_user() to reject
    a JWT issued before the account's most recent password change --
    without this, changing a password (self-service or admin reset)
    didn't actually invalidate a token an attacker already had; it just
    meant the old password stopped working for a *new* login."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT PASSWORD_CHANGED_AT FROM TT_AI_USERS WHERE USERNAME = :username",
        username=username
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None:
        return None

    return row[0]


def check_and_apply_lockout(username: str, role: str, ip_address: str = None):
    """Gateway (AI-subversion) lockout -- triggered by SECURITY_ALERT
    events from the AI Security Gateway. Unchanged from before."""
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


def check_and_apply_flag_escalation(username: str, role: str, ip_address: str = None):
    """Escalates to a full lockout after repeated SECURITY_FLAG events
    (flagged-but-allowed, risk_score > 0 but under the block threshold) --
    same shape as check_and_apply_lockout() above, counting a different
    event type against a separately-tunable threshold/window. Writes to
    the same LOCKED_UNTIL column and the same SECURITY_LOCKOUT event type
    as the ALERT-based lockout, with its own detail text distinguishing
    which pattern actually triggered it."""
    if username in REDTEAM_EXEMPT_USERS:
        return

    conn = _get_connection()
    cursor = conn.cursor()

    window_start = datetime.now() - timedelta(minutes=FLAG_WINDOW_MINUTES)
    cursor.execute("""
        SELECT COUNT(*) FROM TT_AI_AUDIT_LOG
        WHERE USERNAME = :username
        AND EVENT_TYPE = 'SECURITY_FLAG'
        AND CREATED_AT >= :window_start
    """, username=username, window_start=window_start)

    flag_count = cursor.fetchone()[0]

    if flag_count >= FLAG_THRESHOLD:
        lock_until = datetime.now() + timedelta(minutes=FLAG_LOCK_DURATION_MINUTES)
        cursor.execute("""
            UPDATE TT_AI_USERS SET LOCKED_UNTIL = :lock_until WHERE USERNAME = :username
        """, lock_until=lock_until, username=username)
        conn.commit()

        log_event(
            "SECURITY_LOCKOUT",
            username=username,
            role=role,
            details=f"Account locked until {lock_until.isoformat()} after {flag_count} SECURITY_FLAG events in {FLAG_WINDOW_MINUTES} min (repeated near-miss pattern)",
            ip_address=ip_address
        )

    cursor.close()
    conn.close()


def apply_immediate_lockout(username: str, role: str, ip_address: str = None, reason: str = None):
    """Immediate lockout for a confirmed outcome (a honeytoken hit), not a
    suspicious pattern to accumulate -- unlike check_and_apply_lockout()
    above, this doesn't count anything first, it locks on this call.
    Still checks REDTEAM_EXEMPT_USERS itself, even though callers (e.g.
    app.security.honeytoken) already check it -- defense in depth, this
    function should never lock that account no matter how it's invoked.
    """
    if username in REDTEAM_EXEMPT_USERS:
        return

    conn = _get_connection()
    cursor = conn.cursor()

    lock_until = datetime.now() + timedelta(minutes=LOCK_DURATION_MINUTES)
    cursor.execute("""
        UPDATE TT_AI_USERS SET LOCKED_UNTIL = :lock_until WHERE USERNAME = :username
    """, lock_until=lock_until, username=username)
    conn.commit()

    cursor.close()
    conn.close()

    log_event(
        "SECURITY_LOCKOUT",
        username=username,
        role=role,
        details=f"Account locked until {lock_until.isoformat()} immediately after a confirmed incident: {reason}",
        ip_address=ip_address
    )


def check_and_apply_login_lockout(username: str, ip_address: str = None):
    """Login (brute-force) lockout -- triggered by repeated LOGIN_FAILURE
    events, independent of Gateway activity. Deliberately a separate
    mechanism from check_and_apply_lockout() above: credential guessing
    and AI subversion are different threat models with different
    appropriate thresholds, and the audit trail should say clearly
    which one caused a lock, not conflate them.

    Called from /login itself, before we know the account's role (a
    bad username might not exist at all) -- so this looks up role
    directly rather than requiring the caller to supply it.
    """
    if username in REDTEAM_EXEMPT_USERS:
        return

    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT ROLE FROM TT_AI_USERS WHERE USERNAME = :username", username=username)
    row = cursor.fetchone()
    role = row[0] if row else None

    window_start = datetime.now() - timedelta(minutes=LOGIN_WINDOW_MINUTES)
    cursor.execute("""
        SELECT COUNT(*) FROM TT_AI_AUDIT_LOG
        WHERE USERNAME = :username
        AND EVENT_TYPE = 'LOGIN_FAILURE'
        AND CREATED_AT >= :window_start
    """, username=username, window_start=window_start)

    failure_count = cursor.fetchone()[0]

    if failure_count >= LOGIN_ATTEMPT_THRESHOLD:
        lock_until = datetime.now() + timedelta(minutes=LOGIN_LOCK_DURATION_MINUTES)
        cursor.execute("""
            UPDATE TT_AI_USERS SET LOCKED_UNTIL = :lock_until WHERE USERNAME = :username
        """, lock_until=lock_until, username=username)
        conn.commit()

        log_event(
            "LOGIN_LOCKOUT",
            username=username,
            role=role,
            details=f"Account locked until {lock_until.isoformat()} after {failure_count} LOGIN_FAILURE events in {LOGIN_WINDOW_MINUTES} min (brute-force protection)",
            ip_address=ip_address
        )

    cursor.close()
    conn.close()
