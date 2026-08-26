"""
Platform super-admin surface — deliberately CROSS-TENANT.

Every query in this module intentionally reads across accounts. That is an
explicit, reviewed exemption from the "always scope by account_id" rule in
CLAUDE.md: this router serves the platform operator, not a tenant, and it is
guarded router-wide by require_platform_admin (api/deps.py, users.is_platform_admin,
migration 0073). Do NOT "fix" the missing account_id scoping here.

Every mutation records an admin_audit_log row (api/admin_audit.py) in the same
transaction as the change. No endpoint here may declare a query param named
``token`` — it would collide with get_current_user's ?token= CSV-export fallback.

GET    /admin/summary                     — platform KPI tiles
GET    /admin/accounts                    — org list w/ plan, billing, usage aggregates
POST   /admin/accounts                    — provision a fresh org + its owner login
GET    /admin/accounts/{id}               — org drill-down (members, counts, recent activity)
GET    /admin/accounts/{id}/activity      — per-user activity inside one org
POST   /admin/accounts/{id}/plan          — assign plan + module overrides
POST   /admin/accounts/{id}/trial         — extend or expire a trial
DELETE /admin/accounts/{id}               — purge the org and every row it owns
GET    /admin/users                       — cross-tenant user list
POST   /admin/users                       — create user (existing org or fresh org)
PATCH  /admin/users/{id}                  — role / active / verified / platform-admin
DELETE /admin/users/{id}                  — delete the login, keep the org's data
POST   /admin/users/{id}/reset-password   — mint a reset link (optionally email it)
POST   /admin/users/{id}/set-password     — directly set a temporary password
GET   /admin/security                     — security panel (failed logins, config checks, …)
GET   /admin/auth-events                  — login/auth event feed
GET   /admin/audit-log                    — admin-action audit feed
GET   /admin/prospects                    — landing-page prospect signups
"""
import logging
import os
from datetime import datetime, timezone

import psycopg2.errors
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from psycopg2.extras import Json
from pydantic import BaseModel

from config import (
    ACCOUNT_DELETE_BATCH, ACCOUNT_DELETE_TIMEOUT_MS, ADMIN_NOTIFICATION_EMAIL,
    APP_BASE_URL, RESEND_API_KEY, RESEND_FROM_EMAIL, SELF_SERVE_SIGNUP,
    STRIPE_BILLING_WEBHOOK_SECRET, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
)
from api.accounts import provision_owner
from api.admin_audit import record_admin_action
from api.admin_logic import (
    ADMIN_ROLES, build_leftover_probe_sql, build_reset_url, clamp_page,
    evaluate_config_checks, validate_account_delete, validate_admin_user_update,
    validate_user_delete,
)
from api.billing import apply_plan, billing_configured
from api.business_types import BUSINESS_TYPES, DEFAULT_BUSINESS_TYPE
from api.deps import (
    dict_fetchall, dict_fetchone, get_db, require_platform_admin,
)
from api.entitlements import get_account_modules, resolve_plan_modules
from api.routes.signup import _issue_token, _send_reset_email
from api.security import hash_password
from api.signup_logic import (
    EMAIL_RE, MIN_PASSWORD_LEN, RESET_PASSWORD_TTL, USERNAME_RE,
    company_problem, derive_username, normalize_email, password_problem,
    username_candidates, validate_signup,
)

log = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────

class PlanAssign(BaseModel):
    plan: str
    enable: list[str] = []
    disable: list[str] = []


class TrialUpdate(BaseModel):
    action: str                              # 'extend' | 'expire'
    trial_ends_at: datetime | None = None    # required for 'extend'


class AdminNewAccount(BaseModel):
    name: str
    business_type: str = DEFAULT_BUSINESS_TYPE


class AdminAccountOwner(BaseModel):
    email: str
    password: str
    username: str | None = None              # derived from email when omitted


class AdminAccountCreate(BaseModel):
    name: str
    business_type: str = DEFAULT_BUSINESS_TYPE
    owner: AdminAccountOwner


class AdminUserCreate(BaseModel):
    email: str
    password: str
    username: str | None = None              # derived from email when omitted
    role: str = "owner"
    account_id: int | None = None            # exactly one of account_id /
    new_account: AdminNewAccount | None = None  # new_account


class AdminUserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    email_verified: bool | None = None
    is_platform_admin: bool | None = None


class ResetLinkRequest(BaseModel):
    send_email: bool = False


class SetPasswordRequest(BaseModel):
    password: str


# ── Helpers ───────────────────────────────────────────────────────────────────

_USER_COLS = ("id, username, email, role, is_active, email_verified, "
              "is_platform_admin, account_id, created_at, last_login_at")


def _get_user(db: PGConn, user_id: int) -> dict:
    with db.cursor() as cur:
        cur.execute(f"SELECT {_USER_COLS} FROM users WHERE id = %s", (user_id,))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


def _require_account(db: PGConn, account_id: int) -> dict:
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, name, business_type, created_at, review_link "
            "FROM accounts WHERE id = %s", (account_id,),
        )
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    return row


def _provision_org_with_owner(db: PGConn, admin: dict, *, name: str,
                              business_type: str, email: str, password: str,
                              username: str | None) -> dict:
    """Fresh org + its owner in one transaction, through the same
    provision_owner as self-serve signup (stages, fields, plan, trial row,
    workflows), plus the audit rows. Shared by POST /admin/accounts and
    POST /admin/users' new_account mode so the two ways an admin can create an
    org cannot drift. Caller owns the transaction (commits).
    Returns provision_owner's {"user_id", "account_id", "username"}.
    """
    try:
        created = provision_owner(
            db,
            company=name,
            email=email,
            username_base=username or derive_username(email),
            hashed_pw=hash_password(password),
            business_type=business_type,
            email_verified=True,
        )
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409, detail="A user with that email already exists.")
    except RuntimeError as exc:
        # provision_owner exhausted its numbered username candidates — the only
        # RuntimeError it raises. Logged in case that ever stops being true.
        db.rollback()
        log.warning("org provisioning failed for %r: %s", name, exc)
        raise HTTPException(status_code=409, detail="Could not find a free username.")
    record_admin_action(
        db, admin, "account.create", "account", created["account_id"],
        {"name": name, "business_type": business_type},
    )
    record_admin_action(
        db, admin, "user.create", "user", created["user_id"],
        {"email": email, "role": "owner", "account_id": created["account_id"],
         "new_account": True},
    )
    return created


