#!/usr/bin/env python3
"""Cost-aware BatchData demographics test against an ALREADY-SEEDED lead.

BatchData's Property Search bills one match per returned result, so the goal is
to never spend on a lead we don't need to. This script makes that visible:

  * It locates a real property row in your DB (by lead id, or address + zip).
  * It evaluates the SAME cost guards the pipeline's demographics step applies
    (see pipeline/demographics.enrich_demographics) and tells you whether this
    lead would trigger a billable call — or be skipped for free.
  * It is a DRY RUN by default: ZERO API calls. You only spend a lookup when you
    explicitly pass --commit.

The single most important guard: a lead that already has `owner_age` is treated
as enriched and skipped, so re-running enrichment over your book costs $0 for
everything already filled. This script demonstrates that — run it once with
--commit --write, then run it again and watch it report "WOULD SKIP, 0 cost".

Usage:
    # Dry run — no API call, just the cost verdict for a seeded lead:
    python scripts/test_batchdata_seeded.py --lead-id 42
    python scripts/test_batchdata_seeded.py --address "3723 Apple Hollow Ln" --zip 77396 --account-id 1

    # Spend exactly one lookup and print the demographics (does NOT write):
    python scripts/test_batchdata_seeded.py --lead-id 42 --commit

    # Spend one lookup AND persist the fields onto the lead:
    python scripts/test_batchdata_seeded.py --lead-id 42 --commit --write

    # Re-fetch a lead that is already enriched (overrides the skip guard — bills 1):
    python scripts/test_batchdata_seeded.py --lead-id 42 --commit --force

Requires DATABASE_URL (the seeded DB) and, for --commit, DEMO_PROVIDER=batchdata
+ DEMO_API_KEY. Exit codes: 0 success/clean dry run, 1 not found or call failed,
2 not configured.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2.extras  # noqa: E402

from pipeline.db import get_conn, upsert_properties  # noqa: E402
import pipeline.demographics as demo  # noqa: E402

# Columns BatchData's demographics provider can fill — used to show what a call
# would add and to persist only those fields on --write.
DEMO_FIELDS = [
    "owner_age", "age_range", "est_household_income", "estimated_net_worth",
    "marital_status", "occupation", "has_children", "loan_to_value",
    "senior_in_household", "refi_date", "length_of_residence_years", "life_stage",
]


def _find_lead(conn, lead_id, address, zip_code, account_id) -> dict | None:
    where, params = [], []
    if lead_id is not None:
        where.append("id = %s"); params.append(lead_id)
    if address:
        where.append("LOWER(address) = LOWER(%s)"); params.append(address)
    if zip_code:
        where.append("zip = %s"); params.append(zip_code)
    if account_id is not None:
        where.append("account_id = %s"); params.append(account_id)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM properties WHERE {' AND '.join(where)} LIMIT 2", params)
        rows = cur.fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        print("WARNING: multiple leads matched — narrow it with --account-id or --lead-id.",
              file=sys.stderr)
    return dict(rows[0])


def _evaluate_guards(row: dict, force: bool) -> tuple[bool, list[str]]:
    """Return (would_call, reasons) mirroring enrich_demographics' filters."""
    reasons = []
    would_call = True

    has_owner = bool(row.get("owner_name"))
    reasons.append(f"  owner_name present .......... {'YES (' + row['owner_name'] + ')' if has_owner else 'NO  → batch step skips (BatchData itself only needs the address)'}")
    if not has_owner:
        would_call = False

    already = row.get("owner_age") is not None
    if already and not force:
        reasons.append(f"  owner_age already set ....... YES ({row['owner_age']})  → SKIP, 0 cost (use --force to re-fetch)")
        would_call = False
    elif already and force:
        reasons.append(f"  owner_age already set ....... YES ({row['owner_age']})  → --force overrides, WILL bill 1")
    else:
        reasons.append("  owner_age already set ....... NO   → not yet enriched")

    gate = demo.DEMO_MIN_GRADE or "(none)"
    passes = demo._passes_grade(row)
    reasons.append(f"  passes grade gate ({gate}) .... {'YES' if passes else 'NO  → below DEMO_MIN_GRADE, skipped'} (grade={row.get('score_grade')})")
    if not passes:
        would_call = False

    configured = demo.DEMO_PROVIDER == "batchdata" and bool(demo.DEMO_API_KEY)
    reasons.append(f"  provider configured ......... {'batchdata' if configured else f'NO (DEMO_PROVIDER={demo.DEMO_PROVIDER!r}, key set={bool(demo.DEMO_API_KEY)})'}")

    return would_call, reasons


