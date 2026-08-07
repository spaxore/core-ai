import os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv
import oracledb

from app.security.auth import verify_password, create_access_token
from app.security.audit import log_event

load_dotenv()

router = APIRouter()

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
        log_event("LOGIN_FAILURE", username=request.username, details="User not found", ip_address=client_ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    stored_hash, role, is_active = row

    if is_active == 0:
        cursor.close()
        conn.close()
        log_event("LOGIN_FAILURE", username=request.username, role=role, details="Account disabled", ip_address=client_ip)
        raise HTTPException(status_code=403, detail="Account disabled")

    if not verify_password(request.password, stored_hash):
        cursor.close()
        conn.close()
        log_event("LOGIN_FAILURE", username=request.username, role=role, details="Wrong password", ip_address=client_ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(request.username, role)

    cursor.close()
    conn.close()

    log_event("LOGIN_SUCCESS", username=request.username, role=role, details="Login successful", ip_address=client_ip)

    return TokenResponse(access_token=token, role=role)