# Per-table row counts for one org. Heavy enough that it is deliberately absent
# from the list endpoint; shared by the drill-down and by DELETE, which reports
# what it destroyed and so must count before the cascade, not after.
_ACCOUNT_COUNTS_SQL = """
    SELECT
      (SELECT COUNT(*) FROM properties
        WHERE account_id = %(id)s AND archived_at IS NULL)              AS leads,
      (SELECT COUNT(*) FROM tasks WHERE account_id = %(id)s)            AS tasks,
      (SELECT COUNT(*) FROM invoices WHERE account_id = %(id)s)         AS invoices,
      (SELECT COUNT(*) FROM quotes WHERE account_id = %(id)s)           AS quotes,
      (SELECT COUNT(*) FROM expenses WHERE account_id = %(id)s)         AS expenses,
      (SELECT COUNT(*) FROM calls WHERE account_id = %(id)s)            AS calls,
      (SELECT COUNT(*) FROM contact_history ch
        JOIN properties p ON p.id = ch.property_id
        WHERE p.account_id = %(id)s)                                    AS messages,
      (SELECT COUNT(*) FROM pipeline_runs WHERE account_id = %(id)s)    AS pipeline_runs,
      (SELECT COUNT(*) FROM workflow_rules WHERE account_id = %(id)s)   AS workflow_rules,
      (SELECT COUNT(*) FROM scoring_reveals
        WHERE account_id = %(id)s
          AND month = date_trunc('month', CURRENT_DATE)::date)          AS scoring_reveals_month
"""


def _account_counts(db: PGConn, account_id: int) -> dict:
    with db.cursor() as cur:
        cur.execute(_ACCOUNT_COUNTS_SQL, {"id": account_id})
        return dict_fetchone(cur)


def _assert_account_purged(db: PGConn, account_id: int) -> None:
    """Fail the delete if any account-scoped row outlived the cascade.

    Migration 0074 hands the teardown to Postgres, which is right but silent:
    ON DELETE CASCADE reaches every table that declares the FK, and says nothing
    about a table that carries ``account_id`` with no FK at all. That is not
    hypothetical — ``auth_events`` is exactly such a table (0073, deliberately),
    which is why the endpoint deletes it by hand first. This runs inside the
    same transaction and re-derives the table list from the catalog, so the next
    table someone adds that way trips a rollback instead of quietly leaving a
    deleted customer's rows in the database.
    """
    with db.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'account_id' "
            "  AND table_name IN (SELECT table_name FROM information_schema.tables "
            "                     WHERE table_schema = 'public' AND table_type = 'BASE TABLE') "
            "ORDER BY table_name"
        )
        tables = [r[0] for r in cur.fetchall()]
        cur.execute(build_leftover_probe_sql(tables), {"id": account_id})
        leftovers = [r[0] for r in cur.fetchall()]
    if leftovers:
        db.rollback()
        log.error("account %s purge left rows in: %s", account_id, ", ".join(leftovers))
        raise HTTPException(
            status_code=500,
            detail="Delete aborted — rows survived in: " + ", ".join(leftovers),
        )


def _delete_account_leads(cur, account_id: int, batch: int) -> int:
    """Delete the org's ``properties`` rows in bounded batches. Returns the count.

    ``DELETE FROM accounts`` cascades to everything (migration 0074) and that is
    still the authority here — this only takes the one table out of its way
    first, because of how Postgres actually performs a cascade.

    A referential-integrity action is an AFTER-ROW trigger, not a set operation:
    for every deleted parent row, and for every FK pointing at it, the server
    runs one more query against the child. ``properties`` has nineteen children,
    so purging an org runs nineteen queries per lead inside a single
    ``DELETE FROM accounts`` statement — and ``statement_timeout`` caps
    statements, which is what cancelled the delete at 30s (api/deps.py,
    DB_STATEMENT_TIMEOUT_MS) and put ``QueryCanceled`` in front of the operator.

    Batching moves the org's size out of any one statement: each of these costs
    ``batch`` leads' worth of trigger work regardless of whether the org holds
    ten thousand or a million, so one timeout value is correct for every org
    instead of needing to exceed the largest one. The batches share the caller's
    transaction, so the purge is still all-or-nothing and
    ``_assert_account_purged`` still gets to veto the commit.

    Bounding the statement is not a substitute for indexing the children: an
    unindexed child column makes each of those nineteen queries a sequential
    scan, which no batch size rescues. Migration 0080 indexes them and asserts
    that the next one added is indexed too.
    """
    batch = max(1, batch)
    deleted = 0
    while True:
        cur.execute(
            "DELETE FROM properties WHERE id IN "
            "(SELECT id FROM properties WHERE account_id = %s LIMIT %s)",
            (account_id, batch),
        )
        if not cur.rowcount:
            return deleted
        deleted += cur.rowcount
        log.info("account %s purge: %s leads deleted so far", account_id, deleted)


