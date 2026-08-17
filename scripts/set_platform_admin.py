#!/usr/bin/env python3
"""Grant or revoke platform-admin access (users.is_platform_admin) from the CLI.

This is how the FIRST platform admin gets flagged — the /api/admin surface
(api/routes/admin.py) is guarded by this flag, so someone has to be granted it
out-of-band before the dashboard's own user editor can manage the rest. The
flag is orthogonal to the tenant ``role`` column: role governs power inside one
org, this flag governs the cross-tenant admin surface (migration 0073).

Usage:
    python scripts/set_platform_admin.py --list
    python scripts/set_platform_admin.py --email you@example.com --grant
    python scripts/set_platform_admin.py --email you@example.com --revoke

Requires DATABASE_URL and applied migrations (python db/migrate.py).
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401  (side effect: load_dotenv populates DATABASE_URL)


def list_admins(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT u.id, u.username, u.email, u.role, a.name "
            "FROM users u JOIN accounts a ON a.id = u.account_id "
            "WHERE u.is_platform_admin ORDER BY u.id"
        )
        rows = cur.fetchall()
    if not rows:
        print("No platform admins are flagged.")
        return
    print(f"{'ID':<5}{'USERNAME':<20}{'EMAIL':<32}{'ROLE':<11}ORG")
    print("-" * 88)
    for user_id, username, email, role, org in rows:
        print(f"{user_id:<5}{username[:19]:<20}{email[:31]:<32}{role:<11}{org}")


def set_flag(conn, email: str, value: bool) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET is_platform_admin = %s WHERE lower(email) = lower(%s) "
            "RETURNING id, username",
            (value, email),
        )
        row = cur.fetchone()
    if row is None:
        raise SystemExit(f"No user with email '{email}'")
    conn.commit()
    verb = "granted to" if value else "revoked from"
    print(f"✓ Platform admin {verb} '{row[1]}' (id={row[0]}, email={email})")


def main():
    parser = argparse.ArgumentParser(
        description="Grant/revoke Axon platform-admin access (the /api/admin surface)",
    )
    parser.add_argument("--email", help="Email of the user to modify")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--grant", action="store_true", help="Set is_platform_admin = TRUE")
    action.add_argument("--revoke", action="store_true", help="Set is_platform_admin = FALSE")
    parser.add_argument("--list", action="store_true", help="List current platform admins, then exit")
    args = parser.parse_args()

    if "DATABASE_URL" not in os.environ:
        parser.error("DATABASE_URL environment variable is not set")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        if args.list:
            list_admins(conn)
            return
        if not args.email or not (args.grant or args.revoke):
            parser.error("provide --email with --grant or --revoke (or use --list)")
        set_flag(conn, args.email, bool(args.grant))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
