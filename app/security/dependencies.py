from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from app.security.auth import decode_access_token
from app.security.lockout import is_locked

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    username = payload.get("sub")

    if is_locked(username):
        raise HTTPException(status_code=403, detail="Account temporarily locked due to security violations")

    return {"username": username, "role": payload.get("role")}

def require_role(*allowed_roles):
    def role_checker(user: dict = Depends(get_current_user)):
        if user["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return role_checker
