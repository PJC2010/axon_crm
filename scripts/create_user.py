#!/usr/bin/env python3
"""Create a user login from the command line.

Inserts a new row into the ``users`` table with a bcrypt-hashed password,
using the same hashing as the API. Handy for bootstrapping the first owner
account, or for creating accounts without going through the HTTP API.

Every user belongs to an organization (account). Choose exactly one of:
  --new-account "<Org Name>"   create a fresh, isolated org for this user
  --account-id <id>            add this user to an existing org (shares its leads)

Usage:
    # Bootstrap a brand-new isolated org + its owner:
    python scripts/create_user.py -u admin -e you@example.com -r owner --new-account "Acme Epoxy"
    # Add a teammate to an existing org (they see that org's leads):
    python scripts/create_user.py -u jane -e jane@example.com -r sales_rep --account-id 2

If --password is omitted you will be prompted for it (input hidden).

Requires the DATABASE_URL environment variable to be set and migrations to
have been applied (python db/migrate.py).
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

import psycopg2

# Allow running as a standalone script: make the repo root importable so
# `from api.security import hash_password` works regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.security import hash_password  # noqa: E402
from api.accounts import create_account, seed_business_type_workflows  # noqa: E402
from api.business_types import BUSINESS_TYPES, DEFAULT_BUSINESS_TYPE  # noqa: E402

VALID_ROLES = ("owner", "sales_rep")


def create_user(username: str, email: str, password: str, role: str,
                account_id: int | None, new_account: str | None,
                business_type: str = DEFAULT_BUSINESS_TYPE) -> tuple[int, int]:
    """Insert the user and return (user_id, account_id). Raises on conflict/error.

    Exactly one of `account_id` (join existing org) or `new_account` (create a
    fresh org, seeding the business type's stages/fields/plan) must be provided.
    For a new account, the preset's default workflows are seeded after the user
    insert — scheduled rules run as their creator, so a user must exist first.
    """
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        is_new_account = bool(new_account)
        if new_account:
            account_id = create_account(conn, new_account, business_type=business_type)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, email, hashed_pw, role, account_id) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (username, email, hash_password(password), role, account_id),
            )
            new_id = cur.fetchone()[0]
        if is_new_account:
            seed_business_type_workflows(conn, account_id, business_type, new_id)
        conn.commit()
        return new_id, account_id
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Create a new Axon CRM user login",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-u", "--username", required=True, help="Login username (unique)")
    parser.add_argument("-e", "--email", required=True, help="Email address (unique)")
    parser.add_argument(
        "-r", "--role", default="sales_rep", choices=VALID_ROLES, help="User role"
    )
    parser.add_argument(
        "-p",
        "--password",
        help="Password (prompted securely if omitted)",
    )
    account = parser.add_mutually_exclusive_group(required=True)
    account.add_argument(
        "--new-account", metavar="NAME", dest="new_account",
        help="Create a fresh isolated org with this name and put the user in it",
    )
    account.add_argument(
        "--account-id", type=int, dest="account_id",
        help="Add the user to this existing org (shares its leads)",
    )
    parser.add_argument(
        "--business-type", dest="business_type", default=DEFAULT_BUSINESS_TYPE,
        choices=sorted(BUSINESS_TYPES), metavar="TYPE",
        help=f"Preset for a new org ({', '.join(sorted(BUSINESS_TYPES))}); only used with --new-account",
    )
    args = parser.parse_args()

    if "DATABASE_URL" not in os.environ:
        parser.error("DATABASE_URL environment variable is not set")

    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm password: "):
            parser.error("Passwords do not match")
    if not password:
        parser.error("Password must not be empty")

    try:
        new_id, account_id = create_user(
            args.username, args.email, password, args.role,
            args.account_id, args.new_account, args.business_type,
        )
    except psycopg2.errors.UniqueViolation:
        print(
            f"Error: a user with that username or email already exists.",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:  # pragma: no cover - surface unexpected DB errors
        print(f"Error creating user: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"✓ Created user '{args.username}' (id={new_id}, role={args.role}, account_id={account_id})")


if __name__ == "__main__":
    main()