def main() -> int:
    ap = argparse.ArgumentParser(description="Cost-aware BatchData test on a seeded lead.")
    ap.add_argument("--lead-id", type=int, help="properties.id of the seeded lead")
    ap.add_argument("--address", help="Street address (with --zip) to locate the lead")
    ap.add_argument("--zip", dest="zip_code", help="ZIP for address lookup")
    ap.add_argument("--account-id", type=int, help="Scope the lookup to one org")
    ap.add_argument("--commit", action="store_true", help="Actually call BatchData (spends 1 match)")
    ap.add_argument("--write", action="store_true", help="With --commit, persist fields to the lead")
    ap.add_argument("--force", action="store_true", help="Re-fetch even if already enriched")
    args = ap.parse_args()

    if args.lead_id is None and not (args.address and args.zip_code):
        print("ERROR: pass --lead-id, or --address together with --zip.", file=sys.stderr)
        return 2

    conn = get_conn()
    try:
        row = _find_lead(conn, args.lead_id, args.address, args.zip_code, args.account_id)
        if not row:
            print("Lead not found. Check the id/address/zip and --account-id.", file=sys.stderr)
            return 1

        loc = f"{row.get('address')}, {row.get('city')} {row.get('state')} {row.get('zip')}"
        print(f"Seeded lead #{row['id']} — {loc} (account {row['account_id']})")
        filled = [f for f in DEMO_FIELDS if row.get(f) is not None]
        print(f"Demographic columns already populated: {len(filled)}/{len(DEMO_FIELDS)}"
              + (f"  ({', '.join(filled)})" if filled else ""))

        would_call, reasons = _evaluate_guards(row, args.force)
        print("\nCost-guard evaluation (mirrors enrich_demographics):")
        print("\n".join(reasons))

        verdict = "WOULD CALL BatchData → 1 billable match" if would_call else "WOULD SKIP → 0 cost"
        print(f"\nVerdict: {verdict}")
        print("Re-running after enrichment costs 0 — the owner_age sentinel skips filled leads.")

        if not args.commit:
            print("\nDry run — no API call made. Add --commit to spend exactly one lookup.")
            return 0

        # ── --commit path: make exactly one billable call ──────────────────────
        if not would_call and not args.force:
            print("\nNot calling: the guards above would skip this lead (no spend). "
                  "Use --force only if you intend to bill 1 match anyway.")
            return 0
        if demo.DEMO_PROVIDER != "batchdata" or not demo.DEMO_API_KEY:
            print("\nERROR: set DEMO_PROVIDER=batchdata and DEMO_API_KEY to --commit.", file=sys.stderr)
            return 2

        print("\nCalling BatchData property/search (1 billable match)…")
        data = demo._batchdata_lookup(row)
        if not data:
            print("No demographics returned (no match or call failed).")
            return 1

        print(f"Demographics found ({len(data)} fields):")
        for k in sorted(data):
            print(f"  {k:28} {data[k]}")

        if args.write:
            payload = {**data, "address": row["address"], "zip": row["zip"],
                       "enrichment_flags": {"demographics": "batchdata"}}
            n = upsert_properties(conn, [payload], row["account_id"])
            print(f"\nPersisted to lead #{row['id']} ({n} row updated). "
                  "Re-run this script to confirm it now reports SKIP / 0 cost.")
        else:
            print("\n(Not written — add --write to persist. Re-running without --write "
                  "would bill another match.)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
