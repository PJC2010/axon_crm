"""
Account-wide property backfill and verification against RentCast.

The per-ZIP `property` step (pipeline/property.py) only ever runs inside a
pipeline run, for one ZIP, against whatever the selection step marked. That
leaves two questions it structurally cannot answer for a book of leads built up
over many runs:

  * Which fields are still NULL *across everything I own*, and what would it
    cost to fill them?
  * Is what I already stored still correct?

This module answers both.

``audit`` is free — pure SQL, no API calls. It reports per-field fill rates for
the whole account (or one ZIP), and how many rows a sweep would actually spend
money on, so the bill is knowable before it is incurred.

``sweep`` is the paid half. It walks every property with a gap, asks RentCast
once per property, and applies the result under pipeline/reconcile.py's policy:

  fill mode (default)   Writes only into NULLs. Values already stored are
                        compared and any disagreement is recorded in
                        property_field_audits — never overwritten.
  refresh mode          Additionally overwrites the fields that legitimately
                        move (market estimate, latest sale, owner-occupancy).

Cost discipline matches the rest of the pipeline:

  * every run is capped (PROPERTY_BACKFILL_MAX, or an explicit `limit`)
  * candidates come from fetch_missing_any, so a row is queued only when it has
    a genuine gap
  * the enrichment_flags.rentcast_checked stamp bounds re-asking: a field
    RentCast structurally cannot fill (sale price in a non-disclosure state like
    Texas) would otherwise keep its row eligible forever and re-bill it on every
    run. Verification re-checks are gated the same way, via PROPERTY_RECHECK_DAYS.
  * `dry_run=True` plans the whole sweep and spends nothing

CLI: ``python -m pipeline.backfill --account-id 1 --audit``
"""
import argparse
import logging
import time
from datetime import date

import psycopg2.extras

from config import (
    PROPERTY_BACKFILL_DELAY, PROPERTY_BACKFILL_MAX, PROPERTY_RECHECK_DAYS,
    RENTCAST_API_KEY, SOURCE_FIELDS,
)
from pipeline.addr import sql_has_situs
from pipeline.coverage import TRACKED_FIELDS, rates_from_counts
from pipeline.db import ALL_COLS, fetch_missing_any, get_conn, upsert_properties
from pipeline.equity import EQUITY_SOURCE_FLAG
from pipeline.reconcile import (
    equity_provenance,
    FILL, MISMATCH, REPORTED_FIELDS, reconcile, verify_record,
)

log = logging.getLogger(__name__)

SOURCE = "rentcast"

# The enrichment_flags key stamping the day this row was last asked about.
CHECKED_FLAG = f"{SOURCE}_checked"

# Which NULLs make a row worth a paid lookup. A row missing only `subdivision`
# does not earn a call, but subdivision gets filled for free when some other gap
# earns one.
CANDIDATE_FIELDS = SOURCE_FIELDS.get(SOURCE, [])

# Columns whose fill rate the audit reports.
_TRACKED = list(TRACKED_FIELDS)

# What may appear in the audit trail: every field-level verdict, plus `address`.
# The address entry is a different kind of finding — not "two sources disagree
# about this house" but "the vendor answered about a different house" — and it
# belongs in the same report because it is the one an operator most needs to see.
ADDRESS_FIELD = "address"
AUDITED_FIELDS = [ADDRESS_FIELD, *REPORTED_FIELDS]


def _guard_columns() -> None:
    """Fail at import if any column name reaching SQL is not an allowlisted one.

    The audit builds `COUNT(col)` and `col IS NULL` fragments by interpolation —
    these lists are the only thing standing between that and injection, so a
    typo or a future rename must break loudly here rather than silently produce
    a query that does something else.
    """
    unknown = sorted(set(_TRACKED + CANDIDATE_FIELDS) - set(ALL_COLS))
    if unknown:
        raise ValueError(f"backfill: columns not in the upsert allowlist: {unknown}")


_guard_columns()