def _finish_page(cur, rows: list[dict], page: int, page_size: int,
                 count_sql: str, count_params: tuple) -> dict:
    """Strip the COUNT(*) OVER () column and build the standard page envelope.

    The window-function total only exists when the page has rows — an OFFSET
    past the last match returns nothing at all, which used to read as total=0
    even though matches exist. Past-the-end pages fall back to a real COUNT so
    the client can tell "no matches" from "you paged too far".
    """
    if rows:
        total = rows[0].pop("_total")
        for r in rows[1:]:
            r.pop("_total", None)
    elif page > 1:
        cur.execute(count_sql, count_params)
        total = cur.fetchone()[0]
    else:
        total = 0
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


# ── Overview ──────────────────────────────────────────────────────────────────

@router.get("/admin/summary")
def admin_summary(db: PGConn = Depends(get_db)):
    """Platform KPIs in a single round trip of index-cheap scalar subselects."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM accounts)                                          AS accounts,
              (SELECT COUNT(*) FROM accounts
                WHERE created_at > NOW() - INTERVAL '30 days')                         AS accounts_new_30d,
              (SELECT COUNT(*) FROM users)                                             AS users_total,
              (SELECT COUNT(*) FROM users WHERE is_active)                             AS users_active,
              (SELECT COUNT(*) FROM users WHERE email_verified)                        AS users_verified,
              (SELECT COUNT(*) FROM users
                WHERE last_login_at > NOW() - INTERVAL '7 days')                       AS active_users_7d,
              (SELECT COUNT(*) FROM account_billing WHERE status = 'trialing')         AS trials_active,
              (SELECT COUNT(*) FROM account_billing WHERE status = 'trial_expired')    AS trials_expired,
              (SELECT COUNT(*) FROM account_billing
                WHERE stripe_subscription_id IS NOT NULL
                  AND status IN ('active', 'past_due'))                                AS paying,
              (SELECT COUNT(*) FROM auth_events
                WHERE success AND created_at > NOW() - INTERVAL '24 hours')            AS logins_24h,
              (SELECT COUNT(*) FROM auth_events
                WHERE NOT success AND created_at > NOW() - INTERVAL '24 hours')        AS failed_logins_24h,
              (SELECT COUNT(*) FROM pipeline_runs
                WHERE created_at > NOW() - INTERVAL '24 hours')                        AS pipeline_runs_24h,
              (SELECT COUNT(*) FROM pipeline_runs
                WHERE status IN ('failed', 'cancelled')
                  AND created_at > NOW() - INTERVAL '7 days')                          AS pipeline_failures_7d,
              (SELECT COUNT(*) FROM stripe_webhook_events
                WHERE status = 'error'
                  AND received_at > NOW() - INTERVAL '7 days')                         AS webhook_errors_7d,
              (SELECT COUNT(*) FROM prospect_signups
                WHERE created_at > NOW() - INTERVAL '7 days')                          AS prospect_signups_7d
            """
        )
        return dict_fetchone(cur)


# ── Accounts ──────────────────────────────────────────────────────────────────

# Every sort carries the unique id as a tiebreaker — created_at/name ties are
# real (bulk-seeded orgs share NOW()), and without it OFFSET pages can repeat
# or drop rows across requests.
_ACCOUNT_SORTS = {
    "created_at": "a.created_at DESC, a.id DESC",
    "name": "a.name ASC, a.id ASC",
    "id": "a.id ASC",
}


