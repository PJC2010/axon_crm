"""
Non-residential lead audit and cleanup, account-wide.

`pipeline/residential.py` holds the rule (pure, no DB). This module is the half
that touches the database:

  ``audit``    Free. Pure SQL, no vendor calls, nothing written. Counts how many
               of an account's live leads do not look residential, broken down by
               reason, with real example rows so the operator can check the call
               before acting on it.
  ``archive``  Applies the audit's EXCLUDE tier by setting `archived_at`, the
               same soft-delete `POST /leads/{id}/archive` already uses.

Why archive rather than DELETE
──────────────────────────────
Deleting is both destructive and ineffective here.

Ineffective, because the rows come back. `parcels.seed_account` materializes a
tenant's rows with ``NOT EXISTS (SELECT 1 FROM properties x WHERE …address…)``
— the shared parcel cache still holds the mall, so once the tenant's row is gone
the guard passes and the next scheduled run re-inserts it (burning a fresh
customer number on the way). An archived row stays present, so `NOT EXISTS`
stays false and it is never re-created. Archiving is the durable answer; the
seed-side `residential_only` filter is what stops new ones arriving.

Destructive, because `properties.id` is the parent of notes, history, tasks,
appointments, invoices, quotes, calls and score snapshots. There is no
``DELETE FROM properties`` anywhere in production code today, and this module
does not introduce the first one.

Archived rows are excluded from the lead list, the map, the dialer queue, the
digest, workflow automation and ML training — every one of those already filters
``archived_at IS NULL`` — so archiving stops the row costing the operator time,
and `pipeline/db.py`'s paid-candidate queries stop it costing money. It stays
recoverable via the existing unarchive endpoint.

Scoping
───────
Every statement here is scoped by ``account_id``. The audit reads only
`properties` (per-tenant); it never reads or writes `parcels`, because one
tenant's judgment about what it wants to work must not alter the shared county
cache another tenant seeds from.
"""
import logging

import psycopg2.extras

from pipeline.addr import sql_normalize
from pipeline.residential import (
    ALL_REASONS, EXCLUDE, EXCLUDE_REASONS, REASON_LABELS, REASON_TIERS,
    sql_reason,
)

log = logging.getLogger(__name__)

# How many example rows the audit returns per reason. Enough to judge the rule,
# small enough that the response stays a page load.
SAMPLE_LIMIT = 10

# The archive returns ids so a caller can undo it, but the response has to stay
# a bounded HTTP payload — an account-wide cleanup can touch tens of thousands
# of rows. `ids_truncated` says when the list is partial.
_MAX_RETURNED_IDS = 1000

# A lead a human has already worked is never archived automatically, however the
# rule reads it. "Not worked" is the account's OWN first stage, looked up from
# `pipeline_stages` — the key is not always "new": business-type presets ship
# their own stage sets (an insurance account starts at "prospect",
# api/business_types.py) and every account can rename or delete stages through
# the custom-stages UI (migration 0011). Hardcoding "new" would make the archive
# silently match nothing for those accounts while the audit still offered it. A rep who moved a lead off `new`, or took ownership of it, has
# made a judgment the classifier does not get to overrule in bulk — and the
# classifier can be wrong about a real customer whose surname happens to be
# Church, or whose address was typed without a house number. Those rows are
# still reported by the audit (as `protected`), and can still be archived one at
# a time through the existing per-lead endpoint.
# Correlated on properties.account_id rather than a bind parameter, because
# these fragments are interpolated into statements whose %s ordering is fixed
# (psycopg2 binds positionally by statement text) — see parcels.seed_account for
# the same constraint.
UNWORKED_ONLY_SQL = """(
        status = COALESCE((SELECT s.key FROM pipeline_stages s
                            WHERE s.account_id = properties.account_id
                              AND s.is_default
                            ORDER BY s.sort_order LIMIT 1), 'new')
        AND assigned_to IS NULL
    )"""

# Columns shown in a sample row — the ones an operator needs to recognise a
# parcel, matching the property-signals panel on the lead page.
#
# This tuple MUST be a superset of every column residential.classify() reads,
# because each sample's `reasons` are re-derived from the projected row. Omit
# one and the row silently loses a reason the SQL counted: the audit would
# report N rows flagged for `county_class` and then show examples that do not
# mention it. That is the same Python/SQL drift tests/test_addr.py exists to
# prevent, and _guard_sample_cols below fails at import if it reappears.
_SAMPLE_COLS = (
    "id", "account_number", "address", "zip", "owner_name", "property_type",
    "state_class", "square_footage", "year_built", "estimated_value",
    "lead_score", "score_grade", "status",
    # Carried so the scoring-quota masking on this cleanup view can tell an
    # engine-seeded candidate from the tenant's own imported book (api/routes/
    # data_quality.py); not a classifier input, stripped from the API response.
    "lead_source",
)

