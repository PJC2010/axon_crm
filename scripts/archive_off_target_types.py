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


# The tenant row's own type, else the shared cache's. Existing production rows
# have property_type NULL — it is filled by hcad_enrichment, which runs per ZIP
# per account, so waiting for it would mean re-running the pipeline over every
# ZIP in every book before a single condo could be archived. parcels.property_type
# is filled county-wide by one `tools/build_parcel_cache.py` pass, and
# properties.parcel_id already points at it, so reading through the link lets
# this act on every account at once.
#
# COALESCE order matters: the tenant's own value wins when it has one, because
# that may be RentCast's answer for a row this deployment paid to enrich.
RESOLVED = "COALESCE(p.property_type, pc.property_type)"

# Aliased in a CTE so the allowlist applies to a plain identifier — the guard in
# property_type.sql_type_allowlist validates one, and an expression would (rightly)
# be rejected.
_FROM = """
        FROM properties p
        LEFT JOIN parcels pc ON pc.id = p.parcel_id
"""


def _cte(account_id: int | None) -> tuple[str, list]:
    where = "p.archived_at IS NULL"
    params: list = []
    if account_id is not None:
        where += " AND p.account_id = %s"
        params.append(account_id)
    return (
        f"WITH resolved AS (SELECT p.id, {RESOLVED} AS dwelling_type{_FROM}"
        f"        WHERE {where})",
        params,
    )


def _target(allow_sql: str) -> str:
    """Rows to archive: type resolvable, off the allowlist.

    NOT(allowlist) rather than a NOT IN list: sql_type_allowlist keeps NULL, and
    negating it puts "unknown type" on the KEEP side here too. A row whose type
    cannot be resolved must never be archived by this tool — it means the county
    mirror has no state_class for that parcel, not that the row is a condo.
    """
    return f"dwelling_type IS NOT NULL AND NOT {allow_sql}"


def coverage(cur, account_id: int | None) -> tuple[int, int]:
    """(live rows, rows whose dwelling type is resolvable).

    Printed before anything else so an unpopulated cache reports itself instead
    of looking like a clean book. Finding nothing to archive is a real outcome
    and an empty parcels.property_type is a setup error; they must not render
    identically.
    """
    cte, params = _cte(account_id)
    cur.execute(
        f"{cte} SELECT COUNT(*), COUNT(dwelling_type) FROM resolved", params
    )
    return cur.fetchone()


def preview(cur, allow_sql: str, account_id: int | None) -> list[tuple[str, int]]:
    cte, params = _cte(account_id)
    cur.execute(
        f"{cte} SELECT dwelling_type, COUNT(*) FROM resolved "
        f"WHERE {_target(allow_sql)} GROUP BY 1 ORDER BY 2 DESC",
        params,
    )
    return cur.fetchall()


def archive(cur, allow_sql: str, account_id: int | None) -> int:
    cte, params = _cte(account_id)
    total = 0
    while True:
        cur.execute(
            f"""
            {cte}
            UPDATE properties SET
                archived_at = NOW(),
                exclusion_reason = %s,
                -- Release the paid-budget slot immediately, exactly as
                -- pipeline/property_audit.archive does: a row that stays
                -- selected keeps its enrichment slot until the next selection
                -- pass and would still be billed.
                enrichment_selected = FALSE
            WHERE id IN (
                SELECT id FROM resolved WHERE {_target(allow_sql)}
                ORDER BY id LIMIT {BATCH}
            )
            """,
            params + [REASON],
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

    conn = psycopg2.connect(args.dsn)
    try:
        with conn.cursor() as cur:
            live, typed = coverage(cur, args.account_id)
            print(f"Live leads: {live:,}   with a resolvable type: {typed:,} "
                  f"({(typed / live if live else 0):.1%})")
            if live and not typed:
                sys.exit(
                    "\nNo lead has a resolvable dwelling type — nothing could be "
                    "archived even if it should be.\nLoad state_class into the HCAD "
                    "mirror (tools/load_hcad_to_postgres.py) and fill the shared "
                    "cache\n(tools/build_parcel_cache.py) first; see "
                    "docs/RENDER_DEPLOYMENT.md."
                )
            print()

            rows = preview(cur, allow_sql, args.account_id)
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
            done = archive(cur, allow_sql, args.account_id)
        conn.commit()
        print(f"\nArchived {done:,} lead(s), exclusion_reason='{REASON}'.")
        print("Reversible: unarchive from the lead list clears both columns.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
