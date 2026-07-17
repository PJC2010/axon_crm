"""
Per-score lead snapshots — the scoring feedback loop's data capture.

Every scoring pass writes one lead_score_snapshots row per lead, referencing the
active scoring_model_versions row (seeded as 'v0-heuristic' in migration 0058),
with the exact raw factor values the score was computed from. Training later
joins outcome-derived labels to these frozen features — never to re-enriched
live rows — so enrichment drift can't poison the labels.

Distinct from pipeline/ml/snapshot.py (lead_feature_snapshots), which keeps only
the FIRST-score state for the legacy predictive subsystem; this table records
every pass so any model version's inputs can be reconstructed. The payload
builder (pipeline.ml.features.snapshot_payload) is shared so "which raw fields
get captured" — and the guarantee that they are PII-free (no owner names,
phones, emails, or addresses) — has a single definition.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

import psycopg2.extras

from pipeline.ml.features import snapshot_payload

log = logging.getLogger(__name__)


def get_active_model_version(conn) -> dict | None:
    """The active scoring_model_versions row, or None when no model is registered
    (migration 0058 not yet applied/seeded)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, version_tag, algorithm, coefficients, grade_bands "
            "FROM scoring_model_versions WHERE status = 'active'"
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _jsonable(value):
    """Coerce DB values snapshot_payload passes through (DATE/NUMERIC columns)
    into JSON-serializable types."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def snapshot_features(row: dict) -> dict:
    """PII-free raw factor payload for one lead row."""
    return {k: _jsonable(v) for k, v in snapshot_payload(row).items()}


def write_score_snapshots(
    conn, account_id: int, scored: list[tuple[dict, float, str]],
    model: dict | None = None,
) -> int:
    """Insert one lead_score_snapshots row per (row, score, grade) triple.

    `row` must carry the property id and the factor fields as they were scored
    (i.e. after any in-row backfill the scorer applied). Pass `model` to reuse an
    already-fetched active registry row. When no model is registered the write is
    skipped with a loud warning — scoring must keep working on a pre-migration
    database. Returns the number of snapshots written.
    """
    model = model if model is not None else get_active_model_version(conn)
    if model is None:
        log.warning(
            "No active scoring model registered — skipping %d score snapshot(s). "
            "Run db/migrate.py (migration 0058 seeds v0-heuristic).", len(scored),
        )
        return 0

    values = []
    for row, score, grade in scored:
        property_id = row.get("id")
        if property_id is None:
            continue
        values.append((
            property_id, account_id, model["id"],
            psycopg2.extras.Json(snapshot_features(row)),
            round(float(score), 4), grade,
        ))
    if not values:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO lead_score_snapshots "
            "(property_id, account_id, model_version_id, features, raw_score, grade) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            values,
        )
    conn.commit()
    log.info("Wrote %d lead score snapshot(s) for account %d (model %s)",
             len(values), account_id, model.get("version_tag"))
    return len(values)