@router.get("/admin/accounts")
def admin_accounts(
    q: str | None = Query(None),
    plan: str | None = Query(None),
    billing_status: str | None = Query(None),
    sort: str = Query("created_at"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: PGConn = Depends(get_db),
):
    """Org list: identity + plan + billing in one paged query, then per-account
    aggregates fetched only for the page's ids (never the whole table)."""
    page, page_size = clamp_page(page, page_size)
    where, params = [], []
    if q:
        where.append("(a.name ILIKE %s OR a.id::text = %s)")
        params.extend([f"%{q}%", q.strip()])
    if plan:
        where.append("p.plan_name = %s")
        params.append(plan)
    if billing_status:
        where.append("b.status = %s")
        params.append(billing_status)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order_sql = _ACCOUNT_SORTS.get(sort, _ACCOUNT_SORTS["created_at"])

    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT a.id, a.name, a.business_type, a.created_at,
                   p.plan_name, b.status AS billing_status, b.trial_ends_at,
                   b.current_period_end,
                   COUNT(*) OVER () AS _total
            FROM accounts a
            LEFT JOIN account_plans p ON p.account_id = a.id
            LEFT JOIN account_billing b ON b.account_id = a.id
            {where_sql}
            ORDER BY {order_sql}
            LIMIT %s OFFSET %s
            """,
            (*params, page_size, (page - 1) * page_size),
        )
        rows = dict_fetchall(cur)
        envelope = _finish_page(
            cur, rows, page, page_size,
            "SELECT COUNT(*) FROM accounts a "
            "LEFT JOIN account_plans p ON p.account_id = a.id "
            f"LEFT JOIN account_billing b ON b.account_id = a.id {where_sql}",
            tuple(params),
        )

        ids = [r["id"] for r in rows]
        users_by, leads_by, activity_by = {}, {}, {}
        if ids:
            cur.execute(
                "SELECT account_id, COUNT(*) AS users_total, "
                "COUNT(*) FILTER (WHERE is_active) AS users_active "
                "FROM users WHERE account_id = ANY(%s) GROUP BY account_id",
                (ids,),
            )
            users_by = {r["account_id"]: r for r in dict_fetchall(cur)}
            cur.execute(
                "SELECT account_id, COUNT(*) AS lead_count FROM properties "
                "WHERE account_id = ANY(%s) AND archived_at IS NULL GROUP BY account_id",
                (ids,),
            )
            leads_by = {r["account_id"]: r["lead_count"] for r in dict_fetchall(cur)}
            cur.execute(
                "SELECT account_id, MAX(occurred_at) AS last_activity_at "
                "FROM lead_events WHERE account_id = ANY(%s) GROUP BY account_id",
                (ids,),
            )
            activity_by = {r["account_id"]: r["last_activity_at"] for r in dict_fetchall(cur)}

    for r in rows:
        u = users_by.get(r["id"], {})
        r["users_total"] = u.get("users_total", 0)
        r["users_active"] = u.get("users_active", 0)
        r["lead_count"] = leads_by.get(r["id"], 0)
        r["last_activity_at"] = activity_by.get(r["id"])
    return envelope


@router.post("/admin/accounts", status_code=201)
def admin_create_account(
    body: AdminAccountCreate,
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    """Provision a fresh organization with its owner login.

    The org-first twin of POST /admin/users' new_account mode — both run
    _provision_org_with_owner, and the request is validated by validate_signup
    itself, so an admin-created org cannot drift from a self-serve one (same
    name/email/password rules, same stages, fields, plan, trial and workflows).
    The owner starts email-verified: an admin-created login shouldn't begin
    life gated behind a verification email.
    """
    email = normalize_email(body.owner.email)
    problems = validate_signup(
        company=body.name, email=email, password=body.owner.password,
        username=body.owner.username,
    )
    if body.business_type not in BUSINESS_TYPES:
        problems.append(f"Unknown business type '{body.business_type}'.")
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))

    created = _provision_org_with_owner(
        db, admin, name=body.name.strip(), business_type=body.business_type,
        email=email, password=body.owner.password, username=body.owner.username,
    )
    db.commit()

    account = _require_account(db, created["account_id"])
    with db.cursor() as cur:
        cur.execute(
            "SELECT p.plan_name, b.status AS billing_status, b.trial_ends_at "
            "FROM accounts a "
            "LEFT JOIN account_plans p ON p.account_id = a.id "
            "LEFT JOIN account_billing b ON b.account_id = a.id "
            "WHERE a.id = %s",
            (created["account_id"],),
        )
        plan_billing = dict_fetchone(cur) or {}
    return {**account, **plan_billing, "owner": _get_user(db, created["user_id"])}


@router.get("/admin/accounts/{account_id}")
def admin_account_detail(account_id: int, db: PGConn = Depends(get_db)):
    account = _require_account(db, account_id)
    with db.cursor() as cur:
        cur.execute(
            "SELECT plan_name, modules, scoring_monthly_limit, updated_at "
            "FROM account_plans WHERE account_id = %s", (account_id,),
        )
        plan_row = dict_fetchone(cur)
        cur.execute(
            "SELECT plan_name, status, trial_ends_at, current_period_end, "
            "cancel_at_period_end, stripe_customer_id IS NOT NULL AS has_stripe_customer, "
            "stripe_subscription_id IS NOT NULL AS has_subscription, updated_at "
            "FROM account_billing WHERE account_id = %s", (account_id,),
        )
        billing = dict_fetchone(cur)
        cur.execute(
            f"SELECT {_USER_COLS} FROM users WHERE account_id = %s ORDER BY id",
            (account_id,),
        )
        members = dict_fetchall(cur)
        # Heavy per-table counts live here (one org), never on the list endpoint.
        cur.execute(_ACCOUNT_COUNTS_SQL, {"id": account_id})
        counts = dict_fetchone(cur)
        cur.execute(
            "SELECT id, zip, status, triggered_by, created_at, started_at, finished_at "
            "FROM pipeline_runs WHERE account_id = %s ORDER BY created_at DESC LIMIT 5",
            (account_id,),
        )
        recent_runs = dict_fetchall(cur)
        cur.execute(
            "SELECT le.id, le.event_type, le.channel, le.occurred_at, u.username AS actor "
            "FROM lead_events le LEFT JOIN users u ON u.id = le.actor_user_id "
            "WHERE le.account_id = %s ORDER BY le.occurred_at DESC LIMIT 20",
            (account_id,),
        )
        recent_events = dict_fetchall(cur)

    return {
        **account,
        "plan": plan_row,
        "modules": get_account_modules(account_id, db),
        "billing": billing,
        "members": members,
        "counts": counts,
        "recent_runs": recent_runs,
        "recent_events": recent_events,
    }


@router.get("/admin/accounts/{account_id}/activity")
def admin_account_activity(
    account_id: int,
    days: int = Query(30, ge=1, le=365),
    db: PGConn = Depends(get_db),
):
    _require_account(db, account_id)
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT u.id AS user_id, u.username, u.is_active, u.last_login_at,
              (SELECT COUNT(*) FROM lead_events le
                WHERE le.account_id = u.account_id AND le.actor_user_id = u.id
                  AND le.occurred_at > NOW() - make_interval(days => %(days)s)) AS lead_events,
              (SELECT COUNT(*) FROM calls c
                WHERE c.account_id = u.account_id AND c.user_id = u.id
                  AND c.started_at > NOW() - make_interval(days => %(days)s))   AS calls,
              (SELECT COUNT(*) FROM auth_events ae
                WHERE ae.user_id = u.id AND ae.success
                  AND ae.created_at > NOW() - make_interval(days => %(days)s))  AS logins
            FROM users u WHERE u.account_id = %(id)s ORDER BY u.id
            """,
            {"id": account_id, "days": days},
        )
        return {"days": days, "items": dict_fetchall(cur)}


