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

from api.entitlements import PLAN_CATALOG, resolve_plan_modules  # noqa: E402
from api.business_types import BUSINESS_TYPES  # noqa: E402


def list_accounts(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT a.id, a.name, a.business_type, p.plan_name, p.modules "
            "FROM accounts a LEFT JOIN account_plans p ON p.account_id = a.id "
            "ORDER BY a.id"
        )
        rows = cur.fetchall()
    print(f"{'ID':<5}{'NAME':<24}{'TYPE':<22}{'PLAN':<9}MODULES")
    print("-" * 96)
    for acct_id, name, btype, plan, modules in rows:
        enabled = ",".join(k for k, v in (modules or {}).items() if v) or "(none)"
        print(f"{acct_id:<5}{(name or '')[:23]:<24}{(btype or '—'):<22}{(plan or '—'):<9}{enabled}")


def set_business_type(conn, account_id: int, business_type: str) -> None:
    if business_type not in BUSINESS_TYPES:
        raise SystemExit(f"Unknown business type '{business_type}'. Choose from: {', '.join(BUSINESS_TYPES)}")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM accounts WHERE id = %s", (account_id,))
        if cur.fetchone() is None:
            raise SystemExit(f"No account with id={account_id}")
        cur.execute(
            "UPDATE accounts SET business_type = %s WHERE id = %s",
            (business_type, account_id),
        )
    conn.commit()


def set_plan(conn, account_id: int, plan: str, enable: list[str], disable: list[str]) -> dict:
    try:
        modules = resolve_plan_modules(plan, enable, disable)
    except ValueError as exc:
        raise SystemExit(str(exc))

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
    parser.add_argument("--business-type", choices=sorted(BUSINESS_TYPES), dest="business_type",
                        help="Business type to assign (terminology/categories preset)")
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
        if args.account_id is None:
            parser.error("--account-id is required (or use --list)")
        if args.plan is None and args.business_type is None:
            parser.error("provide --plan and/or --business-type (or use --list)")
        if args.business_type:
            set_business_type(conn, args.account_id, args.business_type)
            print(f"✓ Account {args.account_id} → business type '{args.business_type}'")
        if args.plan:
            modules = set_plan(conn, args.account_id, args.plan, args.enable, args.disable)
            enabled = ", ".join(k for k, v in modules.items() if v) or "(none)"
            print(f"✓ Account {args.account_id} → plan '{args.plan}'. Enabled modules: {enabled}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