# Columns the rule reads. Kept beside the projection it constrains.
_CLASSIFIER_INPUTS = ("address", "owner_name", "property_type",
                      "square_footage", "year_built", "state_class")


def _guard_sample_cols() -> None:
    missing = sorted(set(_CLASSIFIER_INPUTS) - set(_SAMPLE_COLS))
    if missing:
        raise ValueError(
            f"property_audit: sample projection omits classifier inputs "
            f"{missing} — sample reasons would disagree with the counts"
        )


_guard_sample_cols()


# ── Evaluating the rule at account scale ─────────────────────────────────────
# The audit and the archive run the full reason battery over every scoped row.
# Two structural rules keep that scan inside DB_STATEMENT_TIMEOUT_MS — the 30s
# request cap the account-wide audit used to blow through, returning
# QueryCanceled (a 500) to the data-quality page instead of a report:
#
#   1. owner_name is normalized ONCE per row. Without `owner_norm`, sql_reason
#      embeds the double-REGEXP_REPLACE normalization into every token/phrase
#      strpos, and Postgres does not common-subexpression-eliminate scalar
#      expressions — across the totals FILTERs that was ~440 regex evaluations
#      per row, milliseconds each thousand, minutes per account. The inner
#      subquery projects `__owner_norm` once and every fragment reads it.
#   2. Each reason is evaluated ONCE per row, as a boolean column of the
#      middle subquery; the aggregates then combine booleans instead of
#      re-deriving the battery in every FILTER clause.
#
# Both subqueries end in OFFSET 0 — the optimizer fence. Without it Postgres
# pulls the subquery up and substitutes the __owner_norm / r_* expressions
# back into each of their references, silently restoring the per-reference
# cost this structure exists to remove.

def _scoped_rows(scope_sql: str) -> str:
    """FROM-clause source: the scoped rows plus owner_name normalized once.

    Aliased back to `properties` so every fragment written against the bare
    table — sql_reason(prefix=""), _gap_clause, UNWORKED_ONLY_SQL's
    `properties.account_id` correlation — resolves unchanged.
    """
    return (f"(SELECT *, {sql_normalize('owner_name')} AS __owner_norm\n"
            f"                 FROM properties WHERE {scope_sql}\n"
            f"                 OFFSET 0) AS properties")


def _flag_cols(reasons) -> str:
    """Each reason once, as a boolean column: `<expr> AS r_<reason>`."""
    return ",\n                       ".join(
        f"{sql_reason(r, owner_norm='__owner_norm')} AS r_{r}" for r in reasons
    )


def _any(reasons) -> str:
    """Boolean OR over already-computed reason columns."""
    return "(" + " OR ".join(f"r_{r}" for r in reasons) + ")"


def _scope(account_id: int, zip_code: str | None,
           include_archived: bool = False) -> tuple[str, list]:
    """WHERE fragment + params for 'this account's live leads'.

    account_id is always bound, never interpolated. Archived rows are out of
    scope by default: they have already been dealt with, and counting them would
    make a second run of the audit report work that is already done.
    """
    where = ["account_id = %s"]
    params: list = [account_id]
    if not include_archived:
        where.append("archived_at IS NULL")
    if zip_code:
        where.append("zip = %s")
        params.append(zip_code)
    return " AND ".join(where), params


