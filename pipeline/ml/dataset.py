"""
Training-set assembly from labeled feature snapshots.

Primary source is `lead_feature_snapshots` whose `outcome` was backfilled by
snapshot.backfill_outcomes(). Each example is the point-in-time `features` payload
plus its label and an `outcome_at` timestamp used for a leakage-safe time split.

When too few real snapshots exist yet (a brand-new install), `backfill_examples()`
reconstructs *approximate* examples straight from the current `properties` rows so a
first model can be bootstrapped. These are best-effort (features reflect today's
enrichment, not creation time) and are flagged via `approx=True`.
"""
from __future__ import annotations

from datetime import date

import psycopg2.extras

from pipeline.ml import labels


def labeled_snapshots(conn, account_id: int | None = None) -> list[dict]:
    """Examples from snapshots with a non-NULL outcome.

    Returns dicts: {features, label, outcome_at, account_id, vertical}.
    `account_id=None` pools across all accounts (for the global model).
    """
    where = "WHERE outcome IS NOT NULL"
    params: list = []
    if account_id is not None:
        where += " AND account_id = %s"
        params.append(account_id)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""SELECT features, outcome, outcome_at, account_id, vertical
                FROM lead_feature_snapshots {where}""",
            params,
        )
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
    return out


def backfill_examples(
    conn, account_id: int | None = None, *, stale_open_days: int = 120,
    now: date | None = None,
) -> list[dict]:
    """Bootstrap examples from current `properties` (+ revenue joins) when snapshots
    are sparse. Labels via pipeline.ml.labels; features from the live row."""
    now = now or date.today()
    where = "WHERE p.archived_at IS NULL"
    params: list = []
    if account_id is not None:
        where += " AND p.account_id = %s"
        params.append(account_id)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT p.*,
                   EXISTS (SELECT 1 FROM invoices i
                           WHERE i.property_id = p.id AND i.status = 'paid') AS has_paid_invoice,
                   EXISTS (SELECT 1 FROM quotes q
                           WHERE q.property_id = p.id AND q.status = 'accepted') AS has_accepted_quote
            FROM properties p
            {where}
            """,
            params,
        )
        rows = cur.fetchall()

    out = []
    for r in row_dicts(rows):
        hint = None
        if r.get("has_paid_invoice"):
            hint = "paid_invoice"
        elif r.get("has_accepted_quote"):
            hint = "accepted_quote"
        label = labels.derive_label(
            r, stale_open_days=stale_open_days, now=now, outcome_hint=hint,
        )
        if label is None:
            continue
        out.append({
            "features": r,
            "label": label,
            "outcome_at": labels.derive_outcome_at(r, label),
            "account_id": r.get("account_id"),
        })
    return out


def row_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def build_dataset(
    conn, account_id: int | None = None, *, min_examples: int,
    stale_open_days: int = 120, now: date | None = None,
) -> tuple[list[dict], str]:
    """Best available labeled set for a scope.

    Prefer real snapshots; if they don't reach `min_examples` with both classes,
    fall back to property-derived backfill. Returns (examples, source_tag).
    """
    snaps = labeled_snapshots(conn, account_id)
    if _usable(snaps, min_examples):
        return snaps, "snapshots"
    backfill = backfill_examples(conn, account_id, stale_open_days=stale_open_days, now=now)
    if _usable(backfill, min_examples):
        return backfill, "backfill"
    # Return whichever is larger so the caller can report why it couldn't train.
    return (snaps if len(snaps) >= len(backfill) else backfill), "insufficient"


def _usable(examples: list[dict], min_examples: int) -> bool:
    if len(examples) < min_examples:
        return False
    labels_seen = {e["label"] for e in examples}
    return 0 in labels_seen and 1 in labels_seen
