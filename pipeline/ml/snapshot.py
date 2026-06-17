"""
Point-in-time feature snapshots + outcome backfill (lead_feature_snapshots).

`write_snapshots` captures a lead's feature state the FIRST time it is scored and
never overwrites it (ON CONFLICT DO NOTHING), so the training features reflect what
was known at creation — not enrichment added after the lead converted. This is the
single most important guard against target leakage.

`backfill_outcomes` is run by the nightly retrain job: it labels snapshots from the
current pipeline status + accepted quotes / paid invoices.
"""
from __future__ import annotations

import logging
from datetime import date

import psycopg2.extras

from pipeline.ml import features, labels

log = logging.getLogger(__name__)


def write_snapshots(conn, rows: list[dict], account_id: int, vertical: str | None) -> int:
    """Insert a creation-time snapshot for each lead row (id required). Idempotent:
    keeps the earliest snapshot per property."""
    written = 0
    with conn.cursor() as cur:
        for row in rows:
            pid = row.get("id")
            if pid is None:
                continue
            payload = features.snapshot_payload(row)
            cur.execute(
                """
                INSERT INTO lead_feature_snapshots
                    (property_id, account_id, vertical, features)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (property_id) DO NOTHING
                """,
                (pid, account_id, vertical or row.get("vertical"),
                 psycopg2.extras.Json(payload)),
            )
            written += cur.rowcount
    conn.commit()
    if written:
        log.info("Captured %d new feature snapshot(s) for account %d", written, account_id)
    return written


def backfill_outcomes(
    conn, account_id: int | None = None, *, stale_open_days: int = 120,
    now: date | None = None,
) -> int:
    """Label snapshots from current lead outcomes. Returns rows updated."""
    now = now or date.today()
    where = "WHERE s.outcome IS NULL"
    params: list = []
    if account_id is not None:
        where += " AND s.account_id = %s"
        params.append(account_id)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT s.id AS snap_id, p.status, p.created_at, p.stage_moved_at,
                   p.updated_at, p.estimated_job_value,
                   (SELECT MAX(i.total) FROM invoices i
                      WHERE i.property_id = p.id AND i.status = 'paid') AS invoice_total,
                   (SELECT MAX(q.total) FROM quotes q
                      WHERE q.property_id = p.id AND q.status = 'accepted') AS quote_total,
                   EXISTS (SELECT 1 FROM invoices i
                           WHERE i.property_id = p.id AND i.status = 'paid') AS has_paid_invoice,
                   EXISTS (SELECT 1 FROM quotes q
                           WHERE q.property_id = p.id AND q.status = 'accepted') AS has_accepted_quote
            FROM lead_feature_snapshots s
            JOIN properties p ON p.id = s.property_id
            {where}
            """,
            params,
        )
        candidates = [dict(r) for r in cur.fetchall()]

    updates: list[tuple] = []
    for r in candidates:
        hint = "paid_invoice" if r["has_paid_invoice"] else (
            "accepted_quote" if r["has_accepted_quote"] else None)
        label = labels.derive_label(r, stale_open_days=stale_open_days, now=now,
                                    outcome_hint=hint)
        if label is None:
            continue
        outcome_at = labels.derive_outcome_at(r, label)
        job_value = labels.derive_job_value(r) if label == 1 else None
        updates.append((label, outcome_at, job_value, r["snap_id"]))

    if updates:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE lead_feature_snapshots "
                "SET outcome = %s, outcome_at = %s, job_value = %s WHERE id = %s",
                updates,
            )
        conn.commit()
    log.info("Backfilled outcomes for %d snapshot(s)", len(updates))
    return len(updates)
