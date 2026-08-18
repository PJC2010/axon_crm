"""JWT creation/verification and password hashing."""
import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
if not SECRET_KEY:
    # A publicly known signing key lets anyone forge owner tokens. Only allow
    # an insecure fallback when explicitly opted into for local development.
    if os.getenv("ALLOW_INSECURE_DEV_JWT", "").lower() != "true":
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Set it to a long random string, "
            "or set ALLOW_INSECURE_DEV_JWT=true for local development only."
        )
    SECRET_KEY = "insecure-dev-only-secret"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        # iat lets a password reset invalidate every token issued before it
        # (users.password_changed_at, checked in api/deps.py).
        "iat": now,
        "exp": now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Return payload dict or raise JWTError."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
