"""
Training-set assembly from labeled feature snapshots.

Primary source is `lead_feature_snapshots` whose `outcome` was backfilled by
snapshot.backfill_outcomes(). Each example is the point-in-time `features` payload
plus its label and an `outcome_at` timestamp used for a leakage-safe time split.

When too few real snapshots exist yet (a brand-new install), `backfill_examples()`
reconstructs *approximate* examples straight from the current `properties` rows so a
first model can be bootstrapped. These are best-effort (features reflect today's
enrichment, not creation time) and are flagged via `approx=True`.

Memory
------
Both loaders are capped by `max_rows` and neither materializes a whole table.
This matters because the nightly retrain runs *inside* the API process: an
unbounded `SELECT p.* ... fetchall()` over `properties` is several KB of Python
heap per row, so a handful of seeded ZIPs (one is ~20k rows) is enough to get the
web service OOM-killed. `backfill_examples` therefore streams through a
server-side cursor and keeps only the most recently decided `max_rows` examples,
and it projects the columns the features and labels actually read instead of
`p.*` — which also drops the two JSONB columns from every row.
"""
from __future__ import annotations

import itertools
import logging
import re
from contextlib import suppress
from datetime import date

import psycopg2.extras

from config import ML_STREAM_BATCH
from pipeline.ml import features, labels

log = logging.getLogger(__name__)

_STREAM_SEQ = itertools.count()
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

# Columns `labels.derive_*` reads, on top of the feature fields. `id` is needed by
# the correlated revenue subqueries.
_LABEL_COLS = [
    "id", "account_id", "status", "created_at", "stage_moved_at", "updated_at",
    "estimated_job_value",
]


def _backfill_columns() -> list[str]:
    """The `properties` columns the bootstrap path projects, deduped in order.

    Both inputs are code-defined constants, so this is not user input — but the
    list is interpolated into SQL, so it gets the same identifier allowlist guard
    the rest of the codebase applies to dynamic column references. A typo in
    SNAPSHOT_FIELDS should fail loudly here, not build a surprising statement.
    """
    cols = list(dict.fromkeys(_LABEL_COLS + features.SNAPSHOT_FIELDS))
    bad = [c for c in cols if not _IDENT_RE.match(c)]
    if bad:
        raise ValueError(f"unsafe column name(s) in backfill projection: {bad}")
    return cols


def _stream_cursor(conn, prefix: str):
    """Named (server-side) cursor: psycopg2 buffers a whole result set client-side
    unless the cursor is named, which is the difference between a bounded scan and
    holding every row in the process at once."""
    cur = conn.cursor(name=f"{prefix}_{next(_STREAM_SEQ)}",
                      cursor_factory=psycopg2.extras.RealDictCursor)
    cur.itersize = max(1, ML_STREAM_BATCH)
    return cur


def _trim_to_recent(examples: list[dict], max_rows: int) -> None:
    """Keep the `max_rows` most recently decided examples, in place."""
    examples.sort(key=lambda e: labels.outcome_sort_key(e.get("outcome_at")),
                  reverse=True)
    del examples[max_rows:]


def labeled_snapshots(conn, account_id: int | None = None, *,
                      max_rows: int | None = None) -> list[dict]:
    """Examples from snapshots with a non-NULL outcome.

    Returns dicts: {features, label, outcome_at, account_id, vertical}.
    `account_id=None` pools across all accounts (for the global model).
    Capped to the `max_rows` most recent outcomes; the LIMIT bounds the buffer, so
    no server-side cursor is needed here.
    """
    where = "WHERE outcome IS NOT NULL"
    params: list = []
    if account_id is not None:
        where += " AND account_id = %s"
        params.append(account_id)
    sql = f"""SELECT features, outcome, outcome_at, account_id, vertical
              FROM lead_feature_snapshots {where}
              ORDER BY outcome_at DESC NULLS LAST"""
    if max_rows:
        sql += " LIMIT %s"
        params.append(max_rows)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    out = []
    for r in rows:
        feats = dict(r["features"] or {})
        feats.setdefault("vertical", r["vertical"])
        out.append({
            "features": feats,
            "label": int(r["outcome"]),
            "outcome_at": r["outcome_at"],
            "account_id": r["account_id"],
        })
    if max_rows and len(out) >= max_rows:
        log.info("Snapshot training set capped at %d row(s) (ML_MAX_TRAINING_ROWS)",
                 max_rows)
    return out


