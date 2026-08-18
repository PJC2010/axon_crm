#!/usr/bin/env python3
"""Simple sequential SQL migration runner.

Migration files are named ``NNNN_slug.sql`` with a **4-digit** zero-padded
number so a plain filename sort matches numeric order. (Earlier files used a mix
of 3- and 4-digit prefixes, which made a fresh apply-all run e.g. ``0054`` before
``007`` and fail; see ``_canonical`` for how already-migrated databases stay
compatible with the rename.)

Usage:
    python db/migrate.py                    # run all pending migrations
    python db/migrate.py --status           # list applied/pending
    python db/migrate.py --create my_name  # create new numbered migration file
"""
import os
import re
import sys
import argparse
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_PREFIX_RE = re.compile(r"^(\d+)(_.*)$")


def _canonical(name: str) -> str:
    """Zero-pad a migration filename's leading number to 4 digits.

    Filenames are now all 4-digit, but a database migrated under the old 3-digit
    names has those recorded in ``schema_migrations``. Comparing on this
    canonical form (``005_x.sql`` and ``0005_x.sql`` both → ``0005_x.sql``) lets
    such a database recognize the renamed files as already applied instead of
    re-running every one of them on the next deploy.
    """
    m = _PREFIX_RE.match(name)
    return f"{int(m.group(1)):04d}{m.group(2)}" if m else name


def _migration_number(path: Path) -> int:
    m = _PREFIX_RE.match(path.name)
    return int(m.group(1)) if m else -1


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


def reconcile_legacy_names(conn) -> None:
    """Update any legacy un-padded ``schema_migrations`` rows to the padded
    filename now on disk, so the tracking table matches the files. Idempotent —
    a no-op once every recorded name is already canonical.
    """
    on_disk = {f.name for f in all_migration_files()}
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        recorded = {r[0] for r in cur.fetchall()}
        renamed = 0
        for name in recorded:
            canon = _canonical(name)
            # Only rename toward an actual file, and never onto a name already
            # recorded (which would violate the UNIQUE constraint).
            if canon != name and canon in on_disk and canon not in recorded:
                cur.execute(
                    "UPDATE schema_migrations SET filename = %s WHERE filename = %s",
                    (canon, name),
                )
                renamed += 1
    conn.commit()
    if renamed:
        print(f"  (normalized {renamed} legacy migration name(s) in schema_migrations)")


def all_migration_files() -> list[Path]:
    # Sort by canonical (4-digit) name so ordering is numeric even if a stray
    # un-padded file is ever added.
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: _canonical(p.name))


def run(args):
    conn = get_conn()
    ensure_migrations_table(conn)
    reconcile_legacy_names(conn)
    applied = {_canonical(n) for n in applied_migrations(conn)}
    pending = [f for f in all_migration_files() if _canonical(f.name) not in applied]

    if not pending:
        conn.close()
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
    applied_canon = {_canonical(n) for n in applied}
    all_files = all_migration_files()

    print(f"{'STATUS':<10} FILENAME")
    print("-" * 50)
    for f in all_files:
        tag = "applied" if _canonical(f.name) in applied_canon else "PENDING"
        print(f"  {tag:<10} {f.name}")

    extra = applied_canon - {_canonical(f.name) for f in all_files}
    for name in sorted(extra):
        print(f"  {'orphan':<10} {name}")


def create(args):
    existing = all_migration_files()
    # Next number = highest existing + 1 (gap-safe; don't assume contiguous).
    next_num = max((_migration_number(f) for f in existing), default=-1) + 1
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
