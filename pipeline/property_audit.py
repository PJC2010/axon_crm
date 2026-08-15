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

from pipeline.residential import (
    ALL_REASONS, EXCLUDE, EXCLUDE_REASONS, REASON_LABELS, REASON_TIERS,
    sql_non_residential, sql_reason,
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
# rule reads it. A rep who moved a lead off `new`, or took ownership of it, has
# made a judgment the classifier does not get to overrule in bulk — and the
# classifier can be wrong about a real customer whose surname happens to be
# Church, or whose address was typed without a house number. Those rows are
# still reported by the audit (as `protected`), and can still be archived one at
# a time through the existing per-lead endpoint.
UNWORKED_ONLY_SQL = "status = 'new' AND assigned_to IS NULL"

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
          sample_limit: int = SAMPLE_LIMIT) -> dict:
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
    # single scan, rather than a query per reason. FILTER (WHERE …) keeps each
    # count independent while sharing the scan.
    reason_counts = ",\n            ".join(
        f"COUNT(*) FILTER (WHERE {sql_reason(r)}) AS n_{r}" for r in ALL_REASONS
    )
    any_excl = sql_non_residential(tier=EXCLUDE)
    any_reason = sql_non_residential(tier=None)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS properties,
                COUNT(*) FILTER (WHERE {any_reason}) AS flagged,
                COUNT(*) FILTER (WHERE {any_excl})   AS excludable,
                {reason_counts}
            FROM properties
            WHERE {scope_sql}
            """,
            scope_params,
        )
        totals = cur.fetchone() or {}

        # Examples, worst first: a row tripping several reasons is the most
        # clear-cut, and the highest-scoring ones are the leads actively wasting
        # a rep's time.
        reason_score = " + ".join(
            f"(CASE WHEN {sql_reason(r)} THEN 1 ELSE 0 END)" for r in EXCLUDE_REASONS
        )
        cols = ", ".join(_SAMPLE_COLS)
        cur.execute(
            f"""
            SELECT {cols},
                   {reason_score} AS reason_count
            FROM properties
            WHERE {scope_sql} AND {any_reason}
            ORDER BY reason_count DESC, lead_score DESC NULLS LAST, id
            LIMIT %s
            """,
            scope_params + [max(0, int(sample_limit))],
        )
        samples = [dict(r) for r in cur.fetchall()]

        # Per-ZIP breakdown, so an operator can see whether one bad ZIP seed is
        # responsible rather than the problem being spread evenly.
        cur.execute(
            f"""
            SELECT zip,
                   COUNT(*) AS properties,
                   COUNT(*) FILTER (WHERE {any_excl}) AS excludable
            FROM properties
            WHERE {scope_sql}
            GROUP BY zip
            HAVING COUNT(*) FILTER (WHERE {any_excl}) > 0
            ORDER BY excludable DESC, zip
            """,
            scope_params,
        )
        by_zip = [dict(r) for r in cur.fetchall()]

        # What this is actually costing. `gap_clause` is the same predicate
        # fetch_missing_any uses to build the paid candidate pool, so these are
        # excludable rows a vendor would be asked about — and billed for — on
        # the next run. Reported as a count rather than a currency amount
        # because per-lookup pricing is a contract term, not something the code
        # knows.
        from pipeline.backfill import _gap_clause
        cur.execute(
            f"""
            SELECT COUNT(*) AS billable
            FROM properties
            WHERE {scope_sql} AND {any_excl} AND {_gap_clause()}
            """,
            scope_params,
        )
        billable = (cur.fetchone() or {}).get("billable") or 0

        # Excludable rows a human has already worked, which archive() will not
        # touch. Reported so `excludable` and `archived_count` reconcile rather
        # than looking like the cleanup silently under-ran.
        cur.execute(
            f"""
            SELECT COUNT(*) AS n FROM properties
            WHERE {scope_sql} AND {any_excl} AND NOT ({UNWORKED_ONLY_SQL})
            """,
            scope_params,
        )
        protected = (cur.fetchone() or {}).get("n") or 0

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
        "by_zip": by_zip,
        # Excludable rows still in the paid candidate pool — vendor calls the
        # next run would spend on parcels nobody lives at.
        "spend_at_risk": {"billable_rows": int(billable)},
        # Excludable, but a rep has worked it — archive() leaves these alone.
        "protected": int(protected),
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
    picked = list(reasons) if reasons else list(EXCLUDE_REASONS)
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
    predicate = ("(" + " OR ".join(sql_reason(r) for r in picked) + ")"
                 + f" AND {UNWORKED_ONLY_SQL}")

    if dry_run:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM properties WHERE {scope_sql} AND {predicate}",
                scope_params,
            )
            n = cur.fetchone()[0]
        return {"archived_count": 0, "would_archive": int(n),
                "reasons": picked, "dry_run": True, "zip": zip_code}

    # The deciding reason is recomputed per row in SQL rather than carried over
    # from the audit's sample, so a row that changed since the audit ran is
    # stamped with what is true of it now. `picked` is ordered by REASON_TIERS,
    # so the CASE arms fall through most- to least-decisive and the stored reason
    # is the best single explanation for a human.
    ordered = [r for r in ALL_REASONS if r in picked]
    arms = "\n                    ".join(
        f"WHEN {sql_reason(r)} THEN '{r}'" for r in ordered
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
            WHERE {scope_sql} AND {predicate}
            RETURNING id
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
