"""Neighborhood-relative value benchmark.

ZIP-level value is misleading — home prices vary widely within a single ZIP, so a
genuinely premium home gets buried among modest ones. This computes, for every
property, how its value compares to its *immediate neighborhood* (geohash-6 cell,
~1.2km, the "block" unit used by api/neighbors.py), measured by value-per-sqft
(homes without square footage are left unbenchmarked rather than mixed in).

The benchmark MUST NOT be computed inside the per-ZIP scoring batch: a cell on a
ZIP boundary spans two ZIPs, so a per-ZIP median would be biased. We persist the
result onto each row so scoring stays DB-free and the leads list can filter/sort
on it cheaply.

That does not mean every run has to rewrite the whole account. `zips=[...]`
scopes the recompute to the geohash cells the run's ZIPs touch, which is what
makes a per-ZIP run cost O(ZIP) instead of O(account) — an account-wide rewrite
was 983s of a 24-minute run and grew with every ZIP ever seeded. The cell medians
are unchanged by that scoping: the row set is bounded by *cell*, never by ZIP, so
a boundary cell is still measured over every qualifying row in it (including the
neighbouring ZIP's). See `recompute_neighborhood_values` for what the fallback
tiers do under scoping, which is the one place the two paths can differ.

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


def backfill_geohashes(conn, account_id: int, zips: list[str] | None = None) -> int:
    """Populate geohash from lat/lng for any geocoded lead still missing it.

    Leads imported outside the geocode pipeline step have lat/lng but no geohash,
    which would silently exclude them from neighborhood grouping (and from
    api/neighbors.py). Encode them in Python with the same geohash2 settings the
    geocode step uses. Returns the number of rows backfilled.

    `zips` bounds the scan to those ZIPs (a per-ZIP pipeline run only creates
    rows in its own ZIP, so scanning the whole account is wasted work that grows
    with every ZIP ever seeded). None keeps the account-wide sweep.
    """
    if _encode(0.0, 0.0) is None:
        log.warning("geohash2 not installed — cannot backfill geohashes.")
        return 0
    from psycopg2.extras import execute_values
    sql = ("SELECT id, latitude, longitude FROM properties "
           "WHERE account_id = %(acct)s AND geohash IS NULL "
           "  AND latitude IS NOT NULL AND longitude IS NOT NULL")
    params: dict = {"acct": account_id}
    if zips:
        sql += " AND zip = ANY(%(zips)s)"
        params["zips"] = list(zips)
    with conn.cursor() as cur:
        cur.execute(sql, params)
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


def touched_cells(conn, account_id: int, zips: list[str]) -> list[str]:
    """The geohash-6 cells the given ZIPs' rows sit in, for scoping a recompute.

    Keyed off the rows themselves rather than any ZIP↔cell table, so a cell that
    straddles a ZIP line is included as soon as one of its members is in a
    processed ZIP — which is exactly when that cell's median can have moved.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT LEFT(geohash, %(prec)s) FROM properties "
            "WHERE account_id = %(acct)s AND zip = ANY(%(zips)s) "
            "  AND geohash IS NOT NULL AND archived_at IS NULL",
            {"prec": GEOHASH_PRECISION, "acct": account_id, "zips": list(zips)},
        )
        return sorted({row[0] for row in cur.fetchall() if row[0]})


