"""
Database orchestration for the geo scoring layer (thin SQL around the pure math
in pipeline/geo_scoring.py, the same split as account_rescore.py).

"Customers" are properties in a won/converted status (config.CUSTOMER_STATUSES);
their locations drive proximity and density. Each lead is scored against the
account's customer set and service area, and the result — geo_score, blended
final_score, and the component breakdown — is upserted into lead_geo_scores.

Distance is haversine × road-circuity (no PostGIS). At Phase 1 scale the
per-lead nearest-customer search is a straightforward O(leads × customers) scan
in Python; the docs note the PostGIS/GIST upgrade path for larger books.
"""
import logging
from datetime import date, datetime

import psycopg2.extras

from config import (
    CUSTOMER_STATUSES,
    GEO_DENSITY_RADIUS_M,
    GEO_NEIGHBOR_RADIUS_M,
    GEO_RESCORE_RADIUS_KM,
    GEO_SERVICE_AREA_BUFFER_KM,
    GEO_ROAD_CIRCUITY,
    GEO_DEFAULT_CONFIG,
)
from pipeline import geo_scoring

log = logging.getLogger(__name__)


# ── Config resolution ─────────────────────────────────────────────────────────

def get_geo_config(conn, account_id: int, vertical: str | None) -> dict:
    """Resolve the geo config for a lead: tenant override for its vertical, else
    the platform default for that vertical, else config.GEO_DEFAULT_CONFIG. Mirrors
    how scorer.score_zip falls back to DEFAULT_WEIGHTS for unknown verticals."""
    if vertical:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT route_weight, neighbor_weight, geo_blend "
                "FROM vertical_geo_config "
                "WHERE vertical = %s AND (account_id = %s OR account_id IS NULL) "
                "ORDER BY account_id NULLS LAST LIMIT 1",  # override (non-null) wins
                (vertical, account_id),
            )
            row = cur.fetchone()
        if row:
            return dict(row)
    return dict(GEO_DEFAULT_CONFIG)


def _config_cache(conn, account_id: int):
    """Memoize config lookups by vertical for a single rescore pass."""
    cache: dict = {}

    def resolve(vertical: str | None) -> dict:
        key = vertical or "__default__"
        if key not in cache:
            cache[key] = get_geo_config(conn, account_id, vertical)
        return cache[key]

    return resolve


# ── Customers + service area ──────────────────────────────────────────────────

def load_customers(conn, account_id: int) -> list[dict]:
    """Active customers with coordinates: {id, latitude, longitude, completed_at}.

    completed_at (stage_moved_at, when the lead reached its terminal won/converted
    state) dates the "completed job" for the neighbor / visible-work component.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, latitude, longitude, stage_moved_at AS completed_at FROM properties "
            "WHERE account_id = %s AND status = ANY(%s) "
            "  AND latitude IS NOT NULL AND longitude IS NOT NULL "
            "  AND archived_at IS NULL",
            (account_id, list(CUSTOMER_STATUSES)),
        )
        return [dict(r) for r in cur.fetchall()]


def get_service_area(conn, account_id: int, customers: list[dict] | None = None) -> tuple[list | None, str]:
    """Return (polygon_ring, source) for the account. A user-drawn/stored area
    wins; otherwise derive the customer convex hull on the fly. `customers` may be
    passed to avoid a second query during a rescore pass."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT polygon, source FROM service_areas WHERE account_id = %s "
            "ORDER BY (source = 'user_drawn') DESC, computed_at DESC LIMIT 1",
            (account_id,),
        )
        row = cur.fetchone()
    if row:
        return _ring_from_geojson(row["polygon"]), row["source"]

    if customers is None:
        customers = load_customers(conn, account_id)
    ring = geo_scoring.derive_service_area([(c["latitude"], c["longitude"]) for c in customers])
    return ring, "derived"


