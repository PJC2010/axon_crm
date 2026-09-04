#!/usr/bin/env python
"""One-shot rescore of every property account, ZIP by ZIP.

Run once after deploying a scoring change that moves stored numbers without a
pipeline run — the fallback-equity provenance stamp is the case this was written
for: nothing recomputes `properties.lead_score` on deploy, so until an account's
next run (or its owner's "Update All Scores" click) the cards keep pre-change
grades and the explain panel disagrees with them.

Deliberately a script and not a migration or a scheduler job: it walks every
account's ZIPs through pipeline.scorer.score_zip, which is O(rows) of scoring
plus a snapshot write per ZIP — work that belongs outside the web process
(see the OOM note in config.py), and that an operator should start on purpose.

score_zip is called without a vertical, which keeps each lead on the vertical
it was last scored with (pipeline/scorer.py::rows_by_vertical), so this is a
refresh of the numbers and never a re-labelling. The neighborhood benchmark
is not recomputed: no scoring input changed, only how one of them is weighed.

Usage:
    python scripts/rescore_all_accounts.py                 # dry run: list the work
    python scripts/rescore_all_accounts.py --confirm       # do it
    python scripts/rescore_all_accounts.py --confirm --account-id 3
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.db import get_conn          # noqa: E402
from pipeline.scorer import score_zip     # noqa: E402

log = logging.getLogger("rescore_all_accounts")


def plan(conn, account_id: int | None) -> list[tuple[int, str, int]]:
    """(account_id, zip, live_rows) for every scored-able ZIP, largest last so a
    cancelled run has done the most accounts rather than the most rows."""
    sql = (
        "SELECT account_id, zip, COUNT(*) FROM properties "
        "WHERE zip IS NOT NULL AND archived_at IS NULL"
    )
    params: list = []
    if account_id is not None:
        sql += " AND account_id = %s"
        params.append(account_id)
    sql += " GROUP BY account_id, zip ORDER BY account_id, COUNT(*), zip"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [(int(a), str(z), int(n)) for a, z, n in cur.fetchall()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--confirm", action="store_true",
                        help="actually rescore; without it, only print the plan")
    parser.add_argument("--account-id", type=int, default=None,
                        help="limit to one account")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    conn = get_conn()
    try:
        work = plan(conn, args.account_id)
    finally:
        conn.close()

    accounts = sorted({a for a, _, _ in work})
    rows = sum(n for _, _, n in work)
    print(f"{len(work)} ZIP(s) across {len(accounts)} account(s), {rows} live row(s)")
    if not args.confirm:
        for account, zip_code, n in work:
            print(f"  account {account}  zip {zip_code}  rows {n}")
        print("Dry run — nothing rescored. Re-run with --confirm.")
        return 0

    scored = 0
    for account, zip_code, n in work:
        # score_zip opens and closes its own connection per ZIP, so a failure
        # in one ZIP cannot poison the next one's transaction.
        try:
            scored += score_zip(zip_code, account, vertical=None)
        except Exception:
            log.exception("account %s zip %s failed — continuing", account, zip_code)
    print(f"Rescored {scored} row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
