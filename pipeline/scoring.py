"""
Pure lead-scoring math — no database dependency.

All signal functions return a normalized 0.0–1.0 float.
`score_property` is the public entry point; it returns (score, grade).
Weights and thresholds come from config.py and can be overridden per-vertical.
"""
from datetime import date

from config import (
    GRADE_BANDS,
    AGE_SWEET_SPOT_MIN, AGE_SWEET_SPOT_MAX,
    SALE_RECENCY_MAX_MO, EQUITY_TARGET,
    GARAGE_TARGET, INCOME_TARGET, PERMIT_TARGET,
    POOL_SIGNAL_VALUE, SLAB_SIGNAL_VALUE,
)


def score_property(row: dict, weights: dict) -> tuple[float, str]:
    """Compute (score 0–100, grade A–D) for a single property row."""
    score = _compute_score(row, weights)
    return score, _grade(score)


def _compute_score(row: dict, weights: dict) -> float:
    return (
        weights["age"]              * _age_signal(row.get("year_built"))          +
        weights["sale"]             * _sale_signal(row.get("last_sale_date"))     +
        weights["equity"]           * _equity_signal(row.get("estimated_equity")) +
        weights["garage"]           * _garage_signal(row.get("garage_spaces"))    +
        weights["income"]           * _income_signal(row.get("zip_median_income"))+
        weights["permit"]           * _permit_signal(row.get("permit_count_24mo"))+
        weights.get("pool", 0)      * _pool_signal(row.get("has_pool"))           +
        weights.get("slab", 0)      * _slab_signal(row.get("has_cracked_slab"))
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


def _pool_signal(has_pool: bool | None) -> float:
    """1.0 if property has a pool, else 0. Used by pool_maintenance vertical."""
    return POOL_SIGNAL_VALUE if has_pool else 0.0


def _slab_signal(has_cracked_slab: bool | None) -> float:
    """1.0 if HCAD records a cracked slab, else 0. Used by epoxy_flooring vertical."""
    return SLAB_SIGNAL_VALUE if has_cracked_slab else 0.0
