"""
Pre-enrichment lead selection — geographic narrowing (D1) + Top-N cap (A).

Runs AFTER the free steps (seed / census / geocode / HCAD) and BEFORE any paid
enrichment (property detail, skip-trace). It ranks the ZIP's candidate rows using
only fields that are already free at this point and marks `enrichment_selected`,
so the paid steps touch a small, focused subset instead of the entire ZIP.

Two levers, combinable:

  • Radius-from-address (D1): keep only rows whose lat/lng fall within
    `radius_mi` of a center point (a geocoded address). Rows without coordinates
    can't be confirmed inside the circle, so they're excluded.

  • Top-N cap (A): keep the best `top_n` rows by a cheap pre-score. Because the
    pre-score can't see paid-only signals (precise equity, garage, permits), it
    over-selects `top_n * OVERSAMPLE` rows for enrichment; `trim_to_top_n` then
    cuts back to `top_n` after full scoring, so the final list is ranked on real
    scores while paid calls stay close to `top_n`.

Pure helpers (`haversine_miles`, `prescore`) are DB-free and unit-tested.
"""
import logging
import math

from config import DEFAULT_WEIGHTS, VERTICAL_WEIGHTS, EQUITY_FALLBACK_PCT
from pipeline.db import fetch_by_zip
from pipeline.scoring import _compute_score

log = logging.getLogger(__name__)

# How many extra rows to enrich beyond top_n so the post-score trim has slack to
# correct the approximate pre-score ranking (see module docstring).
OVERSAMPLE = 1.5

EARTH_RADIUS_MI = 3958.7613


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles between two lat/lng points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2)
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(a))


def prescore(row: dict, weights: dict) -> float:
    """Cheap pre-enrichment score from free fields only.

    Reuses the production `_compute_score` so the ranking is consistent with the
    real scorer. Paid-only signals (garage, permits) are simply absent at this
    stage and contribute 0. Equity is approximated from estimated_value via the
    same fallback fraction the paid step uses, when no equity is known yet.
    """
    if not row.get("estimated_equity") and row.get("estimated_value"):
        row = dict(row)
        row["estimated_equity"] = int(row["estimated_value"] * EQUITY_FALLBACK_PCT)
    return _compute_score(row, weights)


def _within_radius(row: dict, center: tuple[float, float] | None,
                   radius_mi: float | None) -> bool:
    """True if no radius filter applies, or the row is inside the circle."""
    if not center or not radius_mi:
        return True
    lat, lng = row.get("latitude"), row.get("longitude")
    if lat is None or lng is None:
        return False
    return haversine_miles(center[0], center[1], lat, lng) <= radius_mi


def _set_selected(conn, ids: list[int], value: bool) -> None:
    if not ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE properties SET enrichment_selected = %s WHERE id = ANY(%s)",
            (value, ids),
        )
    conn.commit()


def select_for_enrichment(conn, zip_code: str, *, top_n: int | None = None,
                          center: tuple[float, float] | None = None,
                          radius_mi: float | None = None,
                          vertical: str | None = None) -> dict:
    """Mark which rows in `zip_code` proceed to paid enrichment.

    Applies the radius filter first, then the Top-N cap (over-selecting by
    OVERSAMPLE). Selected rows get enrichment_selected = TRUE, the rest FALSE.
    Returns counts for logging/run results.
    """
    weights = VERTICAL_WEIGHTS.get(vertical, DEFAULT_WEIGHTS) if vertical else DEFAULT_WEIGHTS
    rows = fetch_by_zip(conn, zip_code)
    candidates = len(rows)

    in_radius = [r for r in rows if _within_radius(r, center, radius_mi)]
    in_radius_ids = {r["id"] for r in in_radius}
    excluded_by_radius = [r for r in rows if r["id"] not in in_radius_ids]

    if top_n:
        budget = math.ceil(top_n * OVERSAMPLE)
        ranked = sorted(in_radius, key=lambda r: prescore(r, weights), reverse=True)
        keep = ranked[:budget]
        drop = ranked[budget:]
    else:
        keep = in_radius
        drop = []

    keep_ids = [r["id"] for r in keep]
    drop_ids = [r["id"] for r in drop] + [r["id"] for r in excluded_by_radius]
    _set_selected(conn, keep_ids, True)
    _set_selected(conn, drop_ids, False)

    result = {
        "candidates": candidates,
        "in_radius": len(in_radius),
        "selected": len(keep_ids),
        "excluded": len(drop_ids),
    }
    log.info("Selection for ZIP %s: %s", zip_code, result)
    return result


def trim_to_top_n(conn, zip_code: str, top_n: int) -> int:
    """Post-scoring precision trim: keep only the top_n selected rows by real
    lead_score, deselecting the over-sampled remainder so the contact step (and
    any selected-only consumers) see exactly the final list. Returns rows kept.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM properties "
            "WHERE zip = %s AND enrichment_selected = TRUE "
            "ORDER BY lead_score DESC NULLS LAST, id "
            "OFFSET %s",
            (zip_code, top_n),
        )
        extra_ids = [r[0] for r in cur.fetchall()]
    _set_selected(conn, extra_ids, False)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM properties "
            "WHERE zip = %s AND enrichment_selected = TRUE",
            (zip_code,),
        )
        kept = cur.fetchone()[0]
    log.info("Trimmed ZIP %s to top %d (kept %d, deselected %d)",
             zip_code, top_n, kept, len(extra_ids))
    return kept
