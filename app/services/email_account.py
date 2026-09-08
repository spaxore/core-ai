"""
Per-agent linked email account for sending investigation data directly from
the agent's own address, rather than a shared platform mailbox. The app
password is encrypted at rest (app/security/email_crypto.py) and only ever
decrypted in memory, at send time -- never returned to the frontend.
"""
import os
import smtplib
from email.message import EmailMessage

import oracledb
from dotenv import load_dotenv

from app.security.email_crypto import encrypt_secret, decrypt_secret

load_dotenv()

# Common providers' SMTP settings, keyed by the email's domain -- covers the
# realistic cases without asking every agent to know their own SMTP host.
# Anything else falls back to manual host/port entry in the frontend.
_KNOWN_PROVIDERS = {
    "gmail.com": ("smtp.gmail.com", 587),
    "outlook.com": ("smtp.office365.com", 587),
    "hotmail.com": ("smtp.office365.com", 587),
    "yahoo.com": ("smtp.mail.yahoo.com", 587),
}


def detect_smtp_settings(email: str):
    domain = email.rsplit("@", 1)[-1].lower()
    return _KNOWN_PROVIDERS.get(domain)


def _get_connection():
    return oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN"),
    )


def test_smtp_login(email: str, app_password: str, smtp_host: str, smtp_port: int):
    """
    Raises smtplib.SMTPException (or OSError on a bad host/port) if the
    credentials don't actually work -- callers should surface that as a
    rejected link attempt rather than silently storing bad creds.
    """
    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
        server.starttls()
        server.login(email, app_password)


def link_email_account(username: str, email: str, app_password: str, smtp_host: str, smtp_port: int):
    encrypted = encrypt_secret(app_password)
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        MERGE INTO TT_AI_USER_EMAIL_LINKS t
        USING (SELECT :username AS username FROM dual) s
        ON (t.username = s.username)
        WHEN MATCHED THEN UPDATE SET
            EMAIL_ADDRESS = :email, ENCRYPTED_APP_PASSWORD = :encrypted,
            SMTP_HOST = :smtp_host, SMTP_PORT = :smtp_port, LINKED_AT = SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT (USERNAME, EMAIL_ADDRESS, ENCRYPTED_APP_PASSWORD, SMTP_HOST, SMTP_PORT)
            VALUES (:username, :email, :encrypted, :smtp_host, :smtp_port)
    """, username=username, email=email, encrypted=encrypted, smtp_host=smtp_host, smtp_port=smtp_port)
    conn.commit()
    cursor.close()
    conn.close()


def get_linked_email(username: str):
    """
    Returns {email, smtp_host, smtp_port, linked_at} or None. Never
    includes the password, encrypted or otherwise -- the frontend only
    ever needs to know THAT an account is linked, not any of its secret.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT EMAIL_ADDRESS, SMTP_HOST, SMTP_PORT, LINKED_AT
        FROM TT_AI_USER_EMAIL_LINKS WHERE USERNAME = :username
    """, username=username)
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None:
        return None

    email, smtp_host, smtp_port, linked_at = row
    return {
        "email": email,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "linked_at": linked_at.isoformat() if linked_at else None,
    }


def get_decrypted_credentials(username: str):
    """
    For actual sending (the ticket-email-send feature, built separately) --
    not used by the profile-linking endpoints themselves.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT EMAIL_ADDRESS, ENCRYPTED_APP_PASSWORD, SMTP_HOST, SMTP_PORT
        FROM TT_AI_USER_EMAIL_LINKS WHERE USERNAME = :username
    """, username=username)
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None:
        return None

    email, encrypted, smtp_host, smtp_port = row
    return {
        "email": email,
        "app_password": decrypt_secret(encrypted),
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
    }


def send_email(username: str, to: str, subject: str, body: str):
    """
    Sends from the agent's own linked account (credentials decrypted only
    in memory, for this one call). Raises ValueError if nothing is linked,
    or smtplib.SMTPException/OSError on a real send failure -- callers
    should surface those as 400s, matching the same treatment as the
    profile-linking test_smtp_login() failures.
    """
    creds = get_decrypted_credentials(username)
    if creds is None:
        raise ValueError("Aucun compte email lié -- liez un compte dans Profil avant d'envoyer.")

    msg = EmailMessage()
    msg["From"] = creds["email"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(creds["smtp_host"], creds["smtp_port"], timeout=15) as server:
        server.starttls()
        server.login(creds["email"], creds["app_password"])
        server.send_message(msg)

    return creds["email"]