def audit(conn, account_id: int, *, zip_code: str | None = None,
          recheck_days: int | None = None) -> dict:
    """Free, read-only report on this account's property data.

    No API calls and nothing written — safe to run any time, including from a
    UI page load. Returns::

        {
          "properties":  int,                      # rows in scope
          "fields":      {field: {filled, total, pct}},
          "worst":       [(field, pct), …],        # 10 weakest columns
          "rentcast": {
            "gap_rows":     int,   # rows with at least one fillable NULL
            "eligible":     int,   # …of those, not asked within the window
            "recently_checked": int,
            "recheck_days": int,
            "configured":   bool,  # is an API key present at all
          },
          "by_zip":      [{zip, properties, gap_rows}, …],
          "discrepancies": {"open": int, "by_field": {field: int}},
        }

    `eligible` is the number that would actually be billed on the next sweep;
    `gap_rows` is the standing backlog including rows in their cooldown window.
    """
    recheck_days = PROPERTY_RECHECK_DAYS if recheck_days is None else recheck_days
    scope_sql, scope_params = _scope(account_id, zip_code)
    gap_sql = _gap_clause()
    due_sql, due_params = _due_clause(recheck_days)

    # Counted in SQL, not in Python: an account can hold hundreds of thousands of
    # properties and this runs behind a UI page load. COUNT(col) skips NULLs, so
    # one aggregate pass yields every field's fill rate in constant memory.
    count_cols = ", ".join(f"COUNT({f}) AS {f}" for f in _TRACKED)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT COUNT(*) AS total, {count_cols}, "
            f"       COUNT(*) FILTER (WHERE {gap_sql}) AS gap_rows, "
            f"       COUNT(*) FILTER (WHERE {gap_sql} AND {due_sql}) AS eligible "
            f"FROM properties {scope_sql}",
            # Positional params bind in the order their placeholders appear in
            # the statement: the FILTER clause sits in the SELECT list, so the
            # cooldown params come before the WHERE's scope params.
            due_params + scope_params,
        )
        totals = dict(cur.fetchone())

        cur.execute(
            f"SELECT COALESCE(zip, '(none)') AS zip, COUNT(*) AS properties, "
            f"       COUNT(*) FILTER (WHERE {gap_sql}) AS gap_rows "
            f"FROM properties {scope_sql} "
            f"GROUP BY 1 ORDER BY gap_rows DESC, properties DESC",
            scope_params,
        )
        by_zip = [dict(r) for r in cur.fetchall()]

    total = totals["total"]
    fields = rates_from_counts(total, {f: totals[f] for f in _TRACKED})
    worst = sorted(((f, r["pct"]) for f, r in fields.items()), key=lambda kv: kv[1])[:10]

    return {
        "properties": total,
        "fields": fields,
        "worst": worst,
        "rentcast": {
            "gap_rows": totals["gap_rows"],
            "eligible": totals["eligible"],
            "recently_checked": totals["gap_rows"] - totals["eligible"],
            "recheck_days": recheck_days,
            "configured": bool(RENTCAST_API_KEY),
        },
        "by_zip": by_zip,
        "discrepancies": discrepancy_summary(conn, account_id, zip_code=zip_code),
    }


