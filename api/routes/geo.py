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

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from pydantic import BaseModel, Field

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user
from config import CUSTOMER_STATUSES, GEO_H3_RESOLUTION
from pipeline import geo_score_store, geo_h3
from pipeline.geocode_provider import enqueue_missing

router = APIRouter(prefix="/geo")
log = logging.getLogger(__name__)


class BatchScoreRequest(BaseModel):
    # Omit / empty → re-score the whole account in the background.
    lead_ids: list[int] = Field(default_factory=list, max_length=1000)


class ServiceAreaUpdate(BaseModel):
    # GeoJSON Polygon: {"type":"Polygon","coordinates":[[[lng,lat],...]]}
    polygon: dict


class ProspectSeed(BaseModel):
    # Exactly one of these identifies the seed; a point is a user-dropped pin.
    cluster_id: int | None = None
    customer_id: int | None = None
    lat: float | None = None
    lng: float | None = None


class ProspectRequest(BaseModel):
    seed: ProspectSeed
    radius_m: int | None = Field(default=None, ge=100, le=16000)
    vertical: str | None = None
    # Optional override; when omitted, the vertical's prospect_filter_preset from
    # vertical_geo_config is used.
    preset: dict | None = None


class NeighborsRequest(BaseModel):
    job_id: int
    radius_m: int = Field(default=150, ge=25, le=1600)
    limit: int = Field(default=25, ge=1, le=100)


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


@router.get("/clusters")
def get_clusters(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """The account's customer clusters as a GeoJSON FeatureCollection — each hull
    a polygon feature carrying its label, customer count, and centroid. Powers the
    cluster overlay and the 'prospect this area' action."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT cluster_label, hull, centroid_lat, centroid_lng, customer_count, computed_at "
            "FROM customer_clusters WHERE account_id = %s ORDER BY customer_count DESC",
            (user["account_id"],),
        )
        rows = dict_fetchall(cur)
    features = [
        {
            "type": "Feature",
            "geometry": r["hull"],  # GeoJSON Polygon, or null for tiny clusters
            "properties": {
                "cluster_label": r["cluster_label"],
                "customer_count": r["customer_count"],
                "centroid": [r["centroid_lng"], r["centroid_lat"]],
                "computed_at": r["computed_at"],
            },
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@router.get("/heatmap")
def get_heatmap(
    metric: str = Query("density", pattern="^(density|avg_score)$"),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """H3-hex aggregates for the heatmap. metric=density → customers per hex;
    metric=avg_score → average final (blended) score per hex. Each cell includes
    its H3 id (for deck.gl's H3HexagonLayer) and boundary polygon. Reports
    available=false when the optional h3 package isn't installed / no rows have a
    hex yet, so the frontend can fall back to the geohash choropleth."""
    account_id = user["account_id"]
    with db.cursor() as cur:
        cur.execute(
            "SELECT p.h3_r8, "
            "  COUNT(*) AS leads, "
            "  COUNT(*) FILTER (WHERE p.status = ANY(%s)) AS customers, "
            "  AVG(COALESCE(lgs.final_score, p.lead_score)) AS avg_score "
            "FROM properties p "
            "LEFT JOIN lead_geo_scores lgs ON lgs.property_id = p.id "
            "WHERE p.account_id = %s AND p.h3_r8 IS NOT NULL AND p.archived_at IS NULL "
            "GROUP BY p.h3_r8",
            (list(CUSTOMER_STATUSES), account_id),
        )
        rows = dict_fetchall(cur)

    cells = []
    for r in rows:
        avg_score = float(r["avg_score"]) if r["avg_score"] is not None else None
        value = r["customers"] if metric == "density" else avg_score
        cells.append({
            "h3": r["h3_r8"],
            "value": value,
            "leads": r["leads"],
            "customers": r["customers"],
            "avg_score": round(avg_score, 2) if avg_score is not None else None,
            "boundary": geo_h3.cell_boundary(r["h3_r8"]),
            "center": geo_h3.cell_center(r["h3_r8"]),
        })

    return {
        "metric": metric,
        "resolution": GEO_H3_RESOLUTION,
        "available": geo_h3.available() and bool(cells),
        "cells": cells,
    }


@router.post("/cluster/recompute")
def recompute_clusters(db: PGConn = Depends(get_db), user: dict = Depends(get_current_user)):
    """Re-run DBSCAN clustering + H3 backfill for the account. Runs in the
    background when the scheduler is available, else synchronously."""
    account_id = user["account_id"]
    try:
        from api.scheduler import scheduler

        def _job():
            import psycopg2
            from config import DATABASE_URL
            from pipeline.geo_cluster_store import backfill_h3, recompute_clusters as _recompute
            conn = psycopg2.connect(DATABASE_URL)
            try:
                backfill_h3(conn, account_id)
                _recompute(conn, account_id)
            finally:
                conn.close()

        scheduler.add_job(_job, id=f"geo_cluster_{account_id}", replace_existing=True)
        return {"mode": "queued"}
    except Exception:
        from pipeline.geo_cluster_store import backfill_h3, recompute_clusters as _recompute
        backfill_h3(db, account_id)
        summary = _recompute(db, account_id)
        return {"mode": "sync", **summary}


@router.post("/prospect")
def prospect(body: ProspectRequest, db: PGConn = Depends(get_db),
             user: dict = Depends(get_current_user)):
    """Cluster-seeded prospecting (Section 5): pull a radius of pre-geocoded,
    pre-enriched properties around a seed, refine + dedupe, ingest as leads, and
    score them. Returns a funnel summary (returned → refined → deduped →
    ingested → scored)."""
    from config import RENTCAST_API_KEY, PROPERTY_PROVIDER
    from pipeline import prospecting

    if PROPERTY_PROVIDER == "rentcast" and not RENTCAST_API_KEY:
        raise HTTPException(
            status_code=409,
            detail="Prospecting isn't configured — set RENTCAST_API_KEY.",
        )

    account_id = user["account_id"]
    preset = body.preset
    if preset is None and body.vertical:
        # Fall back to the vertical's configured RentCast filter preset.
        with db.cursor() as cur:
            cur.execute(
                "SELECT prospect_filter_preset FROM vertical_geo_config "
                "WHERE vertical = %s AND (account_id = %s OR account_id IS NULL) "
                "ORDER BY account_id NULLS LAST LIMIT 1",
                (body.vertical, account_id),
            )
            row = cur.fetchone()
        if row and row[0]:
            preset = row[0]

    result = prospecting.prospect(
        db, account_id, body.seed.model_dump(),
        radius_m=body.radius_m, preset=preset, vertical=body.vertical,
        user_id=user["id"],
    )
    if result.get("status") == "unresolved_seed":
        raise HTTPException(status_code=422, detail="Could not resolve the prospecting seed.")
    return result


@router.post("/neighbors")
def neighbors(body: NeighborsRequest, db: PGConn = Depends(get_db),
              user: dict = Depends(get_current_user)):
    """Blast radius around a completed job: ranked open leads within radius_m,
    nearest-and-best first. The door-knock/mail list for visible-work verticals."""
    hits = geo_score_store.blast_radius(
        db, user["account_id"], body.job_id, radius_m=body.radius_m, limit=body.limit
    )
    return {"job_id": body.job_id, "radius_m": body.radius_m, "count": len(hits), "neighbors": hits}


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
