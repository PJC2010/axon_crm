"""
GET /api/map/cells       — geohash-6 aggregates for the service-area choropleth
GET /api/map/properties  — lightweight property pins within a viewport bbox
GET /api/map/zips        — ZIPs the account has leads in, with their extents

All three power the interactive property map. They reuse the account scoping,
archived-lead exclusion, and filter-building (`_build_filters`) established in
api/routes/leads.py so the map sees exactly the same leads the rest of the app
does. Each row carries both color bases (recent intent signals + lead score) so
the frontend's signals/score toggle never needs to refetch.
"""
import logging

from fastapi import APIRouter, Depends, Query
from psycopg2.extensions import connection as PGConn

from api import scoring_quota
from api.deps import get_db, dict_fetchall, get_current_user
from api.entitlements import get_scoring_limit
from api.models import MapCell, MapPoint, MapZip
from api.routes.leads import _build_filters

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/map/cells", response_model=list[MapCell])
def map_cells(
    vertical: str | None = Query(None),
    status: str | None = Query(None),
    signal_days: int = Query(90, ge=1, le=365, description="recency window for intent signals"),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """One row per geohash-6 cell with everything needed to shade it under either
    toggle mode. No min-member threshold — the map shows every cell with leads."""
    conditions, filter_params = _build_filters(
        user["account_id"], vertical=vertical, status=status,
    )
    conditions.append("geohash IS NOT NULL")
    where = f"WHERE {' AND '.join(conditions)}"

    # `s` is a recent-signal property set scoped to this account; it exposes only
    # property_id, so the unqualified columns in `where` stay unambiguous (they
    # all resolve to properties).
    sql = f"""
        SELECT LEFT(geohash, 6) AS cell,
               mode() WITHIN GROUP (ORDER BY hcad_neighborhood_name)
                 FILTER (WHERE hcad_neighborhood_name IS NOT NULL) AS name,
               COUNT(*) AS leads,
               AVG(lead_score) AS avg_score,
               COUNT(*) FILTER (WHERE score_grade = 'A') AS grade_a,
               COUNT(*) FILTER (WHERE score_grade = 'B') AS grade_b,
               COUNT(*) FILTER (WHERE score_grade = 'C') AS grade_c,
               COUNT(*) FILTER (WHERE score_grade = 'D') AS grade_d,
               COUNT(*) FILTER (WHERE s.property_id IS NOT NULL) AS signal_count,
               AVG(latitude) AS lat,
               AVG(longitude) AS lng
        FROM properties
        LEFT JOIN (
            SELECT DISTINCT property_id
            FROM signal_events
            WHERE account_id = %s
              AND detected_at >= NOW() - (%s * INTERVAL '1 day')
        ) s ON s.property_id = properties.id
        {where}
        GROUP BY cell
        ORDER BY signal_count DESC, leads DESC
    """
    params = [user["account_id"], signal_days] + filter_params
    with db.cursor() as cur:
        cur.execute(sql, params)
        rows = dict_fetchall(cur)
    return [MapCell(**r) for r in rows]


@router.get("/map/properties", response_model=list[MapPoint])
def map_properties(
    min_lat: float = Query(...),
    min_lng: float = Query(...),
    max_lat: float = Query(...),
    max_lng: float = Query(...),
    vertical: str | None = Query(None),
    status: str | None = Query(None),
    signal_days: int = Query(90, ge=1, le=365),
    limit: int = Query(2000, ge=1, le=5000),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Property pins inside the current map viewport. Hard `limit` keeps a
    zoomed-out request from dumping the whole table — the UI fetches these only
    once the user has zoomed past the choropleth threshold."""
    conditions, filter_params = _build_filters(
        user["account_id"], vertical=vertical, status=status,
        min_lat=min_lat, max_lat=max_lat, min_lng=min_lng, max_lng=max_lng,
    )
    conditions.append("latitude IS NOT NULL")
    conditions.append("longitude IS NOT NULL")
    where = f"WHERE {' AND '.join(conditions)}"

    # Correlated subquery (rather than a join) keeps the unqualified `where`
    # columns unambiguous, since signal_events also has account_id.
    sql = f"""
        SELECT id, address, latitude, longitude, lead_score, score_grade, status, lead_source,
               COALESCE((
                   SELECT array_agg(DISTINCT se.signal_type)
                   FROM signal_events se
                   WHERE se.property_id = properties.id
                     AND se.account_id = %s
                     AND se.detected_at >= NOW() - (%s * INTERVAL '1 day')
               ), '{{}}') AS signals
        FROM properties
        {where}
        ORDER BY lead_score DESC NULLS LAST
        LIMIT %s
    """
    params = [user["account_id"], signal_days] + filter_params + [limit]
    with db.cursor() as cur:
        cur.execute(sql, params)
        rows = dict_fetchall(cur)
    # A pin carries the full address and exact coordinates — MASKED_FIELDS the
    # scoring quota withholds — and MapPoint requires non-null lat/long, so an
    # unrevealed engine candidate past the allowance is dropped from the map
    # rather than masked. consume=False: viewing the map never spends reveals.
    # Only bites a metered map-enabled account (a per-account scoring override);
    # normal map plans are unlimited, so this is a no-op there.
    limit_ = get_scoring_limit(user["account_id"], db)
    if limit_ is not None:
        rows, _ = scoring_quota.apply_quota(db, user["account_id"], rows, limit_, consume=False)
        rows = [r for r in rows if not r.get("quota_masked")]
    return [MapPoint(**r) for r in rows]


@router.get("/map/zips", response_model=list[MapZip])
def map_zips(
    vertical: str | None = Query(None),
    status: str | None = Query(None),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Every ZIP the caller's account holds geocoded leads in, with the bounding
    box of those leads.

    Backs the map's ZIP jump control. Deriving the extent from the account's own
    rows (rather than a ZIP-centroid gazetteer or a geocoding call) means the
    picker only ever offers territory the account actually has data for, and
    fitting to a real extent frames the ZIP better than a centroid plus a guessed
    zoom would. Honours the same vertical/status filters as the other map
    endpoints so the list matches what the map is currently showing.
    """
    conditions, filter_params = _build_filters(
        user["account_id"], vertical=vertical, status=status,
    )
    conditions += ["zip IS NOT NULL", "latitude IS NOT NULL", "longitude IS NOT NULL"]
    where = f"WHERE {' AND '.join(conditions)}"

    # Percentiles, not MIN/MAX. A single mis-geocoded row (a Houston ZIP with a
    # lat/lng that landed in another state — there are a few hundred in real data)
    # would blow the extent up to a continental box and make "jump to this ZIP"
    # useless. The 1st/99th percentile tracks MIN/MAX within metres for a clean
    # ZIP while ignoring the strays. A single-row ZIP yields a zero-area box,
    # which the frontend's fitBounds maxZoom handles.
    sql = f"""
        SELECT zip,
               COUNT(*) AS leads,
               percentile_cont(0.01) WITHIN GROUP (ORDER BY latitude)  AS min_lat,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY latitude)  AS max_lat,
               percentile_cont(0.01) WITHIN GROUP (ORDER BY longitude) AS min_lng,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY longitude) AS max_lng
        FROM properties
        {where}
        GROUP BY zip
        ORDER BY zip
    """
    with db.cursor() as cur:
        cur.execute(sql, filter_params)
        rows = dict_fetchall(cur)
    return [MapZip(**r) for r in rows]
