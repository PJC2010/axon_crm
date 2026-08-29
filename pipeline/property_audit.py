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
# This tuple MUST remain a superset of every column residential.classify()
# reads. Samples now carry the stored verdict rather than a Python
# re-derivation (migration 0083), so a missing column no longer makes the
# reasons disagree with the counts — but it still leaves the operator looking at
# a row flagged `oversized_structure` with no square footage on screen, unable
# to check the call the panel is asking them to confirm. The guard also keeps
# tests/test_property_audit_stored.py able to re-derive a sample and compare it
# against what the sweep stored. _guard_sample_cols below fails at import.
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
# `classify` (the sweep) and `archive` run the full reason battery over every
# scoped row. `audit` no longer does — it reads the stored verdict (migration
# 0083), because keeping a per-row battery inside DB_STATEMENT_TIMEOUT_MS on a
# page load turned out not to be a fight worth continuing to win: it returned
# QueryCanceled (a 500) to the data-quality page on 2026-08-29.
#
# For the two paths that still derive it, two structural rules keep the scan
# affordable:
#
#   1. owner_name is normalized ONCE per row. Without `owner_norm`, sql_reason
#      embeds the double-REGEXP_REPLACE normalization into every token/phrase
#      strpos, and Postgres does not common-subexpression-eliminate scalar
#      expressions — ~76 evaluations per row, milliseconds each thousand,
#      minutes per account. The inner subquery projects `__owner_norm` once and
#      every fragment reads it.
#   2. Each reason is evaluated ONCE per row, as a boolean column of the
#      middle subquery (archive) or one element of the verdict array
#      (classify); the consumer then combines booleans instead of re-deriving
#      the battery in every clause that references one.
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
    """Boolean OR over already-computed reason columns (archive's flags subquery)."""
    return "(" + " OR ".join(f"r_{r}" for r in reasons) + ")"


# ── Reading the stored verdict ───────────────────────────────────────────────
# The audit's side of migration 0083. Each helper below reads
# `non_residential_reasons` and touches none of the 11,678-byte battery.
#
# NULL (never classified) is deliberately falsy throughout: `= ANY(NULL)` and
# `NULL && ARRAY[...]` are both NULL, and COUNT(*) FILTER treats NULL as false.
# An unclassified row therefore never counts as flagged. It is reported on its
# own as `unclassified` instead, because an audit that quietly calls an
# unexamined row clean is not an audit.

def _has(reason: str) -> str:
    """Does the stored verdict carry this reason?"""
    return f"'{reason}' = ANY(non_residential_reasons)"


def _has_any(reasons) -> str:
    """Does the stored verdict carry any of these? `&&` is array overlap."""
    if not reasons:
        return "(FALSE)"
    literals = ", ".join(f"'{r}'" for r in reasons)
    return f"(non_residential_reasons && ARRAY[{literals}]::text[])"


# "Classified, and tripped at least one reason." array_length is NULL for both
# an empty array and a NULL one, which is why it needs the COALESCE.
FLAGGED_SQL = "(COALESCE(array_length(non_residential_reasons, 1), 0) > 0)"
UNCLASSIFIED_SQL = "(non_residential_reasons IS NULL)"


# ── The stored verdict (migration 0083) ──────────────────────────────────────
# Everything above builds the rule as SQL. Everything here is about running it
# ONCE per row instead of once per read.
#
# The audit is a page load and the battery is 11,678 bytes evaluated per row,
# three passes deep. That combination returned QueryCanceled — a 500 — to the
# data-quality page on 2026-08-29, exactly as this module's header predicted.
# `properties.non_residential_reasons` holds the answer instead: NULL until
# classified, then the array of reasons the row trips (`{}` for a clean row).
#
# The split of labour, which is not symmetric:
#   audit()    reads the stored array. Must be fast; may be a moment stale.
#   archive()  re-evaluates the live rule in its own UPDATE. Must be right;
#              is a deliberate, owner-only action, not a page load.
# A row that changed since the last sweep is therefore stamped by archive with
# what is true of it now — a property worth keeping, and the reason archive() is
# deliberately NOT converted to read the column.


