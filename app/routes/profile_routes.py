import os
import smtplib
from typing import Optional

import oracledb
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv

from app.security.dependencies import get_current_user
from app.security.auth import verify_password, hash_password
from app.security.audit import log_event, get_user_activity
from app.security.mtls import channel_label
from app.services.email_account import (
    detect_smtp_settings,
    test_smtp_login,
    link_email_account,
    get_linked_email,
)

load_dotenv()

router = APIRouter(prefix="/profile", tags=["profile"])


class LinkEmailRequest(BaseModel):
    email: str
    app_password: str
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/email-link")
def get_email_link(user: dict = Depends(get_current_user)):
    linked = get_linked_email(user["username"])
    if linked is None:
        return {"linked": False}
    return {"linked": True, **linked}


@router.post("/email-link")
def post_email_link(payload: LinkEmailRequest, http_request: Request, user: dict = Depends(get_current_user)):
    smtp_host = payload.smtp_host
    smtp_port = payload.smtp_port

    if not smtp_host or not smtp_port:
        detected = detect_smtp_settings(payload.email)
        if detected is None:
            raise HTTPException(
                status_code=400,
                detail="Fournisseur non reconnu automatiquement -- indiquez le serveur et le port SMTP manuellement.",
            )
        smtp_host, smtp_port = detected

    try:
        test_smtp_login(payload.email, payload.app_password, smtp_host, smtp_port)
    except (smtplib.SMTPException, OSError) as e:
        raise HTTPException(status_code=400, detail=f"Connexion SMTP échouée : {e}")

    link_email_account(user["username"], payload.email, payload.app_password, smtp_host, smtp_port)

    log_event(
        "EMAIL_ACCOUNT_LINKED",
        username=user["username"],
        role=user["role"],
        details=f"email={payload.email}, smtp_host={smtp_host}, smtp_port={smtp_port}, channel={channel_label(http_request)}",
        ip_address=http_request.client.host,
    )

    return {"linked": True, "email": payload.email, "smtp_host": smtp_host, "smtp_port": smtp_port}


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, http_request: Request, user: dict = Depends(get_current_user)):
    conn = oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN"),
    )
    cursor = conn.cursor()
    cursor.execute(
        "SELECT PASSWORD_HASH FROM TT_AI_USERS WHERE USERNAME = :username",
        username=user["username"],
    )
    row = cursor.fetchone()

    if row is None or not verify_password(payload.current_password, row[0]):
        cursor.close()
        conn.close()
        log_event(
            "PASSWORD_CHANGE_FAILURE",
            username=user["username"],
            role=user["role"],
            details="Wrong current password",
            ip_address=http_request.client.host,
        )
        raise HTTPException(status_code=401, detail="Mot de passe actuel incorrect")

    new_hash = hash_password(payload.new_password)
    cursor.execute(
        "UPDATE TT_AI_USERS SET PASSWORD_HASH = :new_hash WHERE USERNAME = :username",
        new_hash=new_hash, username=user["username"],
    )
    conn.commit()
    cursor.close()
    conn.close()

    log_event(
        "PASSWORD_CHANGED",
        username=user["username"],
        role=user["role"],
        details="Password updated by user",
        ip_address=http_request.client.host,
    )

    return {"status": "updated"}


@router.get("/activity")
def profile_activity(user: dict = Depends(get_current_user)):
    return {"activity": get_user_activity(user["username"], limit=20)}