def audit(conn, account_id: int, *, zip_code: str | None = None,
          sample_limit: int = SAMPLE_LIMIT, by_zip: bool = False) -> dict:
    """Free, read-only report on non-residential rows in this account's leads.

    No vendor calls and nothing written — safe to hit on a page load, the same
    contract as pipeline/backfill.py::audit. Returns::

        {
          "properties":  int,              # live leads in scope
          "flagged":     int,              # …carrying at least one reason
          "excludable":  int,              # …carrying at least one EXCLUDE reason
          "by_reason":   {reason: {count, tier, label}},
          "samples":     [{…row…, "reasons": [...]}],
          "by_zip":      [{zip, properties, excludable}],
          "scope":       {"zip": str|None},
        }

    `excludable` is the number `archive()` would act on. It is smaller than the
    sum of `by_reason` counts, because one row usually trips several reasons at
    once — a mall is oversized *and* commercially owned *and* has no situs.
    """
    scope_sql, scope_params = _scope(account_id, zip_code)

    # One pass over the account's rows: totals and every per-reason count in a
    # single scan, rather than a query per reason. The middle subquery computes
    # each reason exactly once (see _scoped_rows above); FILTER (WHERE …) then
    # combines the booleans, keeping each count independent while sharing the
    # scan.
    reason_counts = ",\n                ".join(
        f"COUNT(*) FILTER (WHERE r_{r}) AS n_{r}" for r in ALL_REASONS
    )
    any_excl = _any(EXCLUDE_REASONS)
    any_reason = _any(ALL_REASONS)

    # The spend-at-risk and protected counts are FILTERs on the same scan
    # rather than queries of their own. No fragment here binds a parameter, so
    # scope_params is unchanged — psycopg2 binds %s positionally by statement
    # text, and a parameter in the SELECT list would bind ahead of the WHERE.
    from pipeline.backfill import _gap_clause

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS properties,
                COUNT(*) FILTER (WHERE {any_reason}) AS flagged,
                COUNT(*) FILTER (WHERE {any_excl})   AS excludable,
                COUNT(*) FILTER (WHERE {any_excl} AND has_gap) AS billable,
                COUNT(*) FILTER (WHERE {any_excl} AND NOT unworked)
                    AS protected,
                {reason_counts}
            FROM (
                SELECT {_flag_cols(ALL_REASONS)},
                       {_gap_clause()} AS has_gap,
                       {UNWORKED_ONLY_SQL} AS unworked
                FROM {_scoped_rows(scope_sql)}
                OFFSET 0
            ) flags
            """,
            scope_params,
        )
        totals = cur.fetchone() or {}

        # Examples, worst first: a row tripping several reasons is the most
        # clear-cut, and the highest-scoring ones are the leads actively wasting
        # a rep's time.
        reason_score = " + ".join(
            f"(CASE WHEN r_{r} THEN 1 ELSE 0 END)" for r in EXCLUDE_REASONS
        )
        cols = ", ".join(_SAMPLE_COLS)
        cur.execute(
            f"""
            SELECT {cols},
                   {reason_score} AS reason_count
            FROM (
                SELECT {cols},
                       {_flag_cols(ALL_REASONS)}
                FROM {_scoped_rows(scope_sql)}
                OFFSET 0
            ) flags
            WHERE {any_reason}
            ORDER BY reason_count DESC, lead_score DESC NULLS LAST, id
            LIMIT %s
            """,
            scope_params + [max(0, int(sample_limit))],
        )
        samples = [dict(r) for r in cur.fetchall()]

        # Per-ZIP breakdown: another full pass with the same heavy predicate, and
        # only the CLI report renders it — so it is opt-in rather than a cost
        # every page load pays for a field it discards.
        zip_rows: list[dict] = []
        if by_zip:
            cur.execute(
                f"""
                SELECT zip,
                       COUNT(*) AS properties,
                       COUNT(*) FILTER (WHERE {any_excl}) AS excludable
                FROM (
                    SELECT zip,
                           {_flag_cols(EXCLUDE_REASONS)}
                    FROM {_scoped_rows(scope_sql)}
                    OFFSET 0
                ) flags
                GROUP BY zip
                HAVING COUNT(*) FILTER (WHERE {any_excl}) > 0
                ORDER BY excludable DESC, zip
                """,
                scope_params,
            )
            zip_rows = [dict(r) for r in cur.fetchall()]

        # Rows a previous archive already dealt with, so a re-run shows the
        # cleanup held rather than silently reporting zero and looking like it
        # never ran.
        archived_sql, archived_params = _scope(account_id, zip_code,
                                               include_archived=True)
        cur.execute(
            f"""
            SELECT COUNT(*) AS n FROM properties
            WHERE {archived_sql} AND archived_at IS NOT NULL
              AND exclusion_reason IS NOT NULL
            """,
            archived_params,
        )
        already_archived = (cur.fetchone() or {}).get("n") or 0

    # Re-derive each sample's reasons in Python from the row we already have, so
    # the API can explain a flag without another query. classify() and the SQL
    # above are the same rule (tests/test_residential.py proves it), so this
    # cannot disagree with the counts.
    from pipeline.residential import classify
    for row in samples:
        row.pop("reason_count", None)
        row["reasons"] = classify(row)

    return {
        "properties": int(totals.get("properties") or 0),
        "flagged": int(totals.get("flagged") or 0),
        # What archive() would act on. Smaller than the sum of by_reason counts:
        # one bad row usually trips several reasons at once.
        "excludable": int(totals.get("excludable") or 0),
        "by_reason": {
            r: {
                "count": int(totals.get(f"n_{r}") or 0),
                "tier": REASON_TIERS[r],
                "label": REASON_LABELS[r],
            }
            for r in ALL_REASONS
        },
        "samples": samples,
        "by_zip": zip_rows,
        # Excludable rows still in the paid candidate pool — vendor calls the
        # next run would spend on parcels nobody lives at.
        "spend_at_risk": {"billable_rows": int(totals.get("billable") or 0)},
        # Excludable, but a rep has worked it — archive() leaves these alone.
        "protected": int(totals.get("protected") or 0),
        "already_archived": int(already_archived),
        "scope": {"zip": zip_code},
    }


def archive(conn, account_id: int, *, zip_code: str | None = None,
            reasons: list[str] | None = None, dry_run: bool = False) -> dict:
    """Archive this account's non-residential leads. Returns what it did.

    `reasons` restricts the action to specific EXCLUDE-tier reasons; the default
    is all of them. REVIEW-tier reasons are rejected rather than silently
    ignored — they exist precisely because a legitimate home can look like that,
    so acting on one has to be a deliberate, explicit request that this function
    does not currently accept.

    Leads a human has already worked (`status` moved off `new`, or an owner
    assigned) are never touched — see UNWORKED_ONLY_SQL. The audit reports those
    separately as `protected`.

    `dry_run=True` counts what would be archived and writes nothing.

    Records the deciding reason in `exclusion_reason` (migration 0072) so the
    verdict is explainable and reversible, and so a system archive can be told
    apart from one a rep performed — `archived_at` alone cannot say which.
    """
    # `is None` rather than falsiness: [] is what a checkbox UI sends when the
    # operator has deselected every reason, and on a destructive bulk endpoint
    # that must mean "nothing", never "the default set". De-duplicated because
    # each reason becomes one named column of the flags subquery — a repeated
    # reason would make that name ambiguous.
    picked = (list(EXCLUDE_REASONS) if reasons is None
              else list(dict.fromkeys(reasons)))
    if not picked:
        return {"archived_count": 0, "would_archive": 0, "reasons": [],
                "dry_run": dry_run, "zip": zip_code}
    bad = [r for r in picked if r not in REASON_TIERS]
    if bad:
        raise ValueError(f"unknown reason(s): {sorted(bad)}")
    not_excludable = [r for r in picked if REASON_TIERS[r] != EXCLUDE]
    if not_excludable:
        raise ValueError(
            f"reason(s) are review-only and cannot be archived automatically: "
            f"{sorted(not_excludable)}"
        )

    scope_sql, scope_params = _scope(account_id, zip_code)
    # Same normalize-once / evaluate-once structure as the audit (see
    # _scoped_rows above): an account-wide archive runs the battery over every
    # scoped row and would hit the same statement timeout the audit did. The
    # UPDATE joins the flags back by primary key; `flags` is already scoped, so
    # the join adds no rows the WHERE hasn't bound to this account.
    flags = (f"""(
                SELECT id,
                       {_flag_cols(picked)},
                       {UNWORKED_ONLY_SQL} AS unworked
                FROM {_scoped_rows(scope_sql)}
                OFFSET 0
            ) flags""")
    predicate = _any(picked) + " AND unworked"

    if dry_run:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM {flags} WHERE {predicate}",
                scope_params,
            )
            n = cur.fetchone()[0]
        return {"archived_count": 0, "would_archive": int(n),
                "reasons": picked, "dry_run": True, "zip": zip_code}

    # The deciding reason is recomputed in the same statement rather than
    # carried over from the audit's sample, so a row that changed since the
    # audit ran is stamped with what is true of it now. `picked` is ordered by
    # REASON_TIERS, so the CASE arms fall through most- to least-decisive and
    # the stored reason is the best single explanation for a human.
    ordered = [r for r in ALL_REASONS if r in picked]
    arms = "\n                    ".join(
        f"WHEN r_{r} THEN '{r}'" for r in ordered
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE properties SET
                archived_at = NOW(),
                exclusion_reason = CASE
                    {arms}
                END,
                -- Release the paid-budget slot immediately. The selection step
                -- marks a bounded Top-N per run for paid enrichment; a row that
                -- stays selected keeps its slot until the next selection pass,
                -- so an archive during a run would otherwise still be billed.
                enrichment_selected = FALSE
            FROM {flags}
            WHERE properties.id = flags.id AND {predicate}
            RETURNING properties.id
            """,
            scope_params,
        )
        # rowcount, not len(fetchall()): an account can hold hundreds of
        # thousands of rows and this runs in the web process, so the full id
        # list is neither returned nor materialized.
        count = cur.rowcount
        ids = [r[0] for r in cur.fetchmany(_MAX_RETURNED_IDS)]
    conn.commit()
    log.info("residential: archived %d non-residential leads for account %s "
             "(zip=%s, reasons=%s)", count, account_id, zip_code or "all", picked)
    return {"archived_count": count, "would_archive": count,
            "reasons": picked, "dry_run": False, "zip": zip_code,
            "ids": ids, "ids_truncated": count > len(ids)}


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_audit(report: dict, account_id: int) -> None:
    scope = report["scope"]["zip"] or "all ZIPs"
    print(f"\nNon-residential audit — account {account_id}, {scope}")
    print(f"  {report['properties']:,} live leads checked, "
          f"{report['flagged']:,} flagged, {report['excludable']:,} archivable\n")

    for tier, heading in ((EXCLUDE, "Safe to archive — cannot be a dwelling"),
                          ("review", "Worth a look — a real home can look like this")):
        rows = [(k, v) for k, v in report["by_reason"].items()
                if v["tier"] == tier and v["count"]]
        if not rows:
            continue
        print(f"  {heading}")
        for key, r in sorted(rows, key=lambda kv: -kv[1]["count"]):
            print(f"    {r['count']:>8,}  {key:<26} {r['label']}")
        print()
    # Rows trip several reasons at once, so the counts above do not sum to the
    # total — say so rather than letting the arithmetic look broken.
    print("  (a row usually trips several reasons, so these do not sum)\n")

    if report["protected"]:
        print(f"  {report['protected']:,} archivable lead(s) skipped — a rep has "
              f"already worked them\n")
    if report["spend_at_risk"]["billable_rows"]:
        print(f"  {report['spend_at_risk']['billable_rows']:,} flagged lead(s) "
              f"would still be billed to a data provider on the next run\n")
    if report["already_archived"]:
        print(f"  {report['already_archived']:,} previously archived by this rule\n")

    if report["by_zip"]:
        print("  Worst ZIPs:")
        for b in report["by_zip"][:10]:
            # properties.zip is nullable, so GROUP BY emits a NULL bucket —
            # f"{None:>10}" raises TypeError.
            print(f"    {(b['zip'] or '(none)'):>10}  "
                  f"{b['excludable']:>7,} / {b['properties']:,}")
        print()

    if report["samples"]:
        print("  Examples:")
        for s in report["samples"]:
            print(f"    {s['address'] or '(no address)'}, {s['zip'] or '?'}")
            bits = [s.get("owner_name")]
            if s.get("square_footage"):
                bits.append(f"{s['square_footage']:,} sqft")
            if s.get("estimated_value"):
                bits.append(f"${s['estimated_value']:,}")
            if s.get("score_grade"):
                bits.append(f"grade {s['score_grade']}")
            print(f"      {' · '.join(b for b in bits if b)}")
            print(f"      → {', '.join(s['reasons'])}")
        print()


