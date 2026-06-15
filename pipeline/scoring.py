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
    NEIGHBORHOOD_RATIO_TARGET,
    STORM_RECENCY_MAX_MO,
    REFI_RECENCY_MAX_MO, CREDIT_GRADE_SCORES,
    TENURE_TARGET_YEARS, LIFE_STAGE_SCORES,
    FACTOR_META, DEFAULT_WEIGHTS, VERTICAL_WEIGHTS,
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
        weights.get("neighborhood", 0) * _neighborhood_signal(row.get("neighborhood_value_ratio")) +
        weights.get("pool", 0)              * _pool_signal(row.get("has_pool"))                  +
        weights.get("slab", 0)              * _slab_signal(row.get("has_cracked_slab"))          +
        weights.get("storm", 0)             * _storm_signal(row.get("last_storm_date"))          +
        weights.get("home_improvement", 0)  * _home_improvement_signal(row.get("home_improvement_flag")) +
        weights.get("refi", 0)              * _refi_signal(row.get("refi_date"))                +
        weights.get("credit", 0)            * _credit_signal(row.get("credit_rating"))          +
        weights.get("children", 0)          * _children_signal(row.get("has_children"))         +
        weights.get("gardening", 0)         * _gardening_signal(row.get("gardening_flag"))      +
        weights.get("absentee", 0)          * _absentee_signal(row.get("owner_occupied"))       +
        weights.get("tenure", 0)            * _tenure_signal(row.get("ownership_years"))         +
        weights.get("life_stage", 0)        * _life_stage_signal(row.get("life_stage"))
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


def _neighborhood_signal(ratio: float | None) -> float:
    """Reward homes whose value-per-sqft is strong relative to their immediate
    neighborhood. `ratio` (precomputed in pipeline/neighborhood.py) is the home's
    value/sqft ÷ the neighborhood median; 1.0 means exactly at the median. At or
    below median scores 0; NEIGHBORHOOD_RATIO_TARGET× (or higher) scores 1.0.
    This replaces ZIP-median income as the sole locality signal with a far more
    granular one. Unbenchmarked homes (ratio None) score 0."""
    if not ratio or ratio <= 0:
        return 0.0
    return min(1.0, max(0.0, (ratio - 1.0) / (NEIGHBORHOOD_RATIO_TARGET - 1.0)))


def _pool_signal(has_pool: bool | None) -> float:
    """1.0 if property has a pool, else 0. Used by pool_maintenance vertical."""
    return POOL_SIGNAL_VALUE if has_pool else 0.0


def _slab_signal(has_cracked_slab: bool | None) -> float:
    """1.0 if HCAD records a cracked slab, else 0. Used by epoxy_flooring vertical."""
    return SLAB_SIGNAL_VALUE if has_cracked_slab else 0.0


def _storm_signal(last_storm_date) -> float:
    """Recency-weighted signal for a recent storm event (hail/wind/tornado).

    Decays linearly from 1.0 (event today) to 0.0 (event >= STORM_RECENCY_MAX_MO
    months ago). Same decay shape as _sale_signal. Used by roofing, hvac, fencing,
    and pressure_washing verticals.
    """
    if not last_storm_date:
        return 0.0
    try:
        if isinstance(last_storm_date, str):
            event_date = date.fromisoformat(last_storm_date[:10])
        elif isinstance(last_storm_date, date):
            event_date = last_storm_date
        else:
            return 0.0
        months_ago = (date.today() - event_date).days / 30.44
        if months_ago >= STORM_RECENCY_MAX_MO:
            return 0.0
        return max(0.0, 1.0 - (months_ago / STORM_RECENCY_MAX_MO))
    except (ValueError, TypeError):
        return 0.0


def _home_improvement_signal(flag: bool | None) -> float:
    """1.0 if the owner is a confirmed home-improvement buyer, else 0.

    This is a direct behavioral-intent signal from Versium lifestyle data —
    the owner already spends on home improvement, making them a pre-qualified
    prospect for all service verticals.
    """
    return 1.0 if flag else 0.0


def _refi_signal(refi_date) -> float:
    """Recency-weighted signal for a recent mortgage refinance.

    Decays linearly from 1.0 (refi today) to 0.0 (refi >= REFI_RECENCY_MAX_MO
    months ago). A recent cash-out refi signals both available capital and an
    investment mindset — strongest conversion predictor for solar, HVAC, roofing.
    """
    if not refi_date:
        return 0.0
    try:
        if isinstance(refi_date, str):
            event_date = date.fromisoformat(refi_date[:10])
        elif isinstance(refi_date, date):
            event_date = refi_date
        else:
            return 0.0
        months_ago = (date.today() - event_date).days / 30.44
        if months_ago >= REFI_RECENCY_MAX_MO:
            return 0.0
        return max(0.0, 1.0 - (months_ago / REFI_RECENCY_MAX_MO))
    except (ValueError, TypeError):
        return 0.0


