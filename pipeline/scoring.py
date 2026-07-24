"""
Pure lead-scoring math — no database dependency.

All signal functions return a normalized 0.0–1.0 float.
`score_property` is the public entry point; it returns (score, grade).
Weights and thresholds come from config.py and can be overridden per-vertical.
"""
from datetime import date

import config

from config import (
    GRADE_BANDS, GATE_MISS_FACTOR,
    EQUITY_FALLBACK_SIGNAL_SCALE,
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


def compute_score(row: dict, profile) -> float:
    """Profile-driven weighted sum — the generic core every profile shares.

    `profile` is a pipeline.profiles.ScoringProfile (duck-typed here to keep the
    import one-directional). Each weighted signal reads the row field named in
    the profile's factor_meta and normalizes it 0–1 via the profile's signal fn;
    the weighted sum scales to 0–100. Zero-weight factors are skipped, which is
    numerically identical to including them.
    """
    return _weighted_sum(row, profile.weights, profile.factor_meta,
                         profile.signal_fns, getattr(profile, "gates", ()))


def _compute_score(row: dict, weights: dict, gates: tuple = ()) -> float:
    """Back-compat wrapper: score with the classic property signal set.

    Kept as the entry point for callers that pass a raw weights dict
    (scorer.score_zip, explain_score, tests). Parity with the profile-driven
    loop is pinned by tests/test_scoring.py. `gates` mirrors ScoringProfile.gates
    for callers that hold a raw weights dict (scorer.score_zip passes them).
    """
    return _weighted_sum(row, weights, FACTOR_META, _SIGNAL_FNS, gates)


def _weighted_sum(row: dict, weights: dict, factor_meta: dict,
                  signal_fns: dict, gates: tuple = ()) -> float:
    """The one weighted-sum engine both scoring paths share.

    - SCORE_MISSING_MODE "zero" (default): a missing (None) field scores 0.
      "renormalize": missing fields are dropped and the total rescaled by the
      available weight share — the score reflects lead quality only, while
      `data_completeness` reports how much of the profile was measurable.
      Present-but-zero values score 0 in both modes.
    - Gates: for each gate factor, if the field is present and its signal is 0
      (confirmed absence of a qualifier, e.g. no pool for pool_maintenance),
      the final score is multiplied by GATE_MISS_FACTOR. Missing gate fields
      never gate.
    - When the scorer flagged estimated_equity as a flat-fallback estimate
      (row["estimated_equity_is_fallback"]), the equity contribution is scaled
      by EQUITY_FALLBACK_SIGNAL_SCALE — fallback equity proxies home value,
      which the neighborhood/income signals already measure.
    """
    mode = (config.SCORE_MISSING_MODE or "zero").lower()
    equity_scale = (EQUITY_FALLBACK_SIGNAL_SCALE
                    if row.get("estimated_equity_is_fallback") else 1.0)

    weighted = 0.0
    available = 0.0
    gate_miss = False
    for key, weight in weights.items():
        if not weight:
            continue
        value = row.get(factor_meta[key]["field"])
        if mode == "renormalize" and value is None:
            continue
        signal = signal_fns[key](value)
        if key in gates:
            # Gate factors never contribute weight directly; they only decide
            # whether the multiplier below fires.
            if value is not None and signal == 0.0:
                gate_miss = True
            continue
        if key == "equity":
            signal *= equity_scale
        weighted += weight * signal
        available += weight

    # Profiles with gates always renormalize over their non-gate weights: the
    # gate factor is a pure qualifier (contributes no points itself), so the
    # score ranks qualified leads on their remaining signals alone. A missing
    # gate field likewise neither gates nor penalizes.
    if (mode == "renormalize" or gates) and available:
        score = weighted / available
    else:
        score = weighted
    if gate_miss:
        score *= GATE_MISS_FACTOR
    return score * 100


def data_completeness(row: dict, weights: dict, factor_meta: dict = None) -> float:
    """Share of the weighted profile backed by real data (0.0–1.0).

    1.0 means every weighted factor has a non-None input; 0.0 means none do.
    Pair it with the score to separate "weak lead" from "thin file".
    """
    meta = factor_meta or FACTOR_META
    total = sum(w for w in weights.values() if w)
    if not total:
        return 0.0
    present = sum(
        w for key, w in weights.items()
        if w and row.get(meta[key]["field"]) is not None
    )
    return round(present / total, 4)


def validate_weights(weights: dict, factor_meta: dict = None,
                     signal_fns: dict = None) -> None:
    """Fail fast on a malformed weight profile instead of KeyErroring mid-score.

    Raises ValueError for unknown signal keys (not in factor_meta/signal_fns),
    negative weights, or weights that don't sum to 1.0 (within float slop).
    Zero-weight keys are allowed but must still be known signals.
    """
    meta = factor_meta or FACTOR_META
    fns = signal_fns or _SIGNAL_FNS
    unknown = set(weights) - (set(meta) & set(fns))
    if unknown:
        raise ValueError(f"Unknown signal key(s) in weights: {sorted(unknown)}")
    for key, w in weights.items():
        if w < 0:
            raise ValueError(f"Negative weight for '{key}': {w}")
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"Weights must sum to 1.0, got {total!r}")


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