@router.post("/admin/accounts/{account_id}/plan")
def admin_set_plan(
    account_id: int,
    body: PlanAssign,
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    """Assign a plan (+ per-module overrides) — the API twin of
    scripts/set_account_plan.py, sharing resolve_plan_modules so they can't drift.

    Refused (409) when a live Stripe subscription exists, same as the trial
    endpoint: the billing webhook re-applies the subscription's plan on every
    subscription event and would silently fight the override. The CLI remains
    the deliberate escape hatch for a paying org that genuinely needs one.
    """
    _require_account(db, account_id)
    with db.cursor() as cur:
        cur.execute(
            "SELECT stripe_subscription_id FROM account_billing WHERE account_id = %s",
            (account_id,),
        )
        sub = cur.fetchone()
    if sub and sub[0]:
        raise HTTPException(
            status_code=409,
            detail="This account has a live Stripe subscription — change its plan in Stripe.",
        )
    try:
        modules = resolve_plan_modules(body.plan, body.enable, body.disable)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with db.cursor() as cur:
        cur.execute("SELECT plan_name FROM account_plans WHERE account_id = %s", (account_id,))
        old = cur.fetchone()
        cur.execute(
            "INSERT INTO account_plans (account_id, plan_name, modules, updated_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (account_id) DO UPDATE SET plan_name = %s, modules = %s, updated_at = NOW()",
            (account_id, body.plan, Json(modules), body.plan, Json(modules)),
        )
    record_admin_action(
        db, admin, "account.plan_set", "account", account_id,
        {"old_plan": old[0] if old else None, "new_plan": body.plan,
         "enable": body.enable, "disable": body.disable},
    )
    db.commit()
    return {"plan_name": body.plan, "modules": modules}


@router.post("/admin/accounts/{account_id}/trial")
def admin_set_trial(
    account_id: int,
    body: TrialUpdate,
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    """Extend or expire an account's local trial (mirrors api/billing.py's
    expire_stale_trials semantics). Refused when a Stripe subscription exists —
    Stripe owns that state and the webhook would fight the override."""
    _require_account(db, account_id)
    with db.cursor() as cur:
        cur.execute(
            "SELECT status, trial_ends_at, stripe_subscription_id "
            "FROM account_billing WHERE account_id = %s", (account_id,),
        )
        billing = dict_fetchone(cur)
    if billing and billing["stripe_subscription_id"]:
        raise HTTPException(
            status_code=409,
            detail="This account has a live Stripe subscription — manage it in Stripe.",
        )

    if body.action == "extend":
        if body.trial_ends_at is None:
            raise HTTPException(status_code=400, detail="trial_ends_at is required to extend.")
        ends = body.trial_ends_at
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        if ends <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="trial_ends_at must be in the future.")
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO account_billing (account_id, plan_name, status, trial_ends_at) "
                "VALUES (%s, 'pro', 'trialing', %s) "
                "ON CONFLICT (account_id) DO UPDATE SET status = 'trialing', "
                "trial_ends_at = EXCLUDED.trial_ends_at, updated_at = NOW()",
                (account_id, ends),
            )
        # Reactivating an already-expired trial restores the trial's plan too —
        # expire_stale_trials downgraded modules to starter when it fired.
        if billing and billing["status"] == "trial_expired":
            apply_plan(db, account_id, "pro")
        record_admin_action(
            db, admin, "account.trial_extend", "account", account_id,
            {"old_status": billing["status"] if billing else None,
             "trial_ends_at": ends.isoformat()},
        )
    elif body.action == "expire":
        if not billing:
            raise HTTPException(status_code=400, detail="This account has no trial to expire.")
        with db.cursor() as cur:
            cur.execute(
                "UPDATE account_billing SET status = 'trial_expired', "
                "trial_ends_at = NOW(), updated_at = NOW() WHERE account_id = %s",
                (account_id,),
            )
        apply_plan(db, account_id, "starter")
        record_admin_action(
            db, admin, "account.trial_expire", "account", account_id,
            {"old_status": billing["status"]},
        )
    else:
        raise HTTPException(status_code=400, detail="action must be 'extend' or 'expire'.")

    db.commit()
    with db.cursor() as cur:
        cur.execute(
            "SELECT plan_name, status, trial_ends_at, current_period_end, updated_at "
            "FROM account_billing WHERE account_id = %s", (account_id,),
        )
        return dict_fetchone(cur)


