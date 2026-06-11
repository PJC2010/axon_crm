"""
Step 9 — Timing-signal detection (free, runs last).

Static scores say *which* homes are good prospects; timing signals say *when*.
This step diffs time-sensitive fields against the baseline captured on the
previous run (stored under `last_seen_*` keys in enrichment_flags):

  - last_sale_date moved forward   → `just_sold`   (new owner)
  - permit_count_24mo increased    → `new_permit`  (owner actively investing)

Changes are recorded as signal_events rows (surfaced on the lead timeline),
then active `signal_event` workflow rules run so automations like
"just sold → create follow-up task" fire without user action. The first run
for a property only sets its baseline — no events are emitted until there is
history to compare against.
"""
import logging
from datetime import date

import psycopg2.extras

from pipeline.db import get_conn

log = logging.getLogger(__name__)


def detect_signals(zip_code: str, account_id: int) -> dict:
    """Detect and record timing signals for one ZIP. Returns event counts."""
    conn = get_conn()
    try:
        events = _diff_and_record(conn, zip_code, account_id)

        triggered = 0
        if events:
            from api.workflow_engine import execute_signal_event_rules
            triggered = len(execute_signal_event_rules(conn, account_id, events))

        counts: dict = {"just_sold": 0, "new_permit": 0, "rules_triggered": triggered}
        for e in events:
            counts[e["signal_type"]] += 1
        return counts
    finally:
        conn.close()


def _diff_and_record(conn, zip_code: str, account_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, vertical, address, last_sale_date, permit_count_24mo, "
            "       enrichment_flags->>'last_seen_sale_date'    AS seen_sale, "
            "       enrichment_flags->>'last_seen_permit_count' AS seen_permits "
            "FROM properties "
            "WHERE zip = %s AND account_id = %s AND archived_at IS NULL",
            (zip_code, account_id),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    events: list[dict] = []
    baseline_updates: list[tuple] = []   # (flags_json, property_id)

    for row in rows:
        events.extend(events_for_row(row))
        flags = baseline_for_row(row)
        if flags:
            baseline_updates.append((psycopg2.extras.Json(flags), row["id"]))

    with conn.cursor() as cur:
        if events:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO signal_events (property_id, account_id, signal_type, details) VALUES %s",
                [(e["property_id"], account_id, e["signal_type"], psycopg2.extras.Json(e["details"]))
                 for e in events],
            )
        if baseline_updates:
            psycopg2.extras.execute_batch(
                cur,
                "UPDATE properties SET enrichment_flags = COALESCE(enrichment_flags, '{}'::jsonb) || %s WHERE id = %s",
                baseline_updates,
            )
    conn.commit()

    if events:
        log.info("Detected %d timing signals in ZIP %s", len(events), zip_code)
    return events


def events_for_row(row: dict) -> list[dict]:
    """Pure diff: compare a property row's current sale/permit values against
    the `seen_*` baseline columns and return the signal events to emit."""
    sale: date | None = row["last_sale_date"]
    permits: int | None = row["permit_count_24mo"]
    seen_sale = _parse_date(row["seen_sale"])
    seen_permits = _parse_int(row["seen_permits"])

    events: list[dict] = []
    if seen_sale and sale and sale > seen_sale:
        events.append({
            "property_id": row["id"],
            "vertical": row["vertical"],
            "signal_type": "just_sold",
            "details": {
                "summary": f"Sold {sale.isoformat()} (was {seen_sale.isoformat()})",
                "prev": seen_sale.isoformat(),
                "new": sale.isoformat(),
            },
        })

    if seen_permits is not None and permits is not None and permits > seen_permits:
        events.append({
            "property_id": row["id"],
            "vertical": row["vertical"],
            "signal_type": "new_permit",
            "details": {
                "summary": f"Permit activity rose from {seen_permits} to {permits} (24mo)",
                "prev": seen_permits,
                "new": permits,
            },
        })
    return events


def baseline_for_row(row: dict) -> dict:
    """Pure: the `last_seen_*` flag values to persist for the next run's diff."""
    flags: dict = {}
    if row["last_sale_date"] is not None:
        flags["last_seen_sale_date"] = row["last_sale_date"].isoformat()
    if row["permit_count_24mo"] is not None:
        flags["last_seen_permit_count"] = row["permit_count_24mo"]
    return flags


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
