"""FastAPI dependencies: DB connection and auth."""
import psycopg2
import psycopg2.extras
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError

from config import DATABASE_URL

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


def dict_fetchall(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def dict_fetchone(cur) -> dict | None:
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


# ── Auth ──────────────────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db=Depends(get_db),
) -> dict:
    """Decode JWT and return the user row. Raises 401 if missing/invalid."""
    from api.security import decode_token  # late import avoids circular deps

    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload["sub"])
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, username, email, role, is_active FROM users WHERE id = %s",
            (user_id,),
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    user = dict(zip(cols, row))
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account disabled")
    return user


def require_owner(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    return current_user
