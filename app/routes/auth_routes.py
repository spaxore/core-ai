import os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv
import oracledb

from app.security.auth import verify_password, create_access_token, hash_password
from app.security.audit import log_event
from app.security.lockout import is_locked, check_and_apply_login_lockout

load_dotenv()

router = APIRouter()

# Computed once at import time, never a real account's hash -- used only to
# burn the same bcrypt-verify time as a real login attempt on the "user not
# found" path below. Without this, that path returns immediately while a
# real user's wrong-password path calls verify_password() (deliberately
# slow), giving an attacker a timing oracle to enumerate valid usernames
# even though both paths return an identical response body.
_DUMMY_HASH_FOR_TIMING = hash_password("not-a-real-password-only-for-timing-parity")

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str

@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, http_request: Request):
    client_ip = http_request.client.host

    conn = oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN")
    )
    cursor = conn.cursor()

    cursor.execute(
        "SELECT PASSWORD_HASH, ROLE, IS_ACTIVE FROM TT_AI_USERS WHERE USERNAME = :username",
        username=request.username
    )
    row = cursor.fetchone()

    if row is None:
        cursor.close()
        conn.close()
        verify_password(request.password, _DUMMY_HASH_FOR_TIMING)
        log_event("LOGIN_FAILURE", username=request.username, details="User not found", ip_address=client_ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    stored_hash, role, is_active = row

    if is_active == 0:
        cursor.close()
        conn.close()
        log_event("LOGIN_FAILURE", username=request.username, role=role, details="Account disabled", ip_address=client_ip)
        raise HTTPException(status_code=403, detail="Account disabled")

    if is_locked(request.username):
        cursor.close()
        conn.close()
        log_event("LOGIN_FAILURE", username=request.username, role=role, details="Account temporarily locked", ip_address=client_ip)
        raise HTTPException(status_code=403, detail="Account temporarily locked due to failed login attempts")

    if not verify_password(request.password, stored_hash):
        cursor.close()
        conn.close()
        log_event("LOGIN_FAILURE", username=request.username, role=role, details="Wrong password", ip_address=client_ip)
        check_and_apply_login_lockout(request.username, ip_address=client_ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(request.username, role)

    cursor.close()
    conn.close()

    log_event("LOGIN_SUCCESS", username=request.username, role=role, details="Login successful", ip_address=client_ip)

    return TokenResponse(access_token=token, role=role)
