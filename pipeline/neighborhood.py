"""Neighborhood-relative value benchmark.

ZIP-level value is misleading — home prices vary widely within a single ZIP, so a
genuinely premium home gets buried among modest ones. This computes, for every
property, how its value compares to its *immediate neighborhood* (geohash-6 cell,
~1.2km, the "block" unit used by api/neighbors.py), measured by value-per-sqft
(homes without square footage are left unbenchmarked rather than mixed in).

The benchmark MUST be computed account-wide over geohash cells, not inside the
per-ZIP scoring batch: a cell on a ZIP boundary spans two ZIPs, so a per-ZIP median
would be biased. We persist the result onto each row so scoring stays DB-free and
the leads list can filter/sort on it cheaply.

Three columns are written (see migration 025):
  neighborhood_value_ratio  — home value/sqft ÷ neighborhood median (1.0 = at median)
  neighborhood_value_pctile — percent_rank 0–1 within the neighborhood (0.8 = top 20%)
  neighborhood_value_basis  — 'cell' | 'zip' (sparse fallback) | NULL
"""
import logging

from config import NEIGHBORHOOD_MIN_MEMBERS

log = logging.getLogger(__name__)

# ~1.2km x 0.6km cell — "same street/block" scale. Matches api/neighbors.py
# (kept in sync deliberately; pipeline must not import from the api layer).
GEOHASH_PRECISION = 6

# Stored geohash precision (matches pipeline/geocode.py). The cell grouping uses
# the first GEOHASH_PRECISION chars of this.
GEOHASH_STORE_PRECISION = 7

try:
    import geohash2 as _geohash
    def _encode(lat, lng):
        return _geohash.encode(lat, lng, precision=GEOHASH_STORE_PRECISION)
except ImportError:
    def _encode(lat, lng):
        return None


def backfill_geohashes(conn, account_id: int) -> int:
    """Populate geohash from lat/lng for any geocoded lead still missing it.

    Leads imported outside the geocode pipeline step have lat/lng but no geohash,
    which would silently exclude them from neighborhood grouping (and from
    api/neighbors.py). Encode them in Python with the same geohash2 settings the
    geocode step uses. Returns the number of rows backfilled.
    """
    if _encode(0.0, 0.0) is None:
        log.warning("geohash2 not installed — cannot backfill geohashes.")
        return 0
    from psycopg2.extras import execute_values
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, latitude, longitude FROM properties "
            "WHERE account_id = %s AND geohash IS NULL "
            "  AND latitude IS NOT NULL AND longitude IS NOT NULL",
            (account_id,),
        )
        rows = cur.fetchall()
        if not rows:
            return 0
        encoded = [(lead_id, _encode(lat, lng)) for lead_id, lat, lng in rows]
        # Single bulk UPDATE ... FROM (VALUES ...) rather than a per-row loop.
        execute_values(
            cur,
            "UPDATE properties p SET geohash = v.gh "
            "FROM (VALUES %s) AS v(id, gh) WHERE p.id = v.id",
            encoded,
        )
    conn.commit()
    log.info("Backfilled geohash for %d leads in account %s", len(rows), account_id)
    return len(rows)


