"""Feature-module entitlements.

Axon's optional features are grouped into *modules* that pricing plans bundle and
turn on/off per account (see db/migrations/0039_account_plans.sql). This module is
the single source of truth for:

  * which modules exist (``MODULE_KEYS``),
  * which modules each named plan grants (``PLAN_CATALOG``),
  * how to resolve an account's enabled modules (``get_account_modules``), and
  * a FastAPI guard to gate a route on a module (``require_module``).

``core`` features (leads, Kanban board view, tasks, notes, history, export) are
always on and are deliberately NOT modules — only optional, gateable features are.

Resolution is permissive by design: a module is enabled unless an account's stored
plan explicitly sets it ``false``. Accounts with no ``account_plans`` row (e.g. a
brand-new account before provisioning, or a missing backfill) get the full set, so
gating can never silently strip access. Plans tighten access by listing modules and
setting the ones they don't grant to ``false``.
"""
from fastapi import Depends, HTTPException
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, get_current_user

# Every optional, gateable module. Keep in sync with the plan doc and the frontend
# nav config (frontend/lib/nav.ts).
MODULE_KEYS: tuple[str, ...] = (
    "prospecting",   # property data acquisition + scoring ("pipeline refresh")
    "map",           # geographic property map
    "invoicing",     # invoices + accounts-receivable
    "bookkeeping",   # expenses, P&L, job costing
    "quotes",        # quote builder + convert-to-invoice
    "marketing",     # Meta/ad insights
    "automation",    # workflow rules engine
    # Associated child objects (Phase 5 of the generalization roadmap). Existing
    # accounts were backfilled OFF in migration 043; business-type presets opt in.
    "policies",      # insurance book of business + renewal automation
    "orders",        # retail purchase history
    "appointments",  # scheduled visits/bookings
    "calls",         # call tracking + power dialer (Twilio tracking number, call log, outbound queue)
)

# Named plans bundle modules. The exact tiers/prices are a product decision; this
# is the resolved module set each tier grants. Every tier gets `prospecting` —
# scoring is the moat and nobody should experience Axon without it; lower tiers
# meter it via PLAN_SCORING_LIMITS instead of withholding the module. `marketing`
# (Meta CSV insights) is granted by no named plan — the module key and routes
# stay, so it remains re-grantable per-account via overrides
# (scripts/set_account_plan.py) if a fit ever appears.
PLAN_CATALOG: dict[str, set[str]] = {
    "starter": {"prospecting"},
    "growth": {"prospecting", "invoicing", "bookkeeping", "quotes", "automation", "appointments"},
    "pro": set(MODULE_KEYS) - {"marketing"},
}

# Monthly scored-lead reveal allowance per plan (None = unlimited). Enforced at
# render time by api/scoring_quota.py: scored-but-unworked leads past the
# month's allowance show masked, mirroring the public ZIP-sample teaser.
PLAN_SCORING_LIMITS: dict[str, int | None] = {
    "starter": 25,
    "growth": 100,
    "pro": None,
}


def _plan_defaults(plan_name: str) -> dict[str, bool]:
    """Module map a plan grants by default, before per-account overrides."""
    granted = PLAN_CATALOG.get(plan_name, set(MODULE_KEYS))
    return {key: key in granted for key in MODULE_KEYS}


def get_account_modules(account_id: int, db: PGConn) -> dict[str, bool]:
    """Resolve the enabled-module map for an account.

    Starts from the account's plan defaults, then applies any explicit overrides
    stored in ``account_plans.modules``. An account with no row gets the full set
    so gating stays additive (never removes access from an un-provisioned account).
    """
    with db.cursor() as cur:
        cur.execute(
            "SELECT plan_name, modules FROM account_plans WHERE account_id = %s",
            (account_id,),
        )
        row = cur.fetchone()

    if row is None:
        # Un-provisioned account: grant everything rather than locking the user out.
        return {key: True for key in MODULE_KEYS}

    plan_name, overrides = row
    resolved = _plan_defaults(plan_name)
    if overrides:
        for key, enabled in overrides.items():
            if key in resolved:
                resolved[key] = bool(enabled)
    return resolved


def account_has_module(account_id: int, module_key: str, db: PGConn) -> bool:
    return get_account_modules(account_id, db).get(module_key, True)


def get_scoring_limit(account_id: int, db: PGConn) -> int | None:
    """Monthly scored-lead reveal limit for an account (None = unlimited).

    The per-account ``account_plans.scoring_monthly_limit`` column (migration
    0061) overrides the plan default from ``PLAN_SCORING_LIMITS``. Accounts with
    no plan row are unlimited — permissive, like module resolution.
    """
    with db.cursor() as cur:
        cur.execute(
            "SELECT plan_name, scoring_monthly_limit FROM account_plans WHERE account_id = %s",
            (account_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    plan_name, override = row
    if override is not None:
        return override
    return PLAN_SCORING_LIMITS.get(plan_name)


def require_module(module_key: str):
    """FastAPI dependency factory that 403s when the caller's account lacks a module.

    Mirrors the ``require_owner`` pattern in api/deps.py. Usage::

        @router.get("/map/cells")
        def map_cells(..., _=Depends(require_module("map"))):
            ...

    The 403 body carries ``module`` and ``upgrade`` so the frontend can show an
    "Upgrade to unlock" prompt instead of a generic error.
    """
    if module_key not in MODULE_KEYS:
        raise ValueError(f"Unknown module key: {module_key!r}")

    def _guard(
        current_user: dict = Depends(get_current_user),
        db: PGConn = Depends(get_db),
    ) -> dict:
        if not account_has_module(current_user["account_id"], module_key, db):
            raise HTTPException(
                status_code=403,
                detail={
                    "detail": f"The '{module_key}' module is not enabled for your plan.",
                    "module": module_key,
                    "upgrade": True,
                },
            )
        return current_user

    return _guard