def _summarize(grade: str, factors: list[dict], top_drivers: list[str]) -> str:
    """A one-line, plain-language reason for the score: grade + its top drivers.

    Reads off the same `factors`/`top_drivers` the breakdown already computes, so
    the sentence can never disagree with the bars. Labels are lowercased mid-
    sentence ("storm activity" reads better than "Storm activity"). With no
    positive drivers (low scores), say so rather than naming weak factors.
    """
    labels = [f["label"].lower() for f in factors if f["key"] in top_drivers]
    if not labels:
        return f"{grade} lead — no standout signals for this profile."
    if len(labels) == 1:
        phrase = labels[0]
    else:
        phrase = ", ".join(labels[:-1]) + ", and " + labels[-1]
    return f"{grade} lead — driven mainly by {phrase}."


def explain_score(row: dict, weights: dict, profile=None) -> dict:
    """Break a lead's score into per-factor contributions.

    For each factor weighted in `weights` (skipping zero-weight factors), reports
    its normalized signal strength (0–1) and weighted point contribution
    (weight × signal × 100). The contributions sum to the score from
    `_compute_score`, so the breakdown always reconciles with the displayed total.

    When a `profile` (pipeline.profiles.ScoringProfile) is passed, its weights,
    factor metadata, and signal functions are used instead — this is how
    non-property profiles get the same explainable breakdown for free.
    """
    meta_map = profile.factor_meta if profile is not None else FACTOR_META
    fns = profile.signal_fns if profile is not None else _SIGNAL_FNS
    if profile is not None:
        weights = profile.weights

    factors = []
    for key, weight in weights.items():
        if not weight:
            continue  # factor carries no weight in this profile — omit as noise
        meta = meta_map[key]
        signal = fns[key](row.get(meta["field"]))
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
    gates = getattr(profile, "gates", ()) if profile is not None else ()
    score = (compute_score(row, profile) if profile is not None
             else _compute_score(row, weights, gates))

    # Keep the breakdown reconciled with the displayed score even when the
    # engine adjusted it (gate multiplier / renormalized missing data / equity
    # fallback scale): rescale all contributions by the same factor so they
    # still sum to `score`, and flag the adjustment explicitly.
    raw_total = sum(f["contribution"] for f in factors)
    gated = False
    if raw_total > 0 and abs(score - raw_total) > 0.01:
        adj = score / raw_total
        for f in factors:
            f["contribution"] = round(f["contribution"] * adj, 2)
        gate_keys = set(gates)
        gated = any(
            gate_keys & {f["key"]} and f["signal"] == 0.0
            and row.get((meta_map)[f["key"]]["field"]) is not None
            for f in factors
        )

    grade = _grade(score)
    return {
        "score":             round(score, 2),
        "grade":             grade,
        "factors":           factors,
        "top_drivers":       top_drivers,
        "summary":           _summarize(grade, factors, top_drivers),
        "data_completeness": data_completeness(row, weights, meta_map),
        "gated":             gated,
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