def sweep(conn, account_id: int, *, zip_code: str | None = None,
          limit: int | None = None, mode: str = "fill", dry_run: bool = False,
          recheck_days: int | None = None, should_stop=None) -> dict:
    """Fill (and optionally re-verify) this account's property data via RentCast.

    One lookup per property, applied under the reconcile policy. Returns a
    counter dict::

        {"candidates", "queried", "matched", "unanswered", "address_mismatch",
         "rows_updated", "fields_filled", "fields_refreshed", "mismatches",
         "dry_run", "mode", "skipped_no_key", "cancelled",
         "by_field": {field: {"filled", "mismatched"}}}

    `queried` counts properties RentCast answered for — billed whether or not it
    had a match. `unanswered` counts lookups that never got through at all; those
    rows are left unstamped and stay eligible for the next run.
    `address_mismatch` counts answers that described a different property; those
    records are rejected rather than written, and each one is recorded in
    property_field_audits under the `address` field.

    `should_stop` is an optional zero-arg predicate polled between properties, so
    a UI-triggered sweep can be cancelled without losing what it already paid for.

    Under `dry_run` nothing is queried or written: `candidates` and `by_field`
    are populated from the standing gaps — the ceiling on what a real sweep
    could fill — and every other counter stays zero.
    """
    if mode not in ("fill", "refresh"):
        raise ValueError(f"mode must be 'fill' or 'refresh', got {mode!r}")

    limit = PROPERTY_BACKFILL_MAX if limit is None else limit
    recheck_days = PROPERTY_RECHECK_DAYS if recheck_days is None else recheck_days
    counter = {
        "candidates": 0, "queried": 0, "matched": 0, "unanswered": 0,
        "address_mismatch": 0, "rows_updated": 0, "fields_filled": 0,
        "fields_refreshed": 0, "mismatches": 0, "dry_run": dry_run,
        "mode": mode, "skipped_no_key": False, "cancelled": False,
        "by_field": {},
    }

    if not RENTCAST_API_KEY:
        counter["skipped_no_key"] = True
        log.warning("RENTCAST_API_KEY not set — property backfill skipped.")
        return counter
    if limit <= 0:
        return counter

    # Capped and ordered in SQL (emptiest rows first, so a bounded budget buys
    # the most data per call) rather than by pulling the whole book into memory.
    rows = fetch_missing_any(conn, CANDIDATE_FIELDS, account_id, zip_code,
                             checked_flag=CHECKED_FLAG, recheck_days=recheck_days,
                             limit=limit)
    counter["candidates"] = len(rows)
    if not rows:
        return counter

    log.info("Property backfill: %d propert%s (mode=%s%s)", len(rows),
             "y" if len(rows) == 1 else "ies", mode, ", dry run" if dry_run else "")

    from pipeline.property_provider import get_provider
    provider = get_provider(SOURCE)
    today = date.today().isoformat()
    updates: list[dict] = []
    findings: list[tuple[int, dict]] = []

    for row in rows:
        if should_stop is not None and should_stop():
            counter["cancelled"] = True
            log.info("Property backfill cancelled after %d of %d",
                     counter["queried"], len(rows))
            break

        if dry_run:
            # Plan only — spend nothing. Nobody has been asked anything, so the
            # per-field breakdown is the standing gap: an upper bound on what a
            # real sweep could fill, not a prediction that it will.
            for field in _gaps(row):
                bucket = counter["by_field"].setdefault(
                    field, {"filled": 0, "mismatched": 0})
                bucket["filled"] += 1
            continue

        record, answered = provider.get_by_address_result(
            row["address"], row.get("zip"), row.get("state"))
        if not answered:
            # The lookup never got through (timeout, outage). Leave the row
            # unstamped so it stays eligible — stamping here would let one bad
            # afternoon disqualify a whole batch from being retried for
            # PROPERTY_RECHECK_DAYS.
            counter["unanswered"] += 1
            time.sleep(PROPERTY_BACKFILL_DELAY)
            continue

        # Stamp every row the vendor did answer for, match or not. Without this a
        # field RentCast structurally cannot supply keeps the row eligible on
        # every future run, re-billing the same address forever.
        update = {"address": row["address"], "zip": row["zip"],
                  "enrichment_flags": {CHECKED_FLAG: today}}
        if not record:
            counter["queried"] += 1
            updates.append(update)
            time.sleep(PROPERTY_BACKFILL_DELAY)
            continue

        counter["queried"] += 1

        # RentCast resolves the address string itself, so confirm it answered
        # about this property before writing anything. A rejection is recorded
        # like any other finding: it is the single most useful thing in the
        # report, because it says a lead's data may already be a stranger's.
        wrong = verify_record(record, row["address"])
        if wrong:
            counter["address_mismatch"] += 1
            log.warning("RentCast answered %r for %r — record rejected.",
                        wrong, row["address"])
            findings.append((row["id"], {
                "field": "address", "stored": row["address"], "remote": wrong,
                "verdict": MISMATCH, "resolution": "kept",
            }))
            updates.append(update)
            time.sleep(PROPERTY_BACKFILL_DELAY)
            continue

        counter["matched"] += 1
        result = reconcile(row, record, mode=mode)

        # Counters follow REPORTED_FIELDS, so the headline numbers agree with the
        # discrepancy report the operator can actually open. Location noise and
        # self-drifting derived fields are still written — just not tallied.
        for finding in result["findings"]:
            if finding["field"] not in REPORTED_FIELDS:
                continue
            bucket = counter["by_field"].setdefault(
                finding["field"], {"filled": 0, "mismatched": 0})
            if finding["verdict"] == FILL:
                bucket["filled"] += 1
                counter["fields_filled"] += 1
            else:
                bucket["mismatched"] += 1
                counter["mismatches"] += 1
                if finding["resolution"] == "refreshed":
                    counter["fields_refreshed"] += 1
            findings.append((row["id"], finding))

        if result["updates"]:
            update.update(result["updates"])
            # Same marker the per-ZIP step writes, so a lead's provenance reads
            # the same however its data arrived.
            update["enrichment_flags"]["property"] = SOURCE
            equity_source = equity_provenance(row, result["updates"])
            if equity_source:
                update["enrichment_flags"][EQUITY_SOURCE_FLAG] = equity_source
        updates.append(update)
        time.sleep(PROPERTY_BACKFILL_DELAY)

    if not dry_run:
        counter["rows_updated"] = upsert_properties(conn, updates, account_id)
        record_findings(conn, account_id, findings)

    log.info("Property backfill finished: %s",
             {k: v for k, v in counter.items() if k != "by_field"})
    return counter