def refresh_service_area(conn, account_id: int) -> bool:
    """Recompute and persist the DERIVED service area from current customers.
    Leaves a user_drawn area untouched. Returns True if a derived area was stored."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM service_areas WHERE account_id = %s AND source = 'user_drawn' LIMIT 1",
            (account_id,),
        )
        if cur.fetchone():
            return False

    customers = load_customers(conn, account_id)
    ring = geo_scoring.derive_service_area([(c["latitude"], c["longitude"]) for c in customers])
    if not ring:
        return False

    geojson = _geojson_from_ring(ring)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM service_areas WHERE account_id = %s AND source = 'derived'", (account_id,))
        cur.execute(
            "INSERT INTO service_areas (account_id, polygon, source) VALUES (%s, %s, 'derived')",
            (account_id, psycopg2.extras.Json(geojson)),
        )
    conn.commit()
    return True


# ── Scoring ───────────────────────────────────────────────────────────────────

def _spatial_facts(lead: dict, customers: list[dict], ring: list | None, source: str) -> dict:
    """Measure the spatial inputs the score needs for one lead."""
    lat, lng = lead["latitude"], lead["longitude"]
    density_km = GEO_DENSITY_RADIUS_M / 1000.0
    neighbor_km = GEO_NEIGHBOR_RADIUS_M / 1000.0

    nearest_km = None
    within = 0
    neighbor_days = None  # freshest completed job within the neighbor radius
    for c in customers:
        if c["id"] == lead["id"]:
            continue  # a won lead is itself a customer — don't score it against itself
        straight = geo_scoring.haversine_km(lat, lng, c["latitude"], c["longitude"])
        if straight <= density_km:
            within += 1
        road = straight * GEO_ROAD_CIRCUITY
        if nearest_km is None or road < nearest_km:
            nearest_km = road
        # Visible-work contagion: a completed job the prospect can see, within a
        # tight radius. Keep the most recent one.
        if straight <= neighbor_km:
            days = _days_since(c.get("completed_at"))
            if days is not None and (neighbor_days is None or days < neighbor_days):
                neighbor_days = days

    inside = geo_scoring.in_service_area(lat, lng, ring, source, GEO_SERVICE_AREA_BUFFER_KM)
    return {
        "nearest_customer_km": nearest_km,
        "customers_within_radius": within,
        "days_since_completed_job": neighbor_days,
        "inside_service_area": inside,
        "property_score": lead.get("lead_score") or 0.0,
    }


def _days_since(when) -> float | None:
    """Whole days since a timestamp/date, or None. Tolerant of date, datetime
    (naive or tz-aware), and ISO strings so it works across cursor factories."""
    if when is None:
        return None
    try:
        if isinstance(when, str):
            when = datetime.fromisoformat(when)
        if isinstance(when, datetime):
            now = datetime.now(when.tzinfo) if when.tzinfo else datetime.now()
            return max(0.0, (now - when).total_seconds() / 86400.0)
        if isinstance(when, date):
            return max(0.0, float((date.today() - when).days))
    except (ValueError, TypeError):
        return None
    return None


def _score_and_store(conn, account_id: int, leads: list[dict], customers: list[dict],
                     ring: list | None, source: str, resolve_config) -> int:
    """Score `leads` and upsert into lead_geo_scores. Caller owns transaction."""
    upserts = []
    for lead in leads:
        if lead["latitude"] is None or lead["longitude"] is None:
            continue  # can't geo-score without coordinates — leave for the geocode queue
        facts = _spatial_facts(lead, customers, ring, source)
        config = resolve_config(lead.get("vertical"))
        result = geo_scoring.score_geo(facts, config)
        nearest_m = round(facts["nearest_customer_km"] * 1000) if facts["nearest_customer_km"] is not None else None
        upserts.append((
            lead["id"], account_id, result["geo_score"], result["final_score"],
            psycopg2.extras.Json(result["components"]), nearest_m,
            facts["customers_within_radius"],
        ))

    if upserts:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO lead_geo_scores "
                "(property_id, account_id, geo_score, final_score, components, "
                " nearest_customer_m, customers_within_1600m, scored_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW()) "
                "ON CONFLICT (property_id) DO UPDATE SET "
                "  geo_score = EXCLUDED.geo_score, final_score = EXCLUDED.final_score, "
                "  components = EXCLUDED.components, nearest_customer_m = EXCLUDED.nearest_customer_m, "
                "  customers_within_1600m = EXCLUDED.customers_within_1600m, scored_at = NOW()",
                upserts,
            )
    return len(upserts)


def rescore_leads(conn, account_id: int, property_ids: list[int] | None = None) -> int:
    """Recompute geo + final scores for an account's leads (all non-archived leads
    when `property_ids` is None). Returns the number of leads scored. Caller-facing
    entry point for the batch endpoint and the nightly job."""
    customers = load_customers(conn, account_id)
    ring, source = get_service_area(conn, account_id, customers)
    resolve_config = _config_cache(conn, account_id)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if property_ids is not None:
            if not property_ids:
                return 0
            cur.execute(
                "SELECT id, latitude, longitude, vertical, lead_score FROM properties "
                "WHERE account_id = %s AND id = ANY(%s) AND archived_at IS NULL",
                (account_id, property_ids),
            )
        else:
            cur.execute(
                "SELECT id, latitude, longitude, vertical, lead_score FROM properties "
                "WHERE account_id = %s AND archived_at IS NULL",
                (account_id,),
            )
        leads = [dict(r) for r in cur.fetchall()]

    n = _score_and_store(conn, account_id, leads, customers, ring, source, resolve_config)
    conn.commit()
    log.info("Geo-scored %d lead(s) for account %d", n, account_id)
    return n


def rescore_nearby_leads_for_customer(conn, account_id: int, customer_id: int,
                                      radius_km: float = GEO_RESCORE_RADIUS_KM) -> int:
    """Re-score every lead within `radius_km` of a customer — the blast radius that
    fires when a lead becomes a customer (won/converted). Pure selection logic is
    geo_scoring.nearby_property_ids, unit-tested without a DB."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT latitude, longitude FROM properties WHERE id = %s AND account_id = %s",
            (customer_id, account_id),
        )
        cust = cur.fetchone()
        if not cust or cust["latitude"] is None or cust["longitude"] is None:
            return 0
        cur.execute(
            "SELECT id, latitude, longitude FROM properties "
            "WHERE account_id = %s AND archived_at IS NULL "
            "  AND latitude IS NOT NULL AND longitude IS NOT NULL",
            (account_id,),
        )
        candidates = [dict(r) for r in cur.fetchall()]

    ids = geo_scoring.nearby_property_ids(
        (cust["latitude"], cust["longitude"]), candidates, radius_km
    )
    if not ids:
        return 0
    return rescore_leads(conn, account_id, property_ids=ids)


