"""
Step 9 — Timing-signal detection (free, runs last).

Static scores say *which* homes are good prospects; timing signals say *when*.
This step diffs time-sensitive fields against the baseline captured on the
previous run (stored under `last_seen_*` keys in enrichment_flags):

  - last_sale_date moved forward   → `just_sold`   (new owner)
  - permit_count_24mo increased    → `new_permit`  (owner actively investing)
  - last_storm_date moved forward  → `storm_event` (new storm hit this property)
  - score_grade changed bands      → `score_changed` (a lead heated up or cooled off)

Only grade-band crossings emit a score_changed event — same-band score drift
(e.g. 84 → 87, both grade B) stays silent so weekly re-scores don't ping the
owner over jitter. A lead jumping from C to A after enrichment is exactly the
"a cold lead just got hot — call it today" moment the event layer exists for.

Changes are recorded as signal_events rows (surfaced on the lead timeline),
then active `signal_event` workflow rules run so automations like
"just sold → create follow-up task" or "storm_event → create roofing task"
fire without user action. The first run for a property only sets its baseline
— no events are emitted until there is history to compare against.
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

        counts: dict = {"just_sold": 0, "new_permit": 0, "storm_event": 0,
                        "score_changed": 0, "rules_triggered": triggered}
        for e in events:
            counts[e["signal_type"]] += 1
        return counts
    finally:
        conn.close()


def _diff_and_record(conn, zip_code: str, account_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, vertical, address, last_sale_date, permit_count_24mo, "
            "       last_storm_date, lead_score, score_grade, "
            "       enrichment_flags->>'last_seen_sale_date'    AS seen_sale, "
            "       enrichment_flags->>'last_seen_permit_count' AS seen_permits, "
            "       enrichment_flags->>'last_seen_storm_date'   AS seen_storm, "
            "       enrichment_flags->>'last_seen_score'        AS seen_score, "
            "       enrichment_flags->>'last_seen_score_grade'  AS seen_grade "
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
            baseline_updates.append((psycopg2.extras.Json(flags), row["id"]))  # type: ignore[arg-type]

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
    """Pure diff: compare a property row's current sale/permit/storm values against
    the `seen_*` baseline columns and return the signal events to emit."""
    sale: date | None = row["last_sale_date"]
    permits: int | None = row["permit_count_24mo"]
    storm: date | None = row.get("last_storm_date")
    seen_sale = _parse_date(row["seen_sale"])
    seen_permits = _parse_int(row["seen_permits"])
    seen_storm = _parse_date(row.get("seen_storm"))

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

    if seen_storm and storm and storm > seen_storm:
        events.append({
            "property_id": row["id"],
            "vertical": row["vertical"],
            "signal_type": "storm_event",
            "details": {
                "summary": f"New storm detected {storm.isoformat()} (prev {seen_storm.isoformat()})",
                "prev": seen_storm.isoformat(),
                "new": storm.isoformat(),
            },
        })

    grade: str | None = row.get("score_grade")
    score = _parse_float(row.get("lead_score"))
    seen_grade = row.get("seen_grade") or None
    seen_score = _parse_float(row.get("seen_score"))
    if seen_grade and grade and grade != seen_grade:
        # Grade letters order alphabetically (A best), so string compare ranks them.
        direction = "up" if grade < seen_grade else "down"
        verb = "improved" if direction == "up" else "dropped"
        summary = f"Grade {verb} from {seen_grade} to {grade}"
        if seen_score is not None and score is not None:
            summary += f" (score {seen_score:g} → {score:g})"
        events.append({
            "property_id": row["id"],
            "vertical": row["vertical"],
            "signal_type": "score_changed",
            "details": {
                "summary": summary,
                "prev_grade": seen_grade,
                "new_grade": grade,
                "prev_score": seen_score,
                "new_score": score,
                "direction": direction,
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
    storm: date | None = row.get("last_storm_date")
    if storm is not None:
        flags["last_seen_storm_date"] = storm.isoformat()
    score = _parse_float(row.get("lead_score"))
    if row.get("score_grade") is not None:
        flags["last_seen_score_grade"] = row["score_grade"]
        if score is not None:
            flags["last_seen_score"] = score
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


def _parse_float(value) -> float | None:
    """Scores arrive as Decimal/float from the column but as text from the
    JSONB baseline — accept both, reject garbage."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