# ── Discrepancy trail ─────────────────────────────────────────────────────────

def record_findings(conn, account_id: int, findings: list[tuple[int, dict]],
                    source: str = SOURCE) -> int:
    """Upsert per-field findings into property_field_audits. Returns rows written.

    Keyed on (property_id, field, source) so re-checking a field replaces its
    previous verdict rather than appending — the table stays a current-state
    report, bounded by properties × fields, not an ever-growing log. `source`
    names who disagreed with the stored value (default RentCast; the HCAD
    enrichment step records its parcel disagreements under "hcad").
    """
    reportable = [(pid, f) for pid, f in findings if f["field"] in AUDITED_FIELDS]
    if not reportable:
        return 0
    values = [
        (account_id, property_id, f["field"], source,
         f["stored"], f["remote"], f["verdict"], f["resolution"])
        for property_id, f in reportable
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO property_field_audits "
            "(account_id, property_id, field, source, stored_value, remote_value, "
            " verdict, resolution) VALUES %s "
            "ON CONFLICT (property_id, field, source) DO UPDATE SET "
            "  stored_value = EXCLUDED.stored_value, "
            "  remote_value = EXCLUDED.remote_value, "
            "  verdict      = EXCLUDED.verdict, "
            "  resolution   = EXCLUDED.resolution, "
            "  checked_at   = NOW()",
            values, page_size=500,
        )
    conn.commit()
    return len(values)


def discrepancy_summary(conn, account_id: int, *, zip_code: str | None = None) -> dict:
    """Open (kept, not overwritten) disagreements for this account, by field."""
    sql = ("SELECT a.field, COUNT(*) AS n FROM property_field_audits a "
           "JOIN properties p ON p.id = a.property_id AND p.account_id = a.account_id "
           "WHERE a.account_id = %s AND a.verdict = %s AND a.resolution = 'kept'")
    params: list = [account_id, MISMATCH]
    if zip_code:
        sql += " AND p.zip = %s"
        params.append(zip_code)
    sql += " GROUP BY a.field ORDER BY n DESC"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        by_field = {field: n for field, n in cur.fetchall()}
    return {"open": sum(by_field.values()), "by_field": by_field}


def list_discrepancies(conn, account_id: int, *, field: str | None = None,
                       zip_code: str | None = None, limit: int = 100) -> list[dict]:
    """The disagreement report: what we hold vs. what RentCast says, per lead."""
    sql = ("SELECT a.id, a.property_id, a.field, a.stored_value, a.remote_value, "
           "       a.resolution, a.checked_at, p.address, p.zip, p.owner_name, "
           "       p.lead_score, p.status, p.lead_source "
           "FROM property_field_audits a "
           "JOIN properties p ON p.id = a.property_id AND p.account_id = a.account_id "
           "WHERE a.account_id = %s AND a.verdict = %s")
    params: list = [account_id, MISMATCH]
    if field:
        # Guarded against injection by the allowlist, not by quoting.
        if field not in AUDITED_FIELDS:
            raise ValueError(f"Unknown field: {field}")
        sql += " AND a.field = %s"
        params.append(field)
    if zip_code:
        sql += " AND p.zip = %s"
        params.append(zip_code)
    sql += " ORDER BY a.checked_at DESC, a.id DESC LIMIT %s"
    params.append(limit)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _scope(account_id: int, zip_code: str | None) -> tuple[str, list]:
    sql, params = "WHERE account_id = %s", [account_id]
    if zip_code:
        sql += " AND zip = %s"
        params.append(zip_code)
    return sql, params


def _gap_clause() -> str:
    """SQL for "this row has at least one field RentCast could fill".

    A parcel with no situs address (zero house number) is not a gap however
    many NULLs it carries — no address-keyed vendor can be asked about it. Nor
    is an archived row: archiving is how a bad lead is thrown away, and it has
    to stop the vendor bill as well as hiding the row.
    Excluding those here keeps the audit's gap_rows/eligible equal to the
    candidate pool fetch_missing_any hands the sweep, so the audit never
    promises lookups the sweep will not make.

    Column names are interpolated, so they are validated against the upsert
    allowlist at import time (see _TRACKED / CANDIDATE_FIELDS below) rather than
    quoted — the same guard fetch_missing_any uses.
    """
    gaps = " OR ".join(f"{f} IS NULL" for f in CANDIDATE_FIELDS)
    return (f"(({gaps}) AND {sql_has_situs('address')}"
            f" AND archived_at IS NULL)")


