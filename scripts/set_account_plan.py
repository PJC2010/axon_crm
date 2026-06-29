#!/usr/bin/env python3
"""Set an account's pricing plan and feature modules from the command line.

This is the platform-admin path for changing what an org is entitled to. Owners can
toggle modules *within* their plan via the API (PATCH /api/account/plan), but
upgrading/downgrading the plan itself happens here (no billing integration yet).

Usage:
    # List every account and its current plan/modules:
    python scripts/set_account_plan.py --list

    # Switch an account to a named plan (resets modules to that plan's defaults):
    python scripts/set_account_plan.py --account-id 2 --plan growth

    # Switch plan and override individual modules on/off:
    python scripts/set_account_plan.py --account-id 2 --plan growth --enable map --disable quotes

Plans (see api/entitlements.py PLAN_CATALOG):
    starter  — core only (no optional modules)
    growth   — invoicing, bookkeeping, quotes, automation
    pro      — all modules

Requires DATABASE_URL and applied migrations (python db/migrate.py).
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import Json

# Make the repo root importable so the entitlements catalog stays the single source.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.entitlements import MODULE_KEYS, PLAN_CATALOG, _plan_defaults  # noqa: E402


def list_accounts(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT a.id, a.name, p.plan_name, p.modules "
            "FROM accounts a LEFT JOIN account_plans p ON p.account_id = a.id "
            "ORDER BY a.id"
        )
        rows = cur.fetchall()
    print(f"{'ID':<5}{'NAME':<28}{'PLAN':<10}MODULES")
    print("-" * 80)
    for acct_id, name, plan, modules in rows:
        enabled = ",".join(k for k, v in (modules or {}).items() if v) or "(none)"
        print(f"{acct_id:<5}{(name or '')[:27]:<28}{(plan or '—'):<10}{enabled}")


def set_plan(conn, account_id: int, plan: str, enable: list[str], disable: list[str]) -> dict:
    if plan not in PLAN_CATALOG:
        raise SystemExit(f"Unknown plan '{plan}'. Choose from: {', '.join(PLAN_CATALOG)}")
    for key in (*enable, *disable):
        if key not in MODULE_KEYS:
            raise SystemExit(f"Unknown module '{key}'. Choose from: {', '.join(MODULE_KEYS)}")

    modules = _plan_defaults(plan)
    for key in enable:
        modules[key] = True
    for key in disable:
        modules[key] = False

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM accounts WHERE id = %s", (account_id,))
        if cur.fetchone() is None:
            raise SystemExit(f"No account with id={account_id}")
        cur.execute(
            "INSERT INTO account_plans (account_id, plan_name, modules, updated_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (account_id) DO UPDATE SET plan_name = %s, modules = %s, updated_at = NOW()",
            (account_id, plan, Json(modules), plan, Json(modules)),
        )
    conn.commit()
    return modules


def main():
    parser = argparse.ArgumentParser(
        description="Set an Axon CRM account's plan and feature modules",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--list", action="store_true", help="List accounts and their plans, then exit")
    parser.add_argument("--account-id", type=int, help="Account to modify")
    parser.add_argument("--plan", choices=sorted(PLAN_CATALOG), help="Plan to assign")
    parser.add_argument("--enable", nargs="*", default=[], metavar="MODULE",
                        help="Modules to force on (beyond the plan's defaults)")
    parser.add_argument("--disable", nargs="*", default=[], metavar="MODULE",
                        help="Modules to force off")
    args = parser.parse_args()

    if "DATABASE_URL" not in os.environ:
        parser.error("DATABASE_URL environment variable is not set")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        if args.list:
            list_accounts(conn)
            return
        if args.account_id is None or args.plan is None:
            parser.error("--account-id and --plan are required (or use --list)")
        modules = set_plan(conn, args.account_id, args.plan, args.enable, args.disable)
    finally:
        conn.close()

    enabled = ", ".join(k for k, v in modules.items() if v) or "(none)"
    print(f"✓ Account {args.account_id} → plan '{args.plan}'. Enabled modules: {enabled}")


if __name__ == "__main__":
    main()
