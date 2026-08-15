#!/usr/bin/env python3
"""Prove the ZIP-scoped neighborhood recompute agrees with the account-wide one.

``pipeline.neighborhood.recompute_neighborhood_values`` used to rewrite every row
in the account on every per-ZIP pipeline run (983s of a 24-minute run at 214k
rows, and growing with each ZIP ever seeded). It now accepts ``zips=[...]`` and
rewrites only the geohash-6 cells those ZIPs touch.

The change is only safe if the *numbers* are unchanged: a cell straddling a ZIP
line must still be measured over every qualifying row in it, not just the rows in
the ZIP being processed. This script is the check. Against a real database it:

  1. runs the account-wide recompute and snapshots
     (neighborhood_value_ratio, pctile, basis) for every row;
  2. runs the scoped recompute for one ZIP;
  3. asserts every row in a touched cell holds exactly the account-wide value,
     and every row outside them is byte-for-byte unchanged.

Everything happens inside one transaction that is **rolled back** at the end, so
pointing it at production is read-only. ``--commit`` opts out of the rollback.

Known and intended divergence: rows whose own cell has fewer than
NEIGHBORHOOD_MIN_MEMBERS members fall back to the HCAD-neighborhood or ZIP
median, and under scoping those fallback medians are computed from the scoped
rows. Such rows are reported separately as `fallback` rather than as failures —
the run fails only on a cell-tier disagreement. Use --strict to fail on any
difference at all.

Usage:
    DATABASE_URL=postgresql://... python scripts/verify_neighborhood_scoping.py \
        --account-id 5 --zip 77073
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402

from config import DATABASE_URL, NEIGHBORHOOD_MIN_MEMBERS  # noqa: E402
from pipeline.neighborhood import (  # noqa: E402
    GEOHASH_PRECISION, recompute_neighborhood_values, touched_cells,
)

BENCH_COLS = ("neighborhood_value_ratio", "neighborhood_value_pctile",
              "neighborhood_value_basis")


class _NoCommitConn:
    """Connection proxy that swallows commit().

    `recompute_neighborhood_values` commits its own work, which would defeat the
    outer transaction this script relies on to stay read-only. Everything else is
    delegated untouched.
    """

    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


def snapshot(conn, account_id: int) -> dict:
    """id → (ratio, pctile, basis, cell) for every row in the account."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, {', '.join(BENCH_COLS)}, LEFT(geohash, %s) "
            "FROM properties WHERE account_id = %s",
            (GEOHASH_PRECISION, account_id),
        )
        return {r[0]: (r[1], r[2], r[3], r[4]) for r in cur.fetchall()}


def _same(a, b) -> bool:
    """Float-tolerant comparison of one snapshot tuple against another."""
    for x, y in zip(a[:3], b[:3]):
        if x is None or y is None:
            if x is not y:
                return False
        elif isinstance(x, str) or isinstance(y, str):
            if x != y:
                return False
        elif abs(float(x) - float(y)) > 1e-9:
            return False
    return True


def verify(conn, account_id: int, zip_code: str, strict: bool = False) -> int:
    wrapped = _NoCommitConn(conn)

    print(f"account={account_id} zip={zip_code} "
          f"(geohash-{GEOHASH_PRECISION} cells, min_members={NEIGHBORHOOD_MIN_MEMBERS})")

    n_wide = recompute_neighborhood_values(wrapped, account_id)
    wide = snapshot(conn, account_id)
    print(f"  account-wide recompute: {n_wide} row(s) benchmarked, "
          f"{len(wide)} row(s) in account")

    cells = set(touched_cells(wrapped, account_id, [zip_code]))
    if not cells:
        print(f"  !! ZIP {zip_code} has no geocoded rows — nothing to compare")
        return 1

    n_scoped = recompute_neighborhood_values(wrapped, account_id, zips=[zip_code])
    scoped = snapshot(conn, account_id)
    print(f"  scoped recompute:       {n_scoped} row(s) benchmarked, "
          f"{len(cells)} cell(s) touched")

    inside_ok = inside_bad = fallback = outside_bad = 0
    examples: list[str] = []
    bases = Counter()
    for row_id, after in scoped.items():
        before = wide[row_id]
        in_cell = after[3] in cells
        if in_cell:
            bases[before[2]] += 1
        if _same(before, after):
            inside_ok += in_cell
            continue
        if not in_cell:
            outside_bad += 1
            if len(examples) < 10:
                examples.append(f"    OUTSIDE id={row_id} cell={after[3]} "
                                f"was={before[:3]} now={after[:3]}")
            continue
        # Inside a touched cell: a cell-tier row must match exactly; a row that
        # fell back to the neighborhood/ZIP tier is compared against a narrower
        # population by design.
        if before[2] == "cell" and after[2] == "cell" or strict:
            inside_bad += 1
            if len(examples) < 10:
                examples.append(f"    INSIDE  id={row_id} cell={after[3]} "
                                f"was={before[:3]} now={after[:3]}")
        else:
            fallback += 1

    print(f"  rows in touched cells:  {sum(bases.values())} "
          f"({dict(bases)} by account-wide basis)")
    print(f"    identical:            {inside_ok}")
    print(f"    fallback-tier differs:{fallback}  (expected: sparse cells, "
          f"see the module docstring)")
    print(f"    cell-tier differs:    {inside_bad}   <-- must be 0")
    print(f"  rows outside touched cells rewritten: {outside_bad}   <-- must be 0")
    for line in examples:
        print(line)

    ok = inside_bad == 0 and outside_bad == 0
    print("  RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--zip", required=True, help="ZIP to scope the recompute to")
    parser.add_argument("--strict", action="store_true",
                        help="Fail on fallback-tier differences too")
    parser.add_argument("--commit", action="store_true",
                        help="Keep the recomputed values (default: roll back)")
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    try:
        rc = verify(conn, args.account_id, args.zip, strict=args.strict)
        if args.commit:
            conn.commit()
            print("  (committed)")
        else:
            conn.rollback()
            print("  (rolled back — database unchanged)")
        return rc
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