@router.delete("/admin/accounts/{account_id}")
def admin_delete_account(
    account_id: int,
    confirm_name: str = Query(..., description="Must equal the org's name exactly"),
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    """Permanently delete an organization and everything it owns.

    The typed confirmation is a query param, not a JSON body: a request body on
    DELETE is legal but widely mishandled — httpx's own ``.delete()`` refuses to
    send one, and intermediaries have been known to strip it, which would turn
    this endpoint into a permanent 422 behind a proxy. The org's name is not a
    secret, so there is nothing lost by putting it in the URL. (It must not be
    called ``token`` — that name collides with get_current_user's ?token=
    CSV-export fallback.)

    The teardown is still the database's. Migration 0074 made every FK into
    ``accounts(id)`` ON DELETE CASCADE precisely so this endpoint does not carry
    a hand-ordered list of forty DELETEs that goes stale the first time someone
    adds a table — Postgres owns the ordering, and the tenant-parent FKs beneath
    it (contact_history → properties, invoice_line_items → invoices, …) carry
    the sweep down to the leaves. The one concession to size is that leads go
    first, in batches (``_delete_account_leads``), because a cascade is per-row
    trigger work and ``properties`` has nineteen children — enough of them, on a
    real org, to run the single ``DELETE FROM accounts`` past
    ``statement_timeout``. That is a bound on one statement's cost, not a second
    opinion about the order: the cascade still deletes anything the batches miss.

    Two things sit outside the cascade and are handled here. ``auth_events``
    carries ``account_id`` with no FK by design (0073), so it is deleted
    explicitly — leaving it would strand the org's login history, including the
    email addresses that were typed at the login form. And the shared
    ``parcels`` cache is untouched on purpose: it holds free, tenant-independent
    county facts that other orgs are still using, so an org's ``properties``
    rows die while the parcels they pointed at stay.

    ``_assert_account_purged`` then re-reads the catalog and refuses to commit
    if anything survived. Counts are taken **before** the delete so the audit
    row (which outlives the org — ``admin_audit_log`` has no ``account_id``)
    records what was actually destroyed.
    """
    account = _require_account(db, account_id)
    with db.cursor() as cur:
        cur.execute(
            "SELECT stripe_subscription_id FROM account_billing WHERE account_id = %s",
            (account_id,),
        )
        sub = cur.fetchone()
        cur.execute(
            "SELECT username FROM users WHERE account_id = %s AND is_platform_admin "
            "ORDER BY id", (account_id,),
        )
        platform_admins = [r[0] for r in cur.fetchall()]

    problems = validate_account_delete(
        account,
        admin_account_id=admin.get("account_id"),
        confirm_name=confirm_name,
        has_subscription=bool(sub and sub[0]),
        platform_admins=platform_admins,
    )
    if problems:
        # 409, not 400: every one of these describes the org's current state,
        # and each is fixable — cancel in Stripe, revoke the flag, retype the name.
        raise HTTPException(status_code=409, detail=" ".join(problems))

    counts = _account_counts(db, account_id)
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users WHERE account_id = %s", (account_id,))
        counts["users"] = cur.fetchone()[0]
        # SET LOCAL: reverts when this transaction ends, so the next request to
        # borrow this pooled connection is back under the ordinary 30s cap.
        cur.execute(f"SET LOCAL statement_timeout = {int(ACCOUNT_DELETE_TIMEOUT_MS)}")
        cur.execute("DELETE FROM auth_events WHERE account_id = %s", (account_id,))
        counts["auth_events"] = cur.rowcount
        _delete_account_leads(cur, account_id, ACCOUNT_DELETE_BATCH)
        cur.execute("DELETE FROM accounts WHERE id = %s", (account_id,))

    record_admin_action(
        db, admin, "account.delete", "account", account_id,
        {"name": account["name"], "business_type": account["business_type"],
         "counts": counts},
    )
    _assert_account_purged(db, account_id)
    db.commit()
    log.warning("platform admin %s deleted account %s (%s)",
                admin.get("username"), account_id, account["name"])
    return {"deleted": True, "account_id": account_id, "name": account["name"],
            "counts": counts}


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/admin/users")
def admin_users(
    q: str | None = Query(None),
    account_id: int | None = Query(None),
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    email_verified: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: PGConn = Depends(get_db),
):
    page, page_size = clamp_page(page, page_size)
    where, params = [], []
    if q:
        where.append("(u.email ILIKE %s OR u.username ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if account_id is not None:
        where.append("u.account_id = %s")
        params.append(account_id)
    if role:
        where.append("u.role = %s")
        params.append(role)
    if is_active is not None:
        where.append("u.is_active = %s")
        params.append(is_active)
    if email_verified is not None:
        where.append("u.email_verified = %s")
        params.append(email_verified)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT u.id, u.username, u.email, u.role, u.is_active, u.email_verified,
                   u.is_platform_admin, u.account_id, a.name AS account_name,
                   u.created_at, u.last_login_at,
                   COUNT(*) OVER () AS _total
            FROM users u JOIN accounts a ON a.id = u.account_id
            {where_sql}
            ORDER BY u.created_at DESC, u.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, page_size, (page - 1) * page_size),
        )
        rows = dict_fetchall(cur)
        return _finish_page(
            cur, rows, page, page_size,
            f"SELECT COUNT(*) FROM users u JOIN accounts a ON a.id = u.account_id {where_sql}",
            tuple(params),
        )


@router.post("/admin/users", status_code=201)
def admin_create_user(
    body: AdminUserCreate,
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    """Create a user in an existing org, or provision a fresh org + owner.

    Unlike the tenant POST /users and scripts/create_user.py, this path
    validates the password/username and marks the email verified — an
    admin-created login shouldn't start life gated behind a verification email.
    """
    email = normalize_email(body.email)
    problems: list[str] = []
    if not EMAIL_RE.match(email):
        problems.append("A valid email address is required.")
    pw_problem = password_problem(body.password)
    if pw_problem:
        problems.append(pw_problem)
    if body.username is not None and not USERNAME_RE.match(body.username):
        problems.append("Username must be 3–32 chars: lowercase letters, digits, . _ -")
    if (body.account_id is None) == (body.new_account is None):
        problems.append("Provide exactly one of account_id or new_account.")
    if body.role not in ADMIN_ROLES:
        problems.append(f"Role must be one of: {', '.join(ADMIN_ROLES)}.")
    if body.new_account:
        name_problem = company_problem(body.new_account.name)
        if name_problem:
            problems.append(name_problem)
        if body.new_account.business_type not in BUSINESS_TYPES:
            problems.append(f"Unknown business type '{body.new_account.business_type}'.")
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))

    if body.new_account:
        # Fresh org: identical provisioning to self-serve signup (stages,
        # fields, plan, trial row, workflows) — the first user is its owner.
        created = _provision_org_with_owner(
            db, admin, name=body.new_account.name.strip(),
            business_type=body.new_account.business_type,
            email=email, password=body.password, username=body.username,
        )
        user_id = created["user_id"]
    else:
        _require_account(db, body.account_id)
        user_id = None
        try:
            with db.cursor() as cur:
                for candidate in username_candidates(body.username or derive_username(email)):
                    cur.execute("SELECT 1 FROM users WHERE username = %s", (candidate,))
                    if cur.fetchone():
                        continue
                    cur.execute(
                        "INSERT INTO users (username, email, hashed_pw, role, account_id, "
                        "email_verified) VALUES (%s, %s, %s, %s, %s, TRUE) RETURNING id",
                        (candidate, email, hash_password(body.password), body.role,
                         body.account_id),
                    )
                    user_id = cur.fetchone()[0]
                    break
        except psycopg2.errors.UniqueViolation:
            db.rollback()
            raise HTTPException(status_code=409, detail="A user with that email already exists.")
        if user_id is None:
            raise HTTPException(status_code=409, detail="Could not find a free username.")
        record_admin_action(
            db, admin, "user.create", "user", user_id,
            {"email": email, "role": body.role, "account_id": body.account_id,
             "new_account": False},
        )

    db.commit()
    return _get_user(db, user_id)


