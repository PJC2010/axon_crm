"""
POST /api/auth/login      — username + password → JWT
GET  /api/auth/me         — current user info
POST /api/users           — create team member (owner only)
GET  /api/users           — list users (owner only)
PATCH /api/users/{id}     — update role / deactivate (owner only)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as PGConn
from psycopg2.extras import Json
from pydantic import BaseModel
from typing import Optional

from api.deps import get_db, dict_fetchone, dict_fetchall
from api.ratelimit import client_ip, login_limiter
from api.security import hash_password, verify_password, create_access_token
from api.deps import get_current_user, require_owner
from api.entitlements import (
    MODULE_KEYS, PLAN_CATALOG, get_account_modules, _plan_defaults,
)
from api.business_types import BUSINESS_TYPES, business_type_profile

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
    # Enabled feature modules for this user's account. Populated by /auth/me so the
    # frontend can gate nav/UI on first load; empty on the team-management endpoints
    # that don't need it.
    modules: dict[str, bool] = {}
    # The account's business type (drives terminology/categories). The full profile
    # (terminology, categories) is served by GET /account/features.
    business_type: str = "home_services"


class PlanUpdate(BaseModel):
    """Owner-driven toggle of optional modules within the account's plan."""
    modules: dict[str, bool]


class BusinessTypeUpdate(BaseModel):
    business_type: str


def _account_business_type(account_id: int, db: PGConn) -> str:
    with db.cursor() as cur:
        cur.execute("SELECT business_type FROM accounts WHERE id = %s", (account_id,))
        row = cur.fetchone()
    return row[0] if row and row[0] else "home_services"


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
    return UserOut(
        **row,
        modules=get_account_modules(row["account_id"], db),
        business_type=_account_business_type(row["account_id"], db),
    )


@router.get("/account/features")
def account_features(current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    """Resolved plan, enabled modules, and business-type profile for the account.

    Single payload powering both entitlement gating (frontend/hooks/
    useEntitlements.ts) and terminology (frontend/hooks/useTerminology). The
    business-type profile carries terminology + the category picklist + the
    property_based flag.
    """
    acct = current_user["account_id"]
    with db.cursor() as cur:
        cur.execute("SELECT plan_name FROM account_plans WHERE account_id = %s", (acct,))
        row = cur.fetchone()
    plan_name = row[0] if row else "pro"
    return {
        "plan_name": plan_name,
        "modules": get_account_modules(acct, db),
        **business_type_profile(_account_business_type(acct, db)),
    }


@router.patch("/account/plan")
def update_account_plan(
    body: PlanUpdate,
    current_user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    """Let an owner enable/disable optional modules within their plan's allowance.

    A module can only be turned *on* if the account's plan grants it; owners may
    turn any module off. Platform-level plan changes (upgrading the plan itself)
    are done out-of-band via scripts/set_account_plan.py — not here.
    """
    acct = current_user["account_id"]
    with db.cursor() as cur:
        cur.execute("SELECT plan_name, modules FROM account_plans WHERE account_id = %s", (acct,))
        row = cur.fetchone()
    plan_name = row[0] if row else "pro"
    granted = PLAN_CATALOG.get(plan_name, set(MODULE_KEYS))

    overrides = dict(row[1]) if (row and row[1]) else {}
    for key, enabled in body.modules.items():
        if key not in MODULE_KEYS:
            raise HTTPException(status_code=400, detail=f"Unknown module: {key}")
        if enabled and key not in granted:
            raise HTTPException(
                status_code=403,
                detail={"detail": f"Your plan does not include the '{key}' module.",
                        "module": key, "upgrade": True},
            )
        overrides[key] = bool(enabled)

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO account_plans (account_id, plan_name, modules, updated_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (account_id) DO UPDATE SET modules = %s, updated_at = NOW()",
            (acct, plan_name, Json(overrides), Json(overrides)),
        )
        db.commit()
    return {"plan_name": plan_name, "modules": get_account_modules(acct, db)}


@router.patch("/account/business-type")
def update_business_type(
    body: BusinessTypeUpdate,
    current_user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    """Owner switches the account's business type (terminology/categories preset).

    Does not touch enabled modules — those remain under the plan + /account/plan;
    switching type only changes how the product reads. Returns the new profile.
    """
    if body.business_type not in BUSINESS_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown business type: {body.business_type}")
    acct = current_user["account_id"]
    with db.cursor() as cur:
        cur.execute(
            "UPDATE accounts SET business_type = %s WHERE id = %s",
            (body.business_type, acct),
        )
        db.commit()
    return business_type_profile(body.business_type)


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
    authenticated member so assignee dropdowns (leads, tasks) can populate.
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