def recompute_neighborhood_values(conn, account_id: int) -> int:
    """Recompute neighborhood_value_ratio/pctile/basis for every lead in an org.

    Metric is value-per-sqft (estimated_value / square_footage), compared to the
    median of the home's geohash-6 cell. The metric must be uniform within a cell,
    so homes missing estimated_value, square footage, or geohash are left NULL
    (unbenchmarked) rather than mixed in. Cells with fewer than
    NEIGHBORHOOD_MIN_MEMBERS leads fall back to the ZIP median (basis='zip').

    Returns the number of rows updated with a non-NULL benchmark.
    """
    # Self-healing: leads imported without the geocode step have lat/lng but no
    # geohash, so encode them first or they'd be excluded from cell grouping.
    backfill_geohashes(conn, account_id)

    with conn.cursor() as cur:
        # Reset first so leads that no longer qualify (archived, lost value, etc.)
        # don't keep a stale benchmark from a previous run.
        cur.execute(
            "UPDATE properties SET neighborhood_value_ratio = NULL, "
            "neighborhood_value_pctile = NULL, neighborhood_value_basis = NULL "
            "WHERE account_id = %s",
            (account_id,),
        )

        # percentile_cont is an ordered-set aggregate and cannot be used as a
        # window function (even on PG18), so medians are computed in GROUP BY
        # CTEs and joined back. percent_rank IS a window function.
        #
        # Fallback hierarchy: geohash-6 cell (spatial ~1.2km) → HCAD neighborhood
        # code (county assessor comparable-property grouping) → ZIP code.
        # Each tier is used only when it has ≥ NEIGHBORHOOD_MIN_MEMBERS members.
        cur.execute(
            """
            WITH vals AS (
                -- Metric must be uniform within a cell or the median is meaningless,
                -- so compare value-per-sqft only across homes that have square
                -- footage. Homes missing sqft are left unbenchmarked (NULL).
                SELECT id, zip, hcad_neighborhood_code AS nbhd,
                       LEFT(geohash, %(prec)s) AS cell,
                       estimated_value::numeric / square_footage AS metric
                FROM properties
                WHERE account_id = %(acct)s
                  AND estimated_value IS NOT NULL
                  AND square_footage IS NOT NULL AND square_footage > 0
                  AND geohash IS NOT NULL
                  AND archived_at IS NULL
            ),
            cell_stats AS (
                SELECT cell, COUNT(*) AS n,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY metric) AS med
                FROM vals GROUP BY cell
            ),
            nbhd_stats AS (
                -- Only group by HCAD neighborhood when the code is present.
                SELECT nbhd, COUNT(*) AS n,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY metric) AS med
                FROM vals WHERE nbhd IS NOT NULL GROUP BY nbhd
            ),
            zip_stats AS (
                SELECT zip,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY metric) AS med
                FROM vals GROUP BY zip
            ),
            ranked AS (
                SELECT id,
                       percent_rank() OVER (PARTITION BY cell  ORDER BY metric) AS cell_pct,
                       percent_rank() OVER (PARTITION BY nbhd  ORDER BY metric) AS nbhd_pct,
                       percent_rank() OVER (PARTITION BY zip   ORDER BY metric) AS zip_pct
                FROM vals
            ),
            final AS (
                SELECT v.id,
                       v.metric,
                       cs.n >= %(min_members)s                      AS use_cell,
                       COALESCE(ns.n >= %(min_members)s, FALSE)     AS use_nbhd,
                       cs.med  AS cell_med,
                       ns.med  AS nbhd_med,
                       zs.med  AS zip_med,
                       r.cell_pct, r.nbhd_pct, r.zip_pct
                FROM vals v
                JOIN cell_stats cs ON cs.cell = v.cell
                LEFT JOIN nbhd_stats ns ON ns.nbhd IS NOT DISTINCT FROM v.nbhd
                JOIN zip_stats  zs ON zs.zip IS NOT DISTINCT FROM v.zip
                JOIN ranked     r  ON r.id = v.id
            )
            UPDATE properties p SET
                neighborhood_value_basis  = CASE
                    WHEN f.use_cell THEN 'cell'
                    WHEN f.use_nbhd THEN 'hcad_neighborhood'
                    ELSE 'zip'
                END,
                neighborhood_value_pctile = CASE
                    WHEN f.use_cell THEN f.cell_pct
                    WHEN f.use_nbhd THEN f.nbhd_pct
                    ELSE f.zip_pct
                END,
                neighborhood_value_ratio  = CASE
                    WHEN f.use_cell AND f.cell_med > 0
                        THEN f.metric / f.cell_med
                    WHEN f.use_nbhd AND f.nbhd_med IS NOT NULL AND f.nbhd_med > 0
                        THEN f.metric / f.nbhd_med
                    WHEN NOT f.use_cell AND NOT f.use_nbhd AND f.zip_med > 0
                        THEN f.metric / f.zip_med
                    ELSE NULL
                END
            FROM final f
            WHERE p.id = f.id
            """,
            {
                "prec": GEOHASH_PRECISION,
                "acct": account_id,
                "min_members": NEIGHBORHOOD_MIN_MEMBERS,
            },
        )
        updated = cur.rowcount
    conn.commit()
    log.info("Recomputed neighborhood values for account %s: %d leads", account_id, updated)
    return updated
