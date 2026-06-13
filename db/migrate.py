#!/usr/bin/env python3
"""Simple sequential SQL migration runner.

Usage:
    python db/migrate.py                    # run all pending migrations
    python db/migrate.py --status           # list applied/pending
    python db/migrate.py --create my_name  # create new numbered migration file
"""
import os
import sys
import argparse
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def ensure_migrations_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id         SERIAL PRIMARY KEY,
                filename   TEXT NOT NULL UNIQUE,
                applied_at TIMESTAMP DEFAULT NOW()
            )
        """)
    conn.commit()


def applied_migrations(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations ORDER BY filename")
        return {row[0] for row in cur.fetchall()}


def all_migration_files() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return files


def run(args):
    conn = get_conn()
    ensure_migrations_table(conn)
    applied = applied_migrations(conn)
    pending = [f for f in all_migration_files() if f.name not in applied]

    if not pending:
        print("Nothing to migrate — all up to date.")
        return

    for path in pending:
        print(f"  → applying {path.name} ... ", end="", flush=True)
        sql = path.read_text()
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
            )
        conn.commit()
        print("done")

    conn.close()
    print(f"\n{len(pending)} migration(s) applied.")


def status(args):
    conn = get_conn()
    ensure_migrations_table(conn)
    applied = applied_migrations(conn)
    conn.close()
    all_files = all_migration_files()

    print(f"{'STATUS':<10} FILENAME")
    print("-" * 50)
    for f in all_files:
        tag = "applied" if f.name in applied else "PENDING"
        print(f"  {tag:<10} {f.name}")

    extra = applied - {f.name for f in all_files}
    for name in sorted(extra):
        print(f"  {'orphan':<10} {name}")


def create(args):
    existing = all_migration_files()
    next_num = len(existing) + 1
    slug = args.name.lower().replace(" ", "_")
    filename = f"{next_num:04d}_{slug}.sql"
    path = MIGRATIONS_DIR / filename
    path.write_text(f"-- {slug}\n")
    print(f"Created {path}")


def main():
    parser = argparse.ArgumentParser(description="Axon CRM migration runner")
    sub = parser.add_subparsers()

    p_status = sub.add_parser("status", help="Show migration status")
    p_status.set_defaults(func=status)

    p_create = sub.add_parser("create", help="Create new migration file")
    p_create.add_argument("name", help="Migration name (e.g. add_customers)")
    p_create.set_defaults(func=create)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