def _flag_array(prefix: str = "", owner_norm: str | None = None) -> str:
    """SQL building the reasons array for one row.

    Each reason contributes `CASE WHEN <expr> THEN '<name>' END`, which is NULL
    when the reason does not apply; ARRAY_REMOVE then drops the NULLs. A row
    tripping nothing yields `{}` — an empty array, never NULL, so "classified
    and clean" stays distinguishable from "not yet classified".
    """
    arms = ",\n                           ".join(
        f"CASE WHEN {sql_reason(r, prefix, owner_norm=owner_norm)} THEN '{r}' END"
        for r in ALL_REASONS
    )
    return f"ARRAY_REMOVE(ARRAY[\n                           {arms}\n                       ], NULL)"


def rule_hash() -> str:
    """Fingerprint of the residential rule AS DEPLOYED.

    The generated SQL folds in the token and phrase lists, the tier
    composition, and this environment's NONRESIDENTIAL_* thresholds — so an
    operator editing pipeline/residential.py, or overriding a threshold, changes
    the hash. Stamped per account in property_rule_stamps (0083); a stale stamp
    is what makes the next sweep re-derive instead of trusting the change guard,
    which would otherwise make a rule change invisible forever.

    Deliberately the same construction as parcels._rule_hash, over ALL_REASONS
    rather than the EXCLUDE tier, because the audit reports both tiers.
    """
    import hashlib

    payload = "\n".join(sql_reason(r) for r in ALL_REASONS)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def stamped_rule_hash(cur, account_id: int):
    cur.execute("SELECT rule_hash FROM property_rule_stamps WHERE account_id = %s",
                (account_id,))
    row = cur.fetchone()
    if row is None:
        return None
    # RealDictCursor in some callers, plain tuple in others.
    return row["rule_hash"] if isinstance(row, dict) else row[0]


def stamp_rule(cur, account_id: int, value: str) -> None:
    cur.execute(
        """
        INSERT INTO property_rule_stamps (account_id, rule_hash, classified_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (account_id) DO UPDATE SET
            rule_hash = EXCLUDED.rule_hash, classified_at = NOW()
        """,
        (account_id, value),
    )


def next_batch_bound(conn, account_id: int, *, zip_code: str | None = None,
                     after_id: int = 0, batch_size: int = 5000):
    """Highest `id` in the next batch of this account's rows, or None if none.

    Keyset pagination over the primary key, and the reason `classify` takes an
    id range rather than a bare LIMIT.

    A `LIMIT n` with no ordering re-reads an arbitrary — in practice, the same —
    n rows every call. Combined with classify's `IS DISTINCT FROM` change guard
    that is silently wrong on the path that matters most: after a rule change,
    batch 1 corrects some rows, batch 2 reads the same rows, finds nothing left
    to change, reports 0, and the sweep concludes it has finished an account it
    has barely started — then stamps the new rule hash over it, so nothing ever
    revisits the remainder.

    Ordering by id makes each batch disjoint and the walk terminating, at the
    cost of one cheap index-only query per batch.
    """
    scope_sql, scope_params = _scope(account_id, zip_code)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT MAX(id) FROM (
                SELECT id FROM properties
                WHERE {scope_sql} AND id > %s
                ORDER BY id LIMIT %s
            ) batch
            """,
            scope_params + [int(after_id), int(batch_size)],
        )
        row = cur.fetchone()
    if not row:
        return None
    return row["max"] if isinstance(row, dict) else row[0]


def classify(conn, account_id: int, *, zip_code: str | None = None,
             after_id: int | None = None, through_id: int | None = None,
             only_unclassified: bool = False) -> int:
    """Re-derive `non_residential_reasons` for an account. Returns rows changed.

    This is where the expensive battery runs, and the only place it runs on a
    read path's behalf. Structure mirrors parcels._classify_residential, for the
    same measured reasons:

    * owner_name is normalized ONCE per row in the inner subquery and every
      reason reads `__owner_norm`. Inline, the owner battery re-runs a double
      REGEXP_REPLACE once per token and phrase — ~76 times per row.
    * Both subqueries end in `OFFSET 0`, the optimizer fence. Without it the
      planner pulls them up and substitutes the expressions back into each
      reference, restoring exactly the cost this structure removes.
    * `IS DISTINCT FROM` keeps a re-run write-free for rows whose verdict
      stands — no dead tuples, no bloat, no index churn on a nightly sweep.
      It is also why the rule stamp exists: with no writes, nothing else would
      ever notice that the rule itself changed.

    `after_id`/`through_id` bound one batch to a half-open primary-key range,
    from `next_batch_bound`. The nightly sweep runs inside the API process
    (api/scheduler.py), so an account-wide UPDATE has to be divisible or it
    becomes the long statement this whole change is about. A range rather than a
    LIMIT because batches must be disjoint — see next_batch_bound.

    `only_unclassified=True` restricts to rows never classified — the cheap
    catch-up path, served by idx_properties_unclassified (0083).
    """
    scope_sql, scope_params = _scope(account_id, zip_code)
    params = list(scope_params)
    if only_unclassified:
        scope_sql += " AND non_residential_reasons IS NULL"
    # Appended in statement order: psycopg2 binds %s positionally by where the
    # placeholder appears in the text, and both of these sit in the inner WHERE
    # after the scope predicates.
    if after_id is not None:
        scope_sql += " AND id > %s"
        params.append(int(after_id))
    if through_id is not None:
        scope_sql += " AND id <= %s"
        params.append(int(through_id))

    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE properties SET non_residential_reasons = v.reasons
            FROM (
                SELECT src.id,
                       {_flag_array('src.', owner_norm='src.__owner_norm')}
                           AS reasons
                FROM (SELECT *, {sql_normalize('owner_name')} AS __owner_norm
                      FROM properties WHERE {scope_sql}
                      OFFSET 0) src
                OFFSET 0
            ) v
            WHERE properties.id = v.id
              AND properties.non_residential_reasons IS DISTINCT FROM v.reasons
            """,
            params,
        )
        changed = cur.rowcount
    conn.commit()
    return changed


