"""
ARC API Client
--------------
Thin HTTP client for talking to the Secure TT AI Agent backend.
ARC never touches the database, the Oracle layer, or the AI/security
modules directly -- it is just another HTTP client, exactly like
static_ui.html or llm-redteam/runner.py. This keeps ARC fully additive:
nothing here can break the platform it's testing.
"""
from __future__ import annotations

import base64
import json
import time

import requests
from dataclasses import dataclass


class ARCAuthError(Exception):
    """Raised when login fails or a token is rejected."""


@dataclass
class Session:
    base_url: str
    token: str
    username: str
    role: str
    expires_at: float | None = None  # unix timestamp, decoded from the JWT's own exp claim


class APIClient:
    def __init__(self, base_url: str, timeout: float = 90.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def login(self, username: str, password: str) -> Session:
        url = f"{self.base_url}/login"
        try:
            resp = requests.post(
                url,
                json={"username": username, "password": password},
                timeout=self.timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise ARCAuthError(f"Cannot reach {self.base_url} ({exc.__class__.__name__})") from exc
        except requests.exceptions.Timeout as exc:
            raise ARCAuthError("Login request timed out") from exc

        if resp.status_code == 401:
            raise ARCAuthError("Invalid credentials")
        if resp.status_code == 403:
            raise ARCAuthError("Account locked or forbidden")
        if resp.status_code != 200:
            raise ARCAuthError(f"Unexpected response ({resp.status_code})")

        data = resp.json()
        token = data.get("access_token")
        role = data.get("role")
        if not token:
            raise ARCAuthError("Login succeeded but no token was returned")

        return Session(
            base_url=self.base_url,
            token=token,
            username=username,
            role=role,
            expires_at=_decode_jwt_expiry(token),
        )

    def fire_attack(self, session: Session, text: str, endpoint: str = "/classify") -> dict:
        url = f"{self.base_url}{endpoint}"
        headers = {"Authorization": f"Bearer {session.token}"}
        try:
            resp = requests.post(
                url,
                json={"text": text},
                headers=headers,
                timeout=self.timeout,
            )
            return {
                "status_code": resp.status_code,
                "elapsed_ms": resp.elapsed.total_seconds() * 1000,
                "body": _safe_json(resp),
                "error": None,
            }
        except requests.exceptions.RequestException as exc:
            return {
                "status_code": None,
                "elapsed_ms": None,
                "body": None,
                "error": str(exc),
            }

    def get_audit_log(self, session: Session, limit: int = 20) -> list[dict]:
        url = f"{self.base_url}/admin/audit-log"
        headers = {"Authorization": f"Bearer {session.token}"}
        resp = requests.get(url, params={"limit": limit}, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("events", [])


def _decode_jwt_expiry(token: str) -> float | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(payload_bytes)
        exp = payload.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


def _safe_json(resp: requests.Response):
    try:
        return resp.json()
    except ValueError:
        return None
