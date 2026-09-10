import os
from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

MIN_PASSWORD_LENGTH = 8


def validate_password_strength(password: str) -> None:
    """Raises ValueError with a user-facing message if the password is too
    weak. Server-side, deliberately -- the frontend's generated-password
    helper (samplePassword()) is a UX nicety, not a security control, and
    every caller of create_user()/change_password() must go through this
    regardless of how the request was actually made (UI vs a direct API
    call)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Le mot de passe doit contenir au moins {MIN_PASSWORD_LENGTH} caractères.")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(username: str, role: str) -> str:
    issued_at = datetime.utcnow()
    expire = issued_at + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # iat lets get_current_user() reject a token issued before the
    # account's most recent password change (see
    # app.security.lockout.get_password_changed_at) -- without it, a
    # password change/reset didn't actually invalidate a token an
    # attacker already had, only a future login attempt.
    payload = {"sub": username, "role": role, "iat": issued_at, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


if __name__ == "__main__":
    h = hash_password("test123")
    print("Hash:", h)
    print("Verify correct:", verify_password("test123", h))
    print("Verify wrong:", verify_password("wrong", h))

    token = create_access_token("ikbal", "SECURITY_ANALYST")
    print("Token:", token)
    print("Decoded:", decode_access_token(token))