@router.patch("/admin/users/{user_id}")
def admin_update_user(
    user_id: int,
    body: AdminUserUpdate,
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    problems = validate_admin_user_update(changes, is_self=user_id == admin["id"])
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))
    old = _get_user(db, user_id)

    # Fixed column map — SET clause is built only from these literal names.
    columns = {"role", "is_active", "email_verified", "is_platform_admin"}
    changed = {k: v for k, v in changes.items() if k in columns and old[k] != v}
    if changed:
        set_sql = ", ".join(f"{col} = %s" for col in changed)
        with db.cursor() as cur:
            cur.execute(
                f"UPDATE users SET {set_sql} WHERE id = %s",
                (*changed.values(), user_id),
            )
        record_admin_action(
            db, admin, "user.update", "user", user_id,
            {field: {"old": old[field], "new": value} for field, value in changed.items()},
        )
        db.commit()
    return _get_user(db, user_id)


@router.delete("/admin/users/{user_id}")
def admin_delete_user(
    user_id: int,
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    """Delete a login. The org's data stays; their name comes off it.

    A user owns nothing in this schema, so migration 0074 made every FK into
    ``users(id)`` ON DELETE SET NULL: leads they were assigned become
    unassigned, invoices they raised keep their totals and lose their author,
    notes keep their text. The two genuinely user-owned tables — ``user_tokens``
    and ``oauth_identities`` — cascade, which is also what revokes any
    outstanding password-reset link and unlinks their Google/Apple identity.

    ``auth_events`` keeps their login history with a NULL ``user_id`` and the
    typed identifier intact, so the security panel still shows what happened
    before the delete. Deactivating (PATCH ``is_active``) remains the reversible
    option and the right one for most cases; this is for a login that should
    stop existing.
    """
    user = _get_user(db, user_id)
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FILTER (WHERE id <> %(uid)s) AS siblings, "
            "       COUNT(*) FILTER (WHERE id <> %(uid)s AND role = 'owner') AS other_owners "
            "FROM users WHERE account_id = %(aid)s",
            {"uid": user_id, "aid": user["account_id"]},
        )
        siblings, other_owners = cur.fetchone()

    problems = validate_user_delete(
        user, admin_id=admin["id"], siblings=siblings, other_owners=other_owners,
    )
    if problems:
        raise HTTPException(status_code=409, detail=" ".join(problems))

    with db.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    record_admin_action(
        db, admin, "user.delete", "user", user_id,
        {"username": user["username"], "email": user["email"], "role": user["role"],
         "account_id": user["account_id"]},
    )
    db.commit()
    log.warning("platform admin %s deleted user %s (%s)",
                admin.get("username"), user_id, user["username"])
    return {"deleted": True, "user_id": user_id, "username": user["username"],
            "account_id": user["account_id"]}


