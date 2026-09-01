#!/usr/bin/env python3
"""Archive leads whose dwelling type the deployment does not sell to.

Now that property_type is derived from the county's state class
(pipeline/property_type.py), a book seeded before that derivation existed —
or seeded while SEED_PROPERTY_TYPES was "*" — holds condos and apartment
buildings that config.SEED_PROPERTY_TYPES would refuse today. This is the
one-time cleanup for those rows; the seed filter prevents new ones.

Deliberately NOT part of /api/property-data/non-residential. That surface is
built on pipeline/residential.py, which answers "is this a home?" — a
correctness rule whose EXCLUDE tier means "structurally impossible for a
dwelling". A condo IS a home. This is a business preference, so it gets its own
reason key (`off_target_type`) and its own operator-run tool, and the two verdicts
stay tellable apart in `exclusion_reason` afterwards.

Reversible: the existing unarchive endpoints (api/routes/leads.py) clear both
`archived_at` and `exclusion_reason`, so an over-broad run is undone from the UI
with no special tooling.

DRY RUN BY DEFAULT. Nothing is written without --apply.

Usage:
    python scripts/archive_off_target_types.py                     # dry run, all accounts
    python scripts/archive_off_target_types.py --account-id 3      # dry run, one account
    python scripts/archive_off_target_types.py --apply             # write
    python scripts/archive_off_target_types.py --dsn "postgres://..." --apply

Requires DATABASE_URL (or --dsn) and applied migrations.
"""
import argparse
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DATABASE_URL, SEED_PROPERTY_TYPES  # noqa: E402
from pipeline.property_type import sql_type_allowlist  # noqa: E402

REASON = "off_target_type"

# Bounded like the account-delete path (CLAUDE.md): statement_timeout caps a
# STATEMENT, not a transaction, so each UPDATE's cost stays proportional to the
# batch rather than to the account. properties has nineteen child tables, but an
# archive is an UPDATE, not a DELETE — no cascade fires, so this is only about
# keeping one statement's row count sane on a large book.
BATCH = 5000


def _where(allow_sql: str, account_id: int | None) -> tuple[str, list]:
    """Rows to archive: typed, off-allowlist, not already archived."""
    # NOT(allowlist) rather than a NOT IN list: sql_type_allowlist keeps NULL,
    # and negating it is what makes "unknown type" fall on the KEEP side here
    # too. A NULL type must never be archived by this tool — it means the county
    # mirror has no state_class for that parcel, not that the row is a condo.
    where = f"property_type IS NOT NULL AND NOT {allow_sql} AND archived_at IS NULL"
    params: list = []
    if account_id is not None:
        where += " AND account_id = %s"
        params.append(account_id)
    return where, params


def preview(cur, where: str, params: list) -> list[tuple[str, int]]:
    cur.execute(
        f"SELECT property_type, COUNT(*) FROM properties WHERE {where} "
        f"GROUP BY 1 ORDER BY 2 DESC",
        params,
    )
    return cur.fetchall()


def archive(cur, where: str, params: list) -> int:
    total = 0
    while True:
        cur.execute(
            f"""
            UPDATE properties SET
                archived_at = NOW(),
                exclusion_reason = %s,
                -- Release the paid-budget slot immediately, exactly as
                -- pipeline/property_audit.archive does: a row that stays
                -- selected keeps its enrichment slot until the next selection
                -- pass and would still be billed.
                enrichment_selected = FALSE
            WHERE id IN (
                SELECT id FROM properties WHERE {where} ORDER BY id LIMIT {BATCH}
            )
            """,
            [REASON] + params,
        )
        n = cur.rowcount
        total += n
        if n == 0:
            return total
        print(f"  archived {total:,} ...")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", default=DATABASE_URL)
    ap.add_argument("--account-id", type=int, default=None,
                    help="limit to one account (default: every account)")
    ap.add_argument("--apply", action="store_true",
                    help="actually write; without it this is a dry run")
    args = ap.parse_args()

    allow_sql = sql_type_allowlist("property_type", SEED_PROPERTY_TYPES)
    if not allow_sql:
        sys.exit("SEED_PROPERTY_TYPES is '*' or empty — every type is wanted, so "
                 "there is nothing to archive. Narrow it first (see config.py).")

    print(f"Keeping: {', '.join(sorted(SEED_PROPERTY_TYPES))}")
    print("Keeping rows with a NULL property_type (county mirror has no state_class "
          "for them).\n")

    where, params = _where(allow_sql, args.account_id)
    conn = psycopg2.connect(args.dsn)
    try:
        with conn.cursor() as cur:
            rows = preview(cur, where, params)
            if not rows:
                print("Nothing to archive.")
                return
            total = sum(n for _, n in rows)
            for ptype, n in rows:
                print(f"  {ptype:16} {n:>9,}")
            print(f"  {'TOTAL':16} {total:>9,}\n")

            if not args.apply:
                print("Dry run — nothing written. Re-run with --apply to archive.")
                return
            done = archive(cur, where, params)
        conn.commit()
        print(f"\nArchived {done:,} lead(s), exclusion_reason='{REASON}'.")
        print("Reversible: unarchive from the lead list clears both columns.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
