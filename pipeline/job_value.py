"""
Job-value estimation — a coarse, deterministic ballpark for estimated_job_value
when a lead has no manual estimate yet.

Pure functions (no DB / no network) so they're unit-testable like equity/scoring.
Estimation, best source first:
  1. per-vertical model (flat base + per-unit terms from known property fields)
  2. flat fallback: estimated_value × JOB_VALUE_FALLBACK_PCT
Returns whole dollars, or None when there's nothing to estimate from.
"""
from config import JOB_VALUE_MODEL, JOB_VALUE_FALLBACK_PCT


def estimate_job_value(row: dict, vertical: str | None = None) -> int | None:
    """Best-available job-value estimate in whole dollars, or None."""
    est = _vertical_estimate(row, vertical)

    # Generic fallback — a small fraction of the home's value.
    if est is None:
        value = row.get("estimated_value")
        if value:
            est = float(value) * JOB_VALUE_FALLBACK_PCT

    if est is None:
        return None
    return max(int(round(est)), 0)


def _vertical_estimate(row: dict, vertical: str | None) -> float | None:
    """Per-vertical model. Returns None when the model can't be applied."""
    model = JOB_VALUE_MODEL.get(vertical) if vertical else None
    if not model:
        return None

    # Pool-gated recurring services only estimate when a pool is confirmed.
    if model.get("requires_pool"):
        if not row.get("has_pool"):
            return None
        return float(model.get("base", 0)) + float(model.get("pool_value", 0))

    total = float(model.get("base", 0))
    contributed = False

    sqft = row.get("square_footage")
    if model.get("per_sqft") and sqft:
        total += float(model["per_sqft"]) * float(sqft)
        contributed = True

    garages = row.get("garage_spaces")
    if model.get("per_garage") and garages:
        total += float(model["per_garage"]) * float(garages)
        contributed = True

    lot = row.get("lot_size")
    if model.get("per_lot_sqft") and lot:
        total += float(model["per_lot_sqft"]) * float(lot)
        contributed = True

    # A flat base alone (no property inputs) isn't a meaningful estimate — let the
    # generic value-based fallback handle it instead.
    return total if contributed else None
