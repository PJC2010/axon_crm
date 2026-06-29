"""Feature-module entitlements.

Axon's optional features are grouped into *modules* that pricing plans bundle and
turn on/off per account (see db/migrations/039_account_plans.sql). This module is
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
)

# Named plans bundle modules. The exact tiers/prices are a product decision; this
# is the resolved module set each tier grants. `pro` is the full set (also the
# backfill default for existing accounts).
PLAN_CATALOG: dict[str, set[str]] = {
    "starter": set(),  # core only
    "growth": {"invoicing", "bookkeeping", "quotes", "automation"},
    "pro": set(MODULE_KEYS),
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