@router.post("/admin/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: int,
    body: ResetLinkRequest,
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    """Mint a one-time reset link through the same user_tokens machinery as the
    self-serve flow — the returned URL works in the existing /reset-password
    page even when email isn't configured. The raw token is returned to the
    admin and never stored or audited."""
    user = _get_user(db, user_id)
    raw = _issue_token(db, user_id, "reset_password")
    record_admin_action(
        db, admin, "user.reset_link", "user", user_id,
        {"emailed": body.send_email},
    )
    db.commit()
    emailed = bool(body.send_email) and _send_reset_email(user["email"], raw)
    return {
        "reset_url": build_reset_url(APP_BASE_URL, raw),
        "emailed": emailed,
        "expires_in_hours": int(RESET_PASSWORD_TTL.total_seconds() // 3600),
    }


@router.post("/admin/users/{user_id}/set-password")
def admin_set_password(
    user_id: int,
    body: SetPasswordRequest,
    admin: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    if len(body.password or "") < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters.",
        )
    _get_user(db, user_id)
    with db.cursor() as cur:
        cur.execute(
            "UPDATE users SET hashed_pw = %s WHERE id = %s",
            (hash_password(body.password), user_id),
        )
        # Same hygiene as _issue_token: a direct set kills any outstanding link.
        cur.execute(
            "UPDATE user_tokens SET used_at = NOW() "
            "WHERE user_id = %s AND purpose = 'reset_password' AND used_at IS NULL",
            (user_id,),
        )
    record_admin_action(db, admin, "user.set_password", "user", user_id, {})
    db.commit()
    return {"ok": True}


# ── Security panel ────────────────────────────────────────────────────────────

@router.get("/admin/security")
def admin_security(db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT ip, COUNT(*) AS attempts, "
            "COUNT(DISTINCT attempted_identifier) AS identifiers, MAX(created_at) AS last_at "
            "FROM auth_events WHERE NOT success AND created_at > NOW() - INTERVAL '24 hours' "
            "GROUP BY ip ORDER BY attempts DESC LIMIT 20"
        )
        failed_by_ip = dict_fetchall(cur)
        cur.execute(
            "SELECT attempted_identifier, COUNT(*) AS attempts, "
            "COUNT(DISTINCT ip) AS ips, MAX(created_at) AS last_at "
            "FROM auth_events WHERE NOT success AND created_at > NOW() - INTERVAL '24 hours' "
            "GROUP BY attempted_identifier ORDER BY attempts DESC LIMIT 20"
        )
        failed_by_identifier = dict_fetchall(cur)
        cur.execute(
            "SELECT u.id, u.username, u.email, u.created_at, a.name AS account_name "
            "FROM users u JOIN accounts a ON a.id = u.account_id "
            "WHERE u.email_verified = FALSE AND u.is_active "
            "  AND u.created_at < NOW() - INTERVAL '3 days' "
            "ORDER BY u.created_at DESC LIMIT 50"
        )
        unverified_users = dict_fetchall(cur)
        cur.execute(
            "SELECT u.id, u.username, u.email, u.created_at, a.name AS account_name "
            "FROM users u JOIN accounts a ON a.id = u.account_id "
            "WHERE NOT u.is_active ORDER BY u.created_at DESC LIMIT 50"
        )
        disabled_users = dict_fetchall(cur)
        cur.execute(
            "SELECT COUNT(*) FILTER (WHERE expires_at > NOW()) AS live, "
            "COUNT(*) FILTER (WHERE expires_at <= NOW()) AS stale_unused "
            "FROM user_tokens WHERE purpose = 'reset_password' AND used_at IS NULL"
        )
        reset_tokens = dict_fetchone(cur)
        cur.execute(
            "SELECT id, event_type, error, received_at FROM stripe_webhook_events "
            "WHERE status = 'error' ORDER BY received_at DESC LIMIT 20"
        )
        webhook_errors = dict_fetchall(cur)
        cur.execute(
            "SELECT r.id, r.zip, r.status, r.created_at, r.account_id, "
            "a.name AS account_name, r.result_json->>'error' AS error "
            "FROM pipeline_runs r LEFT JOIN accounts a ON a.id = r.account_id "
            "WHERE r.status IN ('failed', 'cancelled') "
            "  AND r.created_at > NOW() - INTERVAL '7 days' "
            "ORDER BY r.created_at DESC LIMIT 20"
        )
        pipeline_failures = dict_fetchall(cur)

    config_checks = evaluate_config_checks({
        "jwt_secret_set": bool(os.getenv("JWT_SECRET_KEY", "")),
        "allow_insecure_dev_jwt": os.getenv("ALLOW_INSECURE_DEV_JWT", "").lower() == "true",
        "app_base_url": APP_BASE_URL,
        "resend_api_key_set": bool(RESEND_API_KEY),
        "resend_from_email_set": bool(RESEND_FROM_EMAIL),
        "billing_configured": billing_configured(),
        "stripe_billing_webhook_secret_set": bool(STRIPE_BILLING_WEBHOOK_SECRET),
        "admin_notification_email_set": bool(ADMIN_NOTIFICATION_EMAIL),
        "self_serve_signup": SELF_SERVE_SIGNUP,
        "twilio_configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
    })

    return {
        "failed_by_ip": failed_by_ip,
        "failed_by_identifier": failed_by_identifier,
        "unverified_users": unverified_users,
        "disabled_users": disabled_users,
        "reset_tokens": reset_tokens,
        "webhook_errors": webhook_errors,
        "pipeline_failures": pipeline_failures,
        "config_checks": config_checks,
    }


# ── Feeds ─────────────────────────────────────────────────────────────────────

@router.get("/admin/auth-events")
def admin_auth_events(
    user_id: int | None = Query(None),
    account_id: int | None = Query(None),
    success: bool | None = Query(None),
    ip: str | None = Query(None),
    method: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: PGConn = Depends(get_db),
):
    page, page_size = clamp_page(page, page_size)
    where, params = [], []
    if user_id is not None:
        where.append("ae.user_id = %s")
        params.append(user_id)
    if account_id is not None:
        where.append("ae.account_id = %s")
        params.append(account_id)
    if success is not None:
        where.append("ae.success = %s")
        params.append(success)
    if ip:
        where.append("ae.ip = %s")
        params.append(ip)
    if method:
        where.append("ae.method = %s")
        params.append(method)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT ae.id, ae.user_id, ae.account_id, ae.attempted_identifier,
                   ae.method, ae.success, ae.failure_reason, ae.ip, ae.user_agent,
                   ae.created_at, u.username, a.name AS account_name,
                   COUNT(*) OVER () AS _total
            FROM auth_events ae
            LEFT JOIN users u ON u.id = ae.user_id
            LEFT JOIN accounts a ON a.id = ae.account_id
            {where_sql}
            ORDER BY ae.created_at DESC, ae.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, page_size, (page - 1) * page_size),
        )
        rows = dict_fetchall(cur)
        return _finish_page(
            cur, rows, page, page_size,
            f"SELECT COUNT(*) FROM auth_events ae {where_sql}",
            tuple(params),
        )


@router.get("/admin/audit-log")
def admin_audit_log(
    admin_user_id: int | None = Query(None),
    action: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: PGConn = Depends(get_db),
):
    page, page_size = clamp_page(page, page_size)
    where, params = [], []
    if admin_user_id is not None:
        where.append("l.admin_user_id = %s")
        params.append(admin_user_id)
    if action:
        where.append("l.action = %s")
        params.append(action)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT l.id, l.admin_user_id, u.username AS admin_username,
                   l.action, l.target_type, l.target_id, l.detail, l.created_at,
                   COUNT(*) OVER () AS _total
            FROM admin_audit_log l
            LEFT JOIN users u ON u.id = l.admin_user_id
            {where_sql}
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, page_size, (page - 1) * page_size),
        )
        rows = dict_fetchall(cur)
        return _finish_page(
            cur, rows, page, page_size,
            f"SELECT COUNT(*) FROM admin_audit_log l {where_sql}",
            tuple(params),
        )


@router.get("/admin/prospects")
def admin_prospects(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: PGConn = Depends(get_db),
):
    """Landing-page prospect signups (migration 0059) — platform-level by
    design, and until now write-only. The admin dashboard is their reader."""
    page, page_size = clamp_page(page, page_size)
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, email, name, source, created_at, updated_at, "
            "COUNT(*) OVER () AS _total "
            "FROM prospect_signups ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
            (page_size, (page - 1) * page_size),
        )
        rows = dict_fetchall(cur)
        return _finish_page(cur, rows, page, page_size,
                            "SELECT COUNT(*) FROM prospect_signups", ())
