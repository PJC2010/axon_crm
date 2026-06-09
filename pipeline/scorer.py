"""
Step 6 — Lead scoring.

Reads enriched property records and writes lead_score (0–100) + score_grade (A/B/C/D).
Pure scoring math lives in pipeline.scoring (DB-free, testable).
"""
import logging
from datetime import datetime

from config import DEFAULT_WEIGHTS, VERTICAL_WEIGHTS
from pipeline.db import get_conn, fetch_by_zip, upsert_properties
from pipeline.scoring import (
    score_property, _compute_score, _grade,
    _age_signal, _sale_signal, _equity_signal,
    _garage_signal, _income_signal, _permit_signal,
)

log = logging.getLogger(__name__)


def score_zip(zip_code: str, account_id: int, vertical: str | None = None) -> int:
    weights = VERTICAL_WEIGHTS.get(vertical, DEFAULT_WEIGHTS) if vertical else DEFAULT_WEIGHTS
    conn = get_conn()
    rows = fetch_by_zip(conn, zip_code, account_id)
    if not rows:
        conn.close()
        return 0

    updates = []
    for row in rows:
        score = _compute_score(row, weights)
        grade = _grade(score)
        updates.append({
            "address":          row["address"],
            "zip":              zip_code,
            "lead_score":       round(score, 2),
            "score_grade":      grade,
            "vertical":         vertical,
            "score_updated_at": datetime.utcnow().isoformat(),
            "enrichment_flags": {"scored": vertical or "default"},
        })

    n = upsert_properties(conn, updates, account_id)
    conn.close()
    log.info("Scored %d properties in ZIP %s (grade dist: %s)", n, zip_code,
             _grade_dist(updates))
    return n


def _grade_dist(updates: list[dict]) -> str:
    dist: dict[str, int] = {}
    for u in updates:
        g = u.get("score_grade", "?")
        dist[g] = dist.get(g, 0) + 1
    return str(dist)