def recompute_neighborhood_values(conn, account_id: int,
                                  zips: list[str] | None = None) -> int:
    """Recompute neighborhood_value_ratio/pctile/basis for an org's leads.

    Metric is value-per-sqft (estimated_value / square_footage), compared to the
    median of the home's geohash-6 cell. The metric must be uniform within a cell,
    so homes missing estimated_value, square footage, or geohash are left NULL
    (unbenchmarked) rather than mixed in. Cells with fewer than
    NEIGHBORHOOD_MIN_MEMBERS leads fall back to the HCAD neighborhood median, then
    to the ZIP median (basis='hcad_neighborhood' / 'zip').

    `zips` bounds the work to the geohash cells those ZIPs touch — the per-ZIP
    pipeline path, where an account-wide rewrite was the single slowest step and
    got slower with every ZIP ever seeded. None (or an empty/blank list, so a
    caller that lost its ZIP never silently under-computes) keeps the
    account-wide sweep, for callers (backfill rescore, rescore-all) that really
    did change every row.

    What scoping does and does not change:
      • Cell medians and cell percentiles are IDENTICAL to the account-wide run.
        The row set is bounded by *cell*, not by ZIP, so a cell straddling a ZIP
        line is still measured over every qualifying row in it. This is the
        load-bearing property — the benchmark's meaning must not move.
      • Rows in cells this run did not touch keep the benchmark they already had.
        Nothing about their cell changed: a per-ZIP run only writes rows in its
        own ZIP, and any cell holding one of those rows is in `cells`.
      • The sparse-cell FALLBACK tiers are computed from the same scoped rows, so
        a row that falls back can compare against a narrower HCAD-neighborhood or
        ZIP median than an account-wide run would have used. That is deliberate
        (the median a row is ranked against must come from the dataset it was
        ranked in) and it only reaches rows whose own cell has fewer than
        NEIGHBORHOOD_MIN_MEMBERS members. For the processed ZIPs the zip tier is
        exact anyway — every one of their cells is in `cells`, so their rows are
        all present. Callers that need the fallback tiers computed against the
        whole account must pass zips=None.

    Returns the number of rows updated with a non-NULL benchmark.
    """
    zips = [z for z in (zips or []) if z] or None

    # Self-healing: leads imported without the geocode step have lat/lng but no
    # geohash, so encode them first or they'd be excluded from cell grouping.
    backfill_geohashes(conn, account_id, zips=zips)

    cells: list[str] | None = None
    if zips is not None:
        cells = touched_cells(conn, account_id, zips)
        if not cells:
            # Nothing in these ZIPs is geocoded yet, so there is no cell whose
            # median could have moved. Skip rather than silently falling back to
            # the account-wide rewrite this call was asked to avoid.
            log.info("Neighborhood recompute (scoped): account=%s zips=%s — no "
                     "geocoded rows, skipped", account_id, ",".join(zips))
            return 0

    params = {
        "prec": GEOHASH_PRECISION,
        "acct": account_id,
        "min_members": NEIGHBORHOOD_MIN_MEMBERS,
        "cells": cells,
    }
    # Same predicate on the reset and on `vals`: resetting a wider row set than
    # the recompute rewrites would leave untouched rows permanently NULL.
    scope = " AND LEFT(geohash, %(prec)s) = ANY(%(cells)s)" if cells else ""

    with conn.cursor() as cur:
        # Reset first so leads that no longer qualify (archived, lost value, etc.)
        # don't keep a stale benchmark from a previous run.
        cur.execute(
            "UPDATE properties SET neighborhood_value_ratio = NULL, "
            "neighborhood_value_pctile = NULL, neighborhood_value_basis = NULL "
            "WHERE account_id = %(acct)s" + scope,
            params,
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
                --
                -- The optional cell predicate is what bounds a per-ZIP run. It
                -- filters by CELL, never by ZIP: every qualifying member of a
                -- touched cell is here, whichever ZIP it belongs to, so the
                -- medians and percent_ranks below are the same numbers the
                -- account-wide run computes for these cells.
                SELECT id, zip, hcad_neighborhood_code AS nbhd,
                       LEFT(geohash, %(prec)s) AS cell,
                       estimated_value::numeric / square_footage AS metric
                FROM properties
                WHERE account_id = %(acct)s
                  AND estimated_value IS NOT NULL
                  AND square_footage IS NOT NULL AND square_footage > 0
                  AND geohash IS NOT NULL
                  AND archived_at IS NULL
                  {scope}
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
            """.format(scope=scope),
            params,
        )
        updated = cur.rowcount
    conn.commit()
    if cells is None:
        log.info("Recomputed neighborhood values for account %s: %d leads",
                 account_id, updated)
    else:
        log.info("Neighborhood recompute (scoped): account=%s zips=%s cells=%d rows=%d",
                 account_id, ",".join(zips), len(cells), updated)
    return updated
