from datetime import datetime
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from app.security.auth import decode_access_token
from app.security.lockout import is_locked, is_account_active, get_password_changed_at

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    username = payload.get("sub")

    if is_locked(username):
        raise HTTPException(status_code=403, detail="Account temporarily locked due to security violations")

    # Checked on every request, not just at /login -- previously IS_ACTIVE
    # was only checked there, so deactivating a compromised or offboarded
    # account blocked future logins but left an already-issued JWT working
    # until it naturally expired.
    if not is_account_active(username):
        raise HTTPException(status_code=403, detail="Account disabled")

    # Reject a token issued before the account's most recent password
    # change -- without this, changing/resetting a password didn't
    # actually invalidate a token an attacker already had. iat is a plain
    # epoch-seconds int after decode (see create_access_token()); a token
    # issued before this check existed has no iat at all, so it's skipped
    # rather than rejected -- it'll just expire naturally like normal.
    password_changed_at = get_password_changed_at(username)
    if password_changed_at is not None:
        issued_at = payload.get("iat")
        if issued_at is not None and datetime.utcfromtimestamp(issued_at) < password_changed_at:
            raise HTTPException(status_code=401, detail="Session expired -- password was changed, please log in again")

    return {"username": username, "role": payload.get("role")}

def require_role(*allowed_roles):
    def role_checker(user: dict = Depends(get_current_user)):
        if user["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return role_checker
