"""
Data-quality audit — free, read-only, pure SQL. No API calls, nothing written.

Answers, across every account at once:

  1. ZIP coverage — how many distinct ZIPs are seeded overall, and per account
     (plus the shared parcels cache and the raw HCAD mirror for comparison).
  2. Junk owner names — how many stored owner_name / contact_name values are
     assessor placeholders ("CURRENT OWNER") per pipeline/owner.py's list.
     These block the paid RentCast fill: only a NULL queues the row.
     Migration 0067 nulls them; this report shows the backlog before (and
     verifies zero after).
  3. owner_name fill — per account: filled, NULL-and-eligible for the next
     RentCast run, and NULL-but-stamped (waiting out PROPERTY_RECHECK_DAYS).

Usage:
    python tools/audit_data_quality.py             # whole database
    python tools/audit_data_quality.py --zip 77396 # one ZIP
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_conn                      # noqa: E402
from pipeline.owner import sql_clean_owner_name       # noqa: E402
from pipeline.addr import sql_normalize               # noqa: E402


def _rows(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _one(conn, sql: str, params=()):
    return _rows(conn, sql, params)[0]


def _exists(conn, table: str) -> bool:
    return _one(conn, "SELECT to_regclass(%s) IS NOT NULL", (table,))[0]


def _print_header(title: str):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def zip_coverage(conn, zip_code: str | None):
    _print_header("1. SEEDED ZIP COVERAGE")
    where, params = ("WHERE p.zip = %s", (zip_code,)) if zip_code else ("", ())

    # A NULL or blank zip is possible (rows imported by CSV/API without one) —
    # count those separately rather than letting them pose as a seeded ZIP.
    total_zips, total_rows, total_accounts, total_blank = _one(conn, f"""
        SELECT COUNT(DISTINCT p.zip) FILTER (WHERE TRIM(COALESCE(p.zip, '')) <> ''),
               COUNT(*), COUNT(DISTINCT p.account_id),
               COUNT(*) FILTER (WHERE TRIM(COALESCE(p.zip, '')) = '')
        FROM properties p {where}
    """, params)
    print(f"\nDistinct ZIPs seeded across ALL accounts: {total_zips}"
          f"   ({total_rows:,} property rows, {total_accounts} account(s))")
    if total_blank:
        print(f"  ⚠ {total_blank:,} row(s) have a NULL/blank zip — "
              "excluded from the ZIP count")

    print(f"\n{'account':>7}  {'name':<28} {'zips':>5} {'rows':>9} "
          f"{'no-zip':>7}  zip list")
    for acct_id, name, zips, rows, blank, zip_list in _rows(conn, f"""
        SELECT p.account_id, COALESCE(a.name, '?'),
               COUNT(DISTINCT p.zip) FILTER (WHERE TRIM(COALESCE(p.zip, '')) <> ''),
               COUNT(*),
               COUNT(*) FILTER (WHERE TRIM(COALESCE(p.zip, '')) = ''),
               ARRAY_AGG(DISTINCT p.zip ORDER BY p.zip)
                   FILTER (WHERE TRIM(COALESCE(p.zip, '')) <> '')
        FROM properties p
        LEFT JOIN accounts a ON a.id = p.account_id
        {where}
        GROUP BY p.account_id, a.name
        ORDER BY p.account_id
    """, params):
        zip_list = zip_list or []   # NULL when an account has only blank zips
        shown = ", ".join(zip_list[:8]) + (" …" if len(zip_list) > 8 else "")
        print(f"{acct_id:>7}  {name[:28]:<28} {zips:>5} {rows:>9,} "
              f"{blank:>7,}  {shown}")

    if _exists(conn, "parcels"):
        pz, pr = _one(conn, "SELECT COUNT(DISTINCT zip), COUNT(*) FROM parcels"
                            + (" WHERE zip = %s" if zip_code else ""), params)
        print(f"\nShared parcels cache: {pz} ZIP(s), {pr:,} parcels")
    if _exists(conn, "hcad_properties"):
        hz, hr = _one(conn, "SELECT COUNT(DISTINCT site_zip), COUNT(*) "
                            "FROM hcad_properties"
                            + (" WHERE site_zip = %s" if zip_code else ""), params)
        print(f"HCAD mirror (available to seed): {hz} ZIP(s), {hr:,} parcels")


def junk_owner_names(conn, zip_code: str | None):
    _print_header("2. JUNK OWNER-NAME AUDIT (placeholders that block RentCast)")
    # The guard expression itself: NULL for junk, so "cleaned IS NULL while the
    # raw value isn't" is exactly "this stored value is junk".
    targets = [
        ("properties", "owner_name", "zip"),
        ("properties", "contact_name", "zip"),
        ("parcels", "owner_name", "zip"),
        ("hcad_properties", "owner_name", "site_zip"),   # raw mirror, kept as-is
    ]
    for table, col, zcol in targets:
        if not _exists(conn, table):
            continue
        where, params = (f"WHERE {zcol} = %s", (zip_code,)) if zip_code else ("", ())
        junk_expr = sql_clean_owner_name(col)
        n, total = _one(conn, f"""
            SELECT COUNT(*) FILTER (WHERE {col} IS NOT NULL
                                      AND ({junk_expr}) IS NULL),
                   COUNT(*) FILTER (WHERE {col} IS NOT NULL)
            FROM {table} {where}
        """, params)
        pct = f"{100 * n / total:.1f}%" if total else "n/a"
        note = "  (raw county mirror — guarded at read, not rewritten)" \
            if table == "hcad_properties" else ""
        print(f"\n{table}.{col}: {n:,} junk of {total:,} non-null ({pct}){note}")
        if n:
            for value, cnt in _rows(conn, f"""
                SELECT {sql_normalize(col)}, COUNT(*)
                FROM {table} {where} {'AND' if where else 'WHERE'} {col} IS NOT NULL
                  AND ({junk_expr}) IS NULL
                GROUP BY 1 ORDER BY 2 DESC LIMIT 10
            """, params):
                print(f"    {cnt:>7,}  {value!r}")


def owner_fill(conn, zip_code: str | None):
    _print_header("3. OWNER_NAME FILL / RENTCAST ELIGIBILITY (per account)")
    where, params = ("WHERE p.zip = %s", (zip_code,)) if zip_code else ("", ())
    print(f"\n{'account':>7} {'rows':>9} {'filled':>9} {'null+eligible':>14} "
          f"{'null+stamped':>13}")
    for acct, rows, filled, eligible, stamped in _rows(conn, f"""
        SELECT p.account_id, COUNT(*),
               COUNT(*) FILTER (WHERE p.owner_name IS NOT NULL),
               COUNT(*) FILTER (WHERE p.owner_name IS NULL
                                  AND NOT COALESCE(p.enrichment_flags, '{{}}'::jsonb)
                                          ? 'rentcast_checked'),
               COUNT(*) FILTER (WHERE p.owner_name IS NULL
                                  AND COALESCE(p.enrichment_flags, '{{}}'::jsonb)
                                          ? 'rentcast_checked')
        FROM properties p {where}
        GROUP BY p.account_id ORDER BY p.account_id
    """, params):
        print(f"{acct:>7} {rows:>9,} {filled:>9,} {eligible:>14,} {stamped:>13,}")
    print("\n  null+eligible: queued on the next RentCast property/backfill run")
    print("  null+stamped:  re-eligible after PROPERTY_RECHECK_DAYS from stamp")


def main():
    ap = argparse.ArgumentParser(description="Free read-only data-quality audit.")
    ap.add_argument("--zip", dest="zip_code", help="restrict to one ZIP")
    args = ap.parse_args()

    conn = get_conn()
    try:
        zip_coverage(conn, args.zip_code)
        junk_owner_names(conn, args.zip_code)
        owner_fill(conn, args.zip_code)
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