def backfill_examples(
    conn, account_id: int | None = None, *, stale_open_days: int = 120,
    now: date | None = None, max_rows: int | None = None,
) -> list[dict]:
    """Bootstrap examples from current `properties` (+ revenue joins) when snapshots
    are sparse. Labels via pipeline.ml.labels; features from the live row.

    Streams the scan and holds at most `2 * max_rows` examples before trimming back
    to the most recently decided `max_rows`. Whether a row is labelable is decided
    in Python by `labels.derive_label` (the one definition), so the cap cannot be
    applied as a SQL LIMIT without duplicating that rule into SQL and letting the
    two drift.
    """
    now = now or date.today()
    cols = _backfill_columns()
    select_list = ", ".join(f"p.{c}" for c in cols)
    where = "WHERE p.archived_at IS NULL"
    params: list = []
    if account_id is not None:
        where += " AND p.account_id = %s"
        params.append(account_id)

    high_water = max_rows * 2 if max_rows else None
    out: list[dict] = []
    scanned = 0
    cur = _stream_cursor(conn, "ml_backfill")
    try:
        cur.execute(
            f"""
            SELECT {select_list},
                   EXISTS (SELECT 1 FROM invoices i
                           WHERE i.property_id = p.id AND i.status = 'paid') AS has_paid_invoice,
                   EXISTS (SELECT 1 FROM quotes q
                           WHERE q.property_id = p.id AND q.status = 'accepted') AS has_accepted_quote
            FROM properties p
            {where}
            """,
            params,
        )
        for r in cur:
            scanned += 1
            row = dict(r)
            hint = None
            if row.get("has_paid_invoice"):
                hint = "paid_invoice"
            elif row.get("has_accepted_quote"):
                hint = "accepted_quote"
            label = labels.derive_label(
                row, stale_open_days=stale_open_days, now=now, outcome_hint=hint,
            )
            if label is None:
                continue
            out.append({
                "features": row,
                "label": label,
                "outcome_at": labels.derive_outcome_at(row, label),
                "account_id": row.get("account_id"),
            })
            if high_water and len(out) >= high_water:
                _trim_to_recent(out, max_rows)
    finally:
        # Closing a server-side cursor issues a CLOSE, which itself fails if the
        # transaction already aborted — don't let cleanup mask the real error.
        with suppress(psycopg2.Error):
            cur.close()

    if max_rows and len(out) > max_rows:
        _trim_to_recent(out, max_rows)
    if max_rows and len(out) >= max_rows:
        log.info("Bootstrap training set capped at %d of %d scanned row(s) "
                 "(ML_MAX_TRAINING_ROWS)", max_rows, scanned)
    return out


def row_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def build_dataset(
    conn, account_id: int | None = None, *, min_examples: int,
    stale_open_days: int = 120, now: date | None = None,
    max_rows: int | None = None,
) -> tuple[list[dict], str]:
    """Best available labeled set for a scope.

    Prefer real snapshots; if they don't reach `min_examples` with both classes,
    fall back to property-derived backfill. Returns (examples, source_tag).
    `max_rows` caps each source at its most recently decided outcomes.
    """
    snaps = labeled_snapshots(conn, account_id, max_rows=max_rows)
    if _usable(snaps, min_examples):
        return snaps, "snapshots"
    backfill = backfill_examples(conn, account_id, stale_open_days=stale_open_days,
                                 now=now, max_rows=max_rows)
    if _usable(backfill, min_examples):
        return backfill, "backfill"
    # Return whichever is larger so the caller can report why it couldn't train.
    return (snaps if len(snaps) >= len(backfill) else backfill), "insufficient"


def _usable(examples: list[dict], min_examples: int) -> bool:
    if len(examples) < min_examples:
        return False
    labels_seen = {e["label"] for e in examples}
    return 0 in labels_seen and 1 in labels_seen
