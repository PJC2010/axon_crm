"""
Geospatial scoring endpoints (juncto geo layer, Phase 1).

    GET  /api/geo/config            — resolved per-vertical geo config for the account
    POST /api/geo/score/batch       — recompute geo + final scores for given leads
    POST /api/geo/geocode/backfill  — enqueue geocoding for leads missing coordinates
    GET  /api/geo/service-area      — the account's service-area polygon (GeoJSON)
    PUT  /api/geo/service-area      — save a user-drawn service-area polygon

Clustering, heatmaps, prospecting, and the map UI are later phases.
"""
import logging

from fastapi import APIRouter, Depends
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel, Field

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user
from pipeline import geo_score_store
from pipeline.geocode_provider import enqueue_missing

router = APIRouter(prefix="/geo")
log = logging.getLogger(__name__)


class BatchScoreRequest(BaseModel):
    # Omit / empty → re-score the whole account in the background.
    lead_ids: list[int] = Field(default_factory=list, max_length=1000)


class ServiceAreaUpdate(BaseModel):
    # GeoJSON Polygon: {"type":"Polygon","coordinates":[[[lng,lat],...]]}
    polygon: dict


@router.get("/config")
def get_geo_config(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Effective geo config for the account: each vertical's platform default with
    any tenant override applied. Explains the weights behind the geo score."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (vertical) vertical, account_id, route_weight, "
            "  neighbor_weight, geo_blend, visits_per_year, event_trigger_types, "
            "  prospect_filter_preset "
            "FROM vertical_geo_config "
            "WHERE account_id = %s OR account_id IS NULL "
            "ORDER BY vertical, account_id NULLS LAST",  # override (non-null) wins
            (user["account_id"],),
        )
        rows = dict_fetchall(cur)
    return {"config": rows}


@router.post("/score/batch")
def score_batch(body: BatchScoreRequest, db: PGConn = Depends(get_db),
                user: dict = Depends(get_current_user)):
    """Recompute geo + final scores. With explicit lead_ids, runs synchronously and
    returns the count. Without, enqueues a full-account rescore in the background."""
    account_id = user["account_id"]
    if body.lead_ids:
        n = geo_score_store.rescore_leads(db, account_id, property_ids=body.lead_ids)
        return {"scored": n, "mode": "sync"}

    from api.scheduler import scheduler

    def _full():
        import psycopg2
        from config import DATABASE_URL
        conn = psycopg2.connect(DATABASE_URL)
        try:
            geo_score_store.refresh_service_area(conn, account_id)
            geo_score_store.rescore_leads(conn, account_id)
        finally:
            conn.close()

    try:
        scheduler.add_job(_full, id=f"geo_full_rescore_{account_id}", replace_existing=True)
        return {"scored": None, "mode": "queued"}
    except Exception:
        # No scheduler (e.g. tests) — fall back to synchronous.
        geo_score_store.refresh_service_area(db, account_id)
        n = geo_score_store.rescore_leads(db, account_id)
        return {"scored": n, "mode": "sync"}


@router.post("/geocode/backfill")
def geocode_backfill(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Queue geocoding for this account's leads that have an address but no
    coordinates. Draining happens in the background — never in this request."""
    n = enqueue_missing(db, user["account_id"])
    try:
        from api.scheduler import scheduler
        from pipeline.geocode_provider import process_queue

        def _drain():
            import psycopg2
            from config import DATABASE_URL
            conn = psycopg2.connect(DATABASE_URL)
            try:
                process_queue(conn, limit=1000)
            finally:
                conn.close()

        scheduler.add_job(_drain, id=f"geocode_drain_{user['account_id']}", replace_existing=True)
    except Exception:
        log.info("Scheduler unavailable — %d row(s) enqueued for the next geo tick", n)
    return {"enqueued": n}


@router.get("/service-area")
def get_service_area(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """The account's service-area polygon as GeoJSON. Falls back to the derived
    customer convex hull when none has been saved."""
    account_id = user["account_id"]
    ring, source = geo_score_store.get_service_area(db, account_id)
    if not ring:
        return {"polygon": None, "source": None}
    return {"polygon": geo_score_store._geojson_from_ring(ring), "source": source}


@router.put("/service-area")
def put_service_area(body: ServiceAreaUpdate, db: PGConn = Depends(get_db),
                     user: dict = Depends(get_current_user)):
    """Save a user-drawn service-area polygon (replaces any existing area) and
    re-score the account so the territory gate reflects it."""
    import psycopg2.extras
    account_id = user["account_id"]
    with db.cursor() as cur:
        cur.execute("DELETE FROM service_areas WHERE account_id = %s", (account_id,))
        cur.execute(
            "INSERT INTO service_areas (account_id, polygon, source) "
            "VALUES (%s, %s, 'user_drawn') RETURNING id, source",
            (account_id, psycopg2.extras.Json(body.polygon)),
        )
        row = dict_fetchone(cur)
    db.commit()
    geo_score_store.rescore_leads(db, account_id)
    return {"id": row["id"], "source": row["source"]}
