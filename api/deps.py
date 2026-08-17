"""FastAPI dependencies: DB connection and auth."""
import psycopg2
import psycopg2.extras
from fastapi import Depends, HTTPException, Query
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
    token: str | None = Query(None),
    db=Depends(get_db),
) -> dict:
    """Decode JWT and return the user row. Raises 401 if missing/invalid.

    The token normally arrives in the ``Authorization: Bearer`` header. As a
    fallback it may be passed as a ``?token=`` query param, which the frontend
    uses for ``<a download>`` CSV exports where headers can't be set.
    """
    from api.security import decode_token  # late import avoids circular deps

    raw_token = credentials.credentials if credentials is not None else token
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(raw_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload["sub"])
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, username, email, role, is_active, account_id, is_platform_admin "
            "FROM users WHERE id = %s",
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
    if current_user["role"] not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner access required")
    return current_user


def require_platform_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Gate for the cross-tenant /api/admin surface (api/routes/admin.py).

    Orthogonal to ``require_owner``: ``role`` governs power inside one org,
    ``users.is_platform_admin`` (migration 0073) governs the whole platform.
    The flag is read from the DB on every request, never from the JWT, so
    revocation takes effect immediately.
    """
    if not current_user.get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="Platform admin access required")
    return current_user
