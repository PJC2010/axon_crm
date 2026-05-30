"""
Step 6 — Lead scoring.

Reads enriched property records and writes lead_score (0–100) + score_grade (A/B/C/D).
The scoring formula and thresholds come from config.py and can be overridden
per-vertical by passing a weights dict.
"""
import logging
from datetime import date, datetime

from config import (
    DEFAULT_WEIGHTS, VERTICAL_WEIGHTS, GRADE_BANDS,
    AGE_SWEET_SPOT_MIN, AGE_SWEET_SPOT_MAX,
    SALE_RECENCY_MAX_MO, EQUITY_TARGET,
    GARAGE_TARGET, INCOME_TARGET, PERMIT_TARGET,
)
from pipeline.db import get_conn, fetch_by_zip, upsert_properties

log = logging.getLogger(__name__)


def score_zip(zip_code: str, vertical: str | None = None) -> int:
    weights = VERTICAL_WEIGHTS.get(vertical, DEFAULT_WEIGHTS) if vertical else DEFAULT_WEIGHTS
    conn = get_conn()
    rows = fetch_by_zip(conn, zip_code)
    if not rows:
        conn.close()
        return 0

    updates = []
    for row in rows:
        score = _compute_score(row, weights)
        grade = _grade(score)
        updates.append({
            "address":         row["address"],
            "zip":             zip_code,
            "lead_score":      round(score, 2),
            "score_grade":     grade,
            "vertical":        vertical,
            "score_updated_at": datetime.utcnow().isoformat(),
            "enrichment_flags": {"scored": vertical or "default"},
        })

    n = upsert_properties(conn, updates)
    conn.close()
    log.info("Scored %d properties in ZIP %s (grade dist: %s)", n, zip_code,
             _grade_dist(updates))
    return n


def _compute_score(row: dict, weights: dict) -> float:
    return (
        weights["age"]    * _age_signal(row.get("year_built"))    +
        weights["sale"]   * _sale_signal(row.get("last_sale_date")) +
        weights["equity"] * _equity_signal(row.get("estimated_equity")) +
        weights["garage"] * _garage_signal(row.get("garage_spaces")) +
        weights["income"] * _income_signal(row.get("zip_median_income")) +
        weights["permit"] * _permit_signal(row.get("permit_count_24mo"))
    ) * 100


def _grade(score: float) -> str:
    for threshold, grade in GRADE_BANDS:
        if score >= threshold:
            return grade
    return "D"


# ── Signal functions (each returns 0.0–1.0) ───────────────────────────────────

def _age_signal(year_built: int | None) -> float:
    if not year_built:
        return 0.0
    age = date.today().year - year_built
    if AGE_SWEET_SPOT_MIN <= age <= AGE_SWEET_SPOT_MAX:
        return 1.0
    if age < AGE_SWEET_SPOT_MIN:
        return age / AGE_SWEET_SPOT_MIN
    # Older than sweet spot: decay from 30 to 50+ years
    return max(0.0, 1.0 - (age - AGE_SWEET_SPOT_MAX) / 20)


def _sale_signal(last_sale_date) -> float:
    if not last_sale_date:
        return 0.0
    try:
        if isinstance(last_sale_date, str):
            sold = date.fromisoformat(last_sale_date[:10])
        elif isinstance(last_sale_date, date):
            sold = last_sale_date
        else:
            return 0.0
        months_ago = (date.today() - sold).days / 30.44
        if months_ago >= SALE_RECENCY_MAX_MO:
            return 0.0
        return 1.0 - (months_ago / SALE_RECENCY_MAX_MO)
    except (ValueError, TypeError):
        return 0.0


def _equity_signal(equity: int | None) -> float:
    if not equity or equity <= 0:
        return 0.0
    return min(1.0, equity / EQUITY_TARGET)


def _garage_signal(spaces: int | None) -> float:
    if not spaces:
        return 0.0
    return min(1.0, spaces / GARAGE_TARGET)


def _income_signal(income: int | None) -> float:
    if not income or income <= 0:
        return 0.0
    return min(1.0, income / INCOME_TARGET)


def _permit_signal(count: int | None) -> float:
    if not count or count <= 0:
        return 0.0
    return min(1.0, count / PERMIT_TARGET)


def _grade_dist(updates: list[dict]) -> str:
    dist: dict[str, int] = {}
    for u in updates:
        g = u.get("score_grade", "?")
        dist[g] = dist.get(g, 0) + 1
    return str(dist)