# ── Neighbor "blast radius" (Phase 3) ─────────────────────────────────────────

def blast_radius(conn, account_id: int, job_id: int, radius_m: float = GEO_NEIGHBOR_RADIUS_M,
                 limit: int = 25) -> list[dict]:
    """Ranked door-knock/mail targets around a just-completed job.

    Returns open (non-terminal, unarchived) leads within `radius_m` of the job
    property, nearest-and-best first — ordered by distance then blended score.
    This is the radius-precise complement to api/neighbors.find_neighbors (which
    buckets by geohash cell); the geo layer measures true distance.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT latitude, longitude FROM properties WHERE id = %s AND account_id = %s",
            (job_id, account_id),
        )
        job = cur.fetchone()
        if not job or job["latitude"] is None or job["longitude"] is None:
            return []
        cur.execute(
            "SELECT p.id, p.address, p.zip, p.latitude, p.longitude, p.status, "
            "       p.score_grade, p.vertical, "
            "       COALESCE(lgs.final_score, p.lead_score) AS final_score "
            "FROM properties p LEFT JOIN lead_geo_scores lgs ON lgs.property_id = p.id "
            "WHERE p.account_id = %s AND p.id <> %s AND p.archived_at IS NULL "
            "  AND p.status NOT IN ('won','lost','not_interested','converted') "
            "  AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL",
            (account_id, job_id),
        )
        candidates = [dict(r) for r in cur.fetchall()]

    radius_km = radius_m / 1000.0
    hits = []
    for c in candidates:
        d_km = geo_scoring.haversine_km(job["latitude"], job["longitude"], c["latitude"], c["longitude"])
        if d_km <= radius_km:
            c["distance_m"] = round(d_km * 1000)
            c["final_score"] = float(c["final_score"]) if c["final_score"] is not None else None
            hits.append(c)

    hits.sort(key=lambda h: (h["distance_m"], -(h["final_score"] or 0)))
    return hits[:limit]


# ── GeoJSON helpers ───────────────────────────────────────────────────────────

def _geojson_from_ring(ring: list) -> dict:
    """Ring of [lng, lat] pairs → a closed GeoJSON Polygon."""
    coords = [list(p) for p in ring]
    if coords and coords[0] != coords[-1]:
        coords.append(list(coords[0]))
    return {"type": "Polygon", "coordinates": [coords]}


def _ring_from_geojson(geojson) -> list | None:
    """GeoJSON Polygon → open ring of [lng, lat] pairs (drops the closing point)."""
    if not geojson:
        return None
    coords = (geojson.get("coordinates") or [None])[0] if isinstance(geojson, dict) else None
    if not coords:
        return None
    ring = [tuple(p) for p in coords]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring or None