def _credit_signal(rating: str | None) -> float:
    """Ordinal credit-quality signal from Versium credit grade A–D.

    Maps: A → 1.0, B → 0.75, C → 0.40, D → 0.10, None → 0.0.
    Predicts financing eligibility for large jobs (solar, HVAC, roofing).
    """
    if not rating:
        return 0.0
    return CREDIT_GRADE_SCORES.get(str(rating).upper().strip(), 0.0)


def _children_signal(has_children: bool | None) -> float:
    """1.0 if children are present in the household, else 0.

    Families with children are the primary customer for safety-driven services:
    pool fencing, HVAC air quality, structural work.
    """
    return 1.0 if has_children else 0.0


def _gardening_signal(gardening_flag: bool | None) -> float:
    """1.0 if the owner has a gardening/outdoor lifestyle interest, else 0.

    A direct behavioral indicator for landscaping, pool maintenance, and
    other outdoor service verticals.
    """
    return 1.0 if gardening_flag else 0.0


def _absentee_signal(owner_occupied: bool | None) -> float:
    """1.0 when the owner does NOT occupy the property (investor/landlord), else 0.

    Absentee owners are reachable through their mailing address and are strong
    prospects for rental turnover, exterior, and systems work. A missing
    owner_occupied value scores 0 — unknown is not assumed to be absentee.
    """
    if owner_occupied is None:
        return 0.0
    return 1.0 if owner_occupied is False else 0.0


def _tenure_signal(years: int | None) -> float:
    """Long ownership tenure — aging systems overdue for big-ticket replacement.

    Scales linearly to TENURE_TARGET_YEARS, then caps at 1.0. Complements the
    home-age signal: a long-tenured owner of an older home is the most "due".
    """
    if not years or years <= 0:
        return 0.0
    return min(1.0, years / TENURE_TARGET_YEARS)


def _life_stage_signal(stage: str | None) -> float:
    """Ordinal life-stage motivation signal (mirrors the _credit_signal lookup).

    Maps the normalized life_stage values produced by pipeline.demographics:
    new_mover → 1.0, retiree → 0.6, established → 0.4, other → 0.1, None → 0.0.
    Recent movers renovate soonest; retirees invest in aging-in-place with equity.
    """
    if not stage:
        return 0.0
    return LIFE_STAGE_SCORES.get(str(stage).lower().strip(), 0.0)


# ── Score explanation ─────────────────────────────────────────────────────────
# Reuse the exact production signal functions above so the breakdown can never
# drift from the real score. Keyed by the same factor keys used in the weights.
_SIGNAL_FNS = {
    "age":              _age_signal,
    "sale":             _sale_signal,
    "equity":           _equity_signal,
    "garage":           _garage_signal,
    "income":           _income_signal,
    "permit":           _permit_signal,
    "neighborhood":     _neighborhood_signal,
    "pool":             _pool_signal,
    "slab":             _slab_signal,
    "storm":            _storm_signal,
    "home_improvement": _home_improvement_signal,
    "refi":             _refi_signal,
    "credit":           _credit_signal,
    "children":         _children_signal,
    "gardening":        _gardening_signal,
    "absentee":         _absentee_signal,
    "tenure":           _tenure_signal,
    "life_stage":       _life_stage_signal,
}


def explain_score(row: dict, weights: dict) -> dict:
    """Break a lead's score into per-factor contributions.

    For each factor weighted in `weights` (skipping zero-weight factors), reports
    its normalized signal strength (0–1) and weighted point contribution
    (weight × signal × 100). The contributions sum to the score from
    `_compute_score`, so the breakdown always reconciles with the displayed total.
    """
    factors = []
    for key, weight in weights.items():
        if not weight:
            continue  # factor carries no weight in this profile — omit as noise
        meta = FACTOR_META[key]
        signal = _SIGNAL_FNS[key](row.get(meta["field"]))
        factors.append({
            "key":          key,
            "label":        meta["label"],
            "description":  meta["description"],
            "weight":       weight,
            "signal":       round(signal, 4),
            "contribution": round(weight * signal * 100, 2),
        })

    factors.sort(key=lambda f: f["contribution"], reverse=True)
    top_drivers = [f["key"] for f in factors[:3] if f["contribution"] > 0]
    score = _compute_score(row, weights)
    return {
        "score":       round(score, 2),
        "grade":       _grade(score),
        "factors":     factors,
        "top_drivers": top_drivers,
    }


def describe_vertical(vertical: str | None) -> dict:
    """Describe the weight profile used for a vertical, derived purely from the
    weights so the description can never drift from actual scoring.

    Unknown/None verticals fall back to DEFAULT_WEIGHTS (same rule as
    `scorer.score_zip`); `is_default` flags that fallback for the UI.
    """
    weights = VERTICAL_WEIGHTS.get(vertical) if vertical else None
    is_default = weights is None
    if is_default:
        weights = DEFAULT_WEIGHTS

    factors = [
        {
            "key":         key,
            "label":       FACTOR_META[key]["label"],
            "description": FACTOR_META[key]["description"],
            "weight":      weight,
        }
        for key, weight in weights.items()
        if weight
    ]
    factors.sort(key=lambda f: f["weight"], reverse=True)
    return {"vertical": vertical, "is_default": is_default, "factors": factors}
