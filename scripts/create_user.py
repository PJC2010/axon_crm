#!/usr/bin/env python3
"""Create a user login from the command line.

Inserts a new row into the ``users`` table with a bcrypt-hashed password,
using the same hashing as the API. Handy for bootstrapping the first owner
account, or for creating accounts without going through the HTTP API.

Usage:
    python scripts/create_user.py --username admin --email you@example.com --role owner
    python scripts/create_user.py -u jane -e jane@example.com -r sales_rep -p secret123

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

VALID_ROLES = ("owner", "sales_rep")


def create_user(username: str, email: str, password: str, role: str) -> int:
    """Insert the user and return the new id. Raises on conflict/error."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, email, hashed_pw, role) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (username, email, hash_password(password), role),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
        return new_id
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
        new_id = create_user(args.username, args.email, password, args.role)
    except psycopg2.errors.UniqueViolation:
        print(
            f"Error: a user with that username or email already exists.",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:  # pragma: no cover - surface unexpected DB errors
        print(f"Error creating user: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"✓ Created user '{args.username}' (id={new_id}, role={args.role})")


if __name__ == "__main__":
    main()