def _due_clause(recheck_days: int) -> tuple[str, list]:
    """SQL mirror of _due_for_check — kept beside it so the two cannot drift.

    Must match fetch_missing_any's cooldown test exactly, or the audit would
    promise a different number of lookups than the sweep goes on to make.
    """
    if recheck_days and recheck_days > 0:
        return ("(enrichment_flags->>%s IS NULL"
                " OR enrichment_flags->>%s"
                "    < to_char(NOW() - make_interval(days => %s), 'YYYY-MM-DD'))",
                [CHECKED_FLAG, CHECKED_FLAG, recheck_days])
    return "enrichment_flags->>%s IS NULL", [CHECKED_FLAG]


def _gaps(row: dict) -> list[str]:
    return [f for f in CANDIDATE_FIELDS if row.get(f) is None]


def _due_for_check(row: dict, recheck_days: int) -> bool:
    """Mirror of fetch_missing_any's cooldown test, in Python.

    Dates are compared as YYYY-MM-DD text — the same representation the SQL uses
    — which sorts chronologically and cannot fail on a malformed stored value.
    """
    stamp = (row.get("enrichment_flags") or {}).get(CHECKED_FLAG)
    if not stamp:
        return True
    if recheck_days <= 0:
        return False
    cutoff = date.fromordinal(date.today().toordinal() - recheck_days).isoformat()
    return str(stamp) < cutoff


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_audit(report: dict, account_id: int) -> None:
    rc = report["rentcast"]
    print(f"\nProperty data audit — account {account_id}, "
          f"{report['properties']} properties\n")
    print(f"  {'field':24}  {'filled':>7}  {'null':>7}  {'pct':>6}")
    print(f"  {'-' * 24}  {'-' * 7}  {'-' * 7}  {'-' * 6}")
    for field, r in sorted(report["fields"].items(), key=lambda kv: kv[1]["pct"]):
        print(f"  {field:24}  {r['filled']:>7}  {r['total'] - r['filled']:>7}  "
              f"{r['pct']:>5}%")

    print(f"\n  RentCast backlog: {rc['gap_rows']} propert"
          f"{'y' if rc['gap_rows'] == 1 else 'ies'} with a fillable gap")
    print(f"    eligible now:      {rc['eligible']}  (would be looked up on the next sweep)")
    print(f"    in cooldown:       {rc['recently_checked']}  "
          f"(asked within {rc['recheck_days']} days)")
    if not rc["configured"]:
        print("    NOTE: RENTCAST_API_KEY is not set — a sweep would do nothing.")

    disc = report["discrepancies"]
    if disc["open"]:
        print(f"\n  Open discrepancies: {disc['open']}")
        for field, n in disc["by_field"].items():
            print(f"    {field:24}  {n}")

    print("\n  Top ZIPs by backlog:")
    for bucket in report["by_zip"][:10]:
        print(f"    {bucket['zip']:>10}  {bucket['gap_rows']:>6} / {bucket['properties']}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit and backfill an account's property data via RentCast")
    ap.add_argument("--account-id", type=int, required=True, dest="account_id")
    ap.add_argument("--zip", default=None, help="Restrict to one ZIP (default: every ZIP)")
    ap.add_argument("--audit", action="store_true",
                    help="Report only — no API calls, no writes, no cost")
    ap.add_argument("--mode", choices=["fill", "refresh"], default="fill",
                    help="fill: write only into NULLs (default). "
                         "refresh: also overwrite stale market/sale values")
    ap.add_argument("--limit", type=int, default=None,
                    help=f"Cap lookups this run (default PROPERTY_BACKFILL_MAX="
                         f"{PROPERTY_BACKFILL_MAX})")
    ap.add_argument("--recheck-days", type=int, default=None, dest="recheck_days",
                    help=f"Days before an already-checked row is eligible again "
                         f"(default {PROPERTY_RECHECK_DAYS}; 0 = never re-check)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan the sweep and print what it would do, spending nothing")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s  %(message)s",
                        datefmt="%H:%M:%S")
    conn = get_conn()
    try:
        report = audit(conn, args.account_id, zip_code=args.zip,
                       recheck_days=args.recheck_days)
        _print_audit(report, args.account_id)
        if args.audit:
            return
        counter = sweep(conn, args.account_id, zip_code=args.zip, limit=args.limit,
                        mode=args.mode, dry_run=args.dry_run,
                        recheck_days=args.recheck_days)
        print(f"  Sweep: {counter}\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
