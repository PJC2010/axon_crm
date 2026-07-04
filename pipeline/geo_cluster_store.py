"""
Database orchestration for clustering + H3 (juncto geo layer, Phase 2) — thin SQL
around the pure logic in pipeline/geo_clustering.py and pipeline/geo_h3.py.

`recompute_clusters` runs DBSCAN over an account's customers (won/converted
properties), rewrites its customer_clusters rows and hulls, and stamps each
geo-scored lead with the cluster whose hull contains it. `backfill_h3` fills
properties.h3_r8 so the heatmap can aggregate by hex.
"""
import logging

import psycopg2.extras

from config import (
    CUSTOMER_STATUSES,
    GEO_CLUSTER_EPS_M,
    GEO_CLUSTER_MIN_POINTS,
    GEO_H3_RESOLUTION,
)
from pipeline import geo_clustering, geo_h3

log = logging.getLogger(__name__)


def backfill_h3(conn, account_id: int, resolution: int = GEO_H3_RESOLUTION) -> int:
    """Populate properties.h3_r8 for this account's geocoded rows that lack it.
    No-op (returns 0) when the h3 package isn't installed. Caller owns the txn."""
    if not geo_h3.available():
        log.info("h3 not installed — skipping h3 backfill for account %d", account_id)
        return 0

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, latitude, longitude FROM properties "
            "WHERE account_id = %s AND latitude IS NOT NULL AND longitude IS NOT NULL "
            "  AND h3_r8 IS NULL AND archived_at IS NULL",
            (account_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    updates = []
    for r in rows:
        cell = geo_h3.to_cell(r["latitude"], r["longitude"], resolution)
        if cell:
            updates.append((cell, r["id"], account_id))
    if updates:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE properties SET h3_r8 = %s WHERE id = %s AND account_id = %s",
                updates,
            )
    conn.commit()
    log.info("H3 backfill: %d row(s) for account %d", len(updates), account_id)
    return len(updates)


def load_customer_points(conn, account_id: int) -> list[dict]:
    """Active customers with coordinates: {id, latitude, longitude}."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, latitude, longitude FROM properties "
            "WHERE account_id = %s AND status = ANY(%s) "
            "  AND latitude IS NOT NULL AND longitude IS NOT NULL AND archived_at IS NULL",
            (account_id, list(CUSTOMER_STATUSES)),
        )
        return [dict(r) for r in cur.fetchall()]


def recompute_clusters(conn, account_id: int) -> dict:
    """Re-run DBSCAN for an account: rewrite customer_clusters and stamp each
    geo-scored lead's cluster_id. Returns a {clusters, customers, leads_tagged}
    summary. Caller owns the transaction."""
    customers = load_customer_points(conn, account_id)
    labels = geo_clustering.dbscan(customers, GEO_CLUSTER_EPS_M, GEO_CLUSTER_MIN_POINTS)
    clusters = geo_clustering.build_clusters(customers, labels)

    # Rewrite this account's clusters as a set — a stable snapshot the map and the
    # prospecting flow read from.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM customer_clusters WHERE account_id = %s", (account_id,))
        for c in clusters:
            hull_geojson = _geojson_polygon(c["hull"]) if c["hull"] else None
            cur.execute(
                "INSERT INTO customer_clusters "
                "(account_id, cluster_label, hull, centroid_lat, centroid_lng, customer_count) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (account_id, c["cluster_label"],
                 psycopg2.extras.Json(hull_geojson) if hull_geojson else None,
                 c["centroid_lat"], c["centroid_lng"], c["customer_count"]),
            )

    # Stamp cluster membership onto geo-scored leads (rows that exist in
    # lead_geo_scores). Leads clear to NULL first so a lead that left every hull
    # doesn't keep a stale cluster_id.
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("UPDATE lead_geo_scores SET cluster_id = NULL WHERE account_id = %s", (account_id,))
        cur.execute(
            "SELECT p.id, p.latitude, p.longitude FROM properties p "
            "JOIN lead_geo_scores lgs ON lgs.property_id = p.id "
            "WHERE p.account_id = %s AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL",
            (account_id,),
        )
        scored = [dict(r) for r in cur.fetchall()]

    tag_updates = []
    for lead in scored:
        label = geo_clustering.cluster_for_point(lead["latitude"], lead["longitude"], clusters)
        if label is not None:
            tag_updates.append((label, lead["id"], account_id))
    if tag_updates:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE lead_geo_scores SET cluster_id = %s "
                "WHERE property_id = %s AND account_id = %s",
                tag_updates,
            )

    conn.commit()
    summary = {"clusters": len(clusters), "customers": len(customers), "leads_tagged": len(tag_updates)}
    log.info("Clustered account %d: %s", account_id, summary)
    return summary


# ── GeoJSON helper ────────────────────────────────────────────────────────────

def _geojson_polygon(ring: list) -> dict:
    coords = [list(p) for p in ring]
    if coords and coords[0] != coords[-1]:
        coords.append(list(coords[0]))
    return {"type": "Polygon", "coordinates": [coords]}