def sweep(conn, account_id: int, *, batch_size: int = 5000,
          max_batches: int = 20) -> dict:
    """Bring one account's verdicts up to date with the live rule.

    Two cases, and they cost very differently:

    * The stamp matches the deployed rule — only rows never classified need
      work, and idx_properties_unclassified finds them without a scan. This is
      the steady state, and on a quiet account it costs one index probe.
    * The stamp is missing or stale (the rule changed) — every row must be
      re-derived, because the change guard means a re-run of an unchanged rule
      writes nothing and nothing else would ever notice the difference.

    Walks the primary key in disjoint batches (see next_batch_bound), bounded by
    `max_batches` so one tick can never run unboundedly. The remainder is picked
    up by the next tick — and crucially, the stamp is written ONLY when the walk
    reaches the end. Stamping a partial sweep would tell the next tick the rule
    change had been applied and strand every row this one did not reach.

    Returns what it did, including `complete`, so a caller can log a partial
    sweep rather than report a clean one.
    """
    current = rule_hash()
    with conn.cursor() as cur:
        stale = stamped_rule_hash(cur, account_id) != current

    changed = batches = 0
    after_id = 0
    complete = False
    for _ in range(max_batches):
        through_id = next_batch_bound(conn, account_id, after_id=after_id,
                                      batch_size=batch_size)
        if through_id is None:
            complete = True          # walked past the last row
            break
        changed += classify(conn, account_id, after_id=after_id,
                            through_id=through_id,
                            only_unclassified=not stale)
        batches += 1
        after_id = through_id

    log.info("residential: swept account %s — %d verdict(s) changed in %d "
             "batch(es), stale_rule=%s, complete=%s",
             account_id, changed, batches, stale, complete)

    if complete:
        with conn.cursor() as cur:
            stamp_rule(cur, account_id, current)
        conn.commit()

    return {"changed": changed, "batches": batches, "rule_was_stale": stale,
            "complete": complete, "rule_hash": current,
            "resume_after_id": None if complete else after_id}


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
    contract as pipeline/backfill.py::audit.

    Reads the STORED verdict (`non_residential_reasons`, migration 0083) rather
    than re-deriving the rule. Deriving it here meant 11,678 bytes of predicate
    per row across three passes, which is what returned QueryCanceled to the
    data-quality page on 2026-08-29. `classify`/`sweep` above own the derivation
    now, off the request path.

    The cost of that trade is staleness, and the report is explicit about it:
    `unclassified` counts rows the rule has not reached, and `rule_stale` says
    whether the deployed rule has changed since the last sweep. Neither is
    folded into the flagged/clean split. Returns::

        {
          "properties":  int,              # live leads in scope
          "unclassified": int,             # …the rule has not reached yet
          "rule_stale":  bool,             # deployed rule changed since the sweep
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
    # single scan, rather than a query per reason. Each count is now an array
    # membership test against the stored verdict — `'x' = ANY(reasons)` — so
    # FILTER combines nine cheap booleans over one scan instead of re-deriving
    # the rule nine times per row.
    reason_counts = ",\n                ".join(
        f"COUNT(*) FILTER (WHERE {_has(r)}) AS n_{r}" for r in ALL_REASONS
    )
    any_excl = _has_any(EXCLUDE_REASONS)
    any_reason = FLAGGED_SQL

    # The spend-at-risk and protected counts are FILTERs on the same scan
    # rather than queries of their own. No fragment here binds a parameter, so
    # scope_params is unchanged — psycopg2 binds %s positionally by statement
    # text, and a parameter in the SELECT list would bind ahead of the WHERE.
    from pipeline.backfill import _gap_clause

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Cheap, and it decides how the numbers below should be read: a stale
        # stamp means the stored verdicts were derived by a different build of
        # the rule than the one deployed now.
        rule_is_stale = stamped_rule_hash(cur, account_id) != rule_hash()

        cur.execute(
            f"""
            SELECT
                COUNT(*) AS properties,
                COUNT(*) FILTER (WHERE {UNCLASSIFIED_SQL}) AS unclassified,
                COUNT(*) FILTER (WHERE {any_reason}) AS flagged,
                COUNT(*) FILTER (WHERE {any_excl})   AS excludable,
                COUNT(*) FILTER (WHERE {any_excl} AND has_gap) AS billable,
                COUNT(*) FILTER (WHERE {any_excl} AND NOT unworked)
                    AS protected,
                {reason_counts}
            FROM (
                SELECT non_residential_reasons,
                       {_gap_clause()} AS has_gap,
                       {UNWORKED_ONLY_SQL} AS unworked
                FROM properties WHERE {scope_sql}
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
            f"(CASE WHEN {_has(r)} THEN 1 ELSE 0 END)" for r in EXCLUDE_REASONS
        )
        cols = ", ".join(_SAMPLE_COLS)
        cur.execute(
            f"""
            SELECT {cols}, non_residential_reasons,
                   {reason_score} AS reason_count
            FROM properties
            WHERE {scope_sql} AND {any_reason}
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
                FROM properties WHERE {scope_sql}
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

    # Each sample's reasons come from the same stored array the counts were
    # aggregated from, so a sample can no longer disagree with the total that
    # selected it. Previously these were re-derived in Python from the projected
    # row, which held only as long as _SAMPLE_COLS stayed a superset of every
    # column the rule reads — the drift _guard_sample_cols exists to catch.
    # Reading the column removes the opportunity for drift rather than guarding
    # against it; tests/test_property_audit_stored.py pins that the stored array
    # and residential.classify() still agree on the same row.
    for row in samples:
        row.pop("reason_count", None)
        row["reasons"] = list(row.pop("non_residential_reasons", None) or [])

    return {
        "properties": int(totals.get("properties") or 0),
        # Rows the rule has not reached yet (migration 0083 ships no backfill).
        # Reported rather than folded into either side: these are not known to
        # be clean, and a caller showing "0 flagged" beside a large
        # `unclassified` is telling the operator something different from a
        # clean account.
        "unclassified": int(totals.get("unclassified") or 0),
        # TRUE when the deployed rule has changed since this account was last
        # swept, so the stored verdicts predate it.
        "rule_stale": rule_is_stale,
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
        # Always present, so a client reads one field rather than testing for
        # the key's absence. empty_report() is the True case.
        "degraded": False,
    }


def empty_report(account_id: int, zip_code: str | None = None) -> dict:
    """The audit's shape with every figure zeroed and `degraded` set.

    Returned by the route when the audit itself times out
    (api/deps.py::soft_query), so the panel renders its own empty state instead
    of the client having to special-case a 500. Built from ALL_REASONS rather
    than written out, so a new reason cannot be missing from the degraded shape
    only — the sort of gap that shows up once, in front of an operator, on the
    day the database is already slow.
    """
    return {
        "properties": 0, "unclassified": 0, "rule_stale": False,
        "flagged": 0, "excludable": 0,
        "by_reason": {r: {"count": 0, "tier": REASON_TIERS[r],
                          "label": REASON_LABELS[r]} for r in ALL_REASONS},
        "samples": [], "by_zip": [],
        "spend_at_risk": {"billable_rows": 0},
        "protected": 0, "already_archived": 0,
        "scope": {"zip": zip_code},
        # The one field that differs from a genuine clean report: every zero
        # above means "not measured", not "none found".
        "degraded": True,
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
