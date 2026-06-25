"""
POST /api/auth/login      — username + password → JWT
GET  /api/auth/me         — current user info
POST /api/users           — create team member (owner only)
GET  /api/users           — list users (owner only)
PATCH /api/users/{id}     — update role / deactivate (owner only)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel
from typing import Optional

from api.deps import get_db, dict_fetchone, dict_fetchall
from api.ratelimit import client_ip, login_limiter
from api.security import hash_password, verify_password, create_access_token
from api.deps import get_current_user, require_owner

router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class IdTokenRequest(BaseModel):
    """An OIDC ID token from Google / Apple, posted by the frontend SDK.

    Used by the social-login routes in api/routes/oauth.py.
    """
    id_token: str


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "sales_rep"


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    account_id: int
    onboarding_complete: bool = False


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: PGConn = Depends(get_db)):
    login_limiter.check(client_ip(request))
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, username, hashed_pw, role, is_active FROM users WHERE username = %s",
            (body.username,),
        )
        row = dict_fetchone(cur)

    if not row or not verify_password(body.password, row["hashed_pw"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Account disabled")

    token = create_access_token(row["id"], row["username"], row["role"])
    return TokenResponse(access_token=token)


@router.get("/auth/me", response_model=UserOut)
def me(current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, username, email, role, is_active, account_id, onboarding_complete FROM users WHERE id = %s",
            (current_user["id"],),
        )
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(**row)


@router.patch("/auth/onboarding-complete")
def complete_onboarding(current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "UPDATE users SET onboarding_complete = TRUE WHERE id = %s RETURNING id",
            (current_user["id"],),
        )
        db.commit()
    return {"ok": True}


@router.get("/auth/checklist-status")
def checklist_status(current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    acct = current_user["account_id"]
    # Single round trip; EXISTS stops at the first row instead of counting.
    with db.cursor() as cur:
        cur.execute(
            "SELECT "
            "  EXISTS(SELECT 1 FROM properties WHERE account_id = %s) AS has_leads, "
            "  EXISTS(SELECT 1 FROM contact_history ch "
            "         JOIN properties p ON p.id = ch.property_id WHERE p.account_id = %s) AS has_contact, "
            "  EXISTS(SELECT 1 FROM invoices WHERE account_id = %s) AS has_invoice, "
            "  EXISTS(SELECT 1 FROM workflow_rules WHERE account_id = %s) AS has_workflow, "
            "  EXISTS(SELECT 1 FROM expenses WHERE account_id = %s) AS has_expense",
            (acct, acct, acct, acct, acct),
        )
        flags = dict_fetchone(cur)
    return flags


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    current_user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    if body.role not in ("owner", "sales_rep"):
        raise HTTPException(status_code=400, detail="role must be owner or sales_rep")
    hashed = hash_password(body.password)
    # New team members join the creator's org so they share the same leads.
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, email, hashed_pw, role, account_id) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id, username, email, role, is_active, account_id",
                (body.username, body.email, hashed, body.role, current_user["account_id"]),
            )
            row = dict_fetchone(cur)
            db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username or email already exists")
    return UserOut(**row)


@router.get("/team")
def list_team(current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    """Lightweight roster (id + username) of active members in the caller's org.

    Unlike GET /users (owner-only, exposes email/role), this is readable by any
    authenticated member so assignee dropdowns (leads, appointments) can populate.
    """
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, username FROM users WHERE account_id = %s AND is_active = TRUE ORDER BY username",
            (current_user["account_id"],),
        )
        return [{"id": r[0], "username": r[1]} for r in cur.fetchall()]


@router.get("/users", response_model=list[UserOut])
def list_users(current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, username, email, role, is_active, account_id FROM users "
            "WHERE account_id = %s ORDER BY id",
            (current_user["account_id"],),
        )
        return [UserOut(**r) for r in dict_fetchall(cur)]


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    current_user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    sets, params = [], []
    if body.role is not None:
        if body.role not in ("owner", "sales_rep"):
            raise HTTPException(status_code=400, detail="Invalid role")
        sets.append("role = %s"); params.append(body.role)
    if body.is_active is not None:
        sets.append("is_active = %s"); params.append(body.is_active)
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    params.extend([user_id, current_user["account_id"]])
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE users SET {', '.join(sets)} WHERE id = %s AND account_id = %s "
            "RETURNING id, username, email, role, is_active, account_id",
            params,
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(**row)