def main() -> None:
    import argparse

    from pipeline.db import get_conn

    ap = argparse.ArgumentParser(
        description="Find and archive leads that are not homes")
    ap.add_argument("--account-id", type=int, required=True, dest="account_id")
    ap.add_argument("--zip", default=None,
                    help="Restrict to one ZIP (default: every ZIP)")
    ap.add_argument("--archive", action="store_true",
                    help="Archive the EXCLUDE-tier rows. Without this the "
                         "command only reports, and writes nothing.")
    ap.add_argument("--reasons", default=None,
                    help="Comma-separated reasons to act on (default: every "
                         f"exclude-tier reason: {','.join(EXCLUDE_REASONS)})")
    ap.add_argument("--dry-run", action="store_true",
                    help="With --archive: count what would be archived, write nothing")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s  %(message)s",
                        datefmt="%H:%M:%S")
    conn = get_conn()
    try:
        # by_zip is opt-in (an extra full scan); the CLI report renders it.
        _print_audit(audit(conn, args.account_id, zip_code=args.zip,
                           by_zip=True),
                     args.account_id)
        if not args.archive:
            return
        reasons = ([r.strip() for r in args.reasons.split(",") if r.strip()]
                   if args.reasons else None)
        result = archive(conn, args.account_id, zip_code=args.zip,
                         reasons=reasons, dry_run=args.dry_run)
        if result["dry_run"]:
            print(f"  Would archive {result['would_archive']:,} lead(s). "
                  f"Nothing written.\n")
        else:
            print(f"  Archived {result['archived_count']:,} lead(s).\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
