"""
GET /api/map/cells       — geohash-6 aggregates for the service-area choropleth
GET /api/map/properties  — lightweight property pins within a viewport bbox

Both power the interactive property map. They reuse the account scoping,
archived-lead exclusion, and filter-building (`_build_filters`) established in
api/routes/leads.py so the map sees exactly the same leads the rest of the app
does. Each row carries both color bases (recent intent signals + lead score) so
the frontend's signals/score toggle never needs to refetch.
"""
import logging

from fastapi import APIRouter, Depends, Query
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, get_current_user
from api.models import MapCell, MapPoint
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
        SELECT id, address, latitude, longitude, lead_score, score_grade, status,
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
    return [MapPoint(**r) for r in rows]
