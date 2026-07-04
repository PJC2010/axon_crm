"""
Pure geospatial-scoring math — no database dependency (mirrors pipeline/scoring.py).

The geo layer scores a lead by *where it sits* relative to the tenant's book of
business, then blends that with the property score. Four mechanisms are planned;
Phase 1 ships three of them:

  - proximity : exponential decay on road distance to the nearest active customer
  - density   : count of active customers within a radius (capped)
  - territory : a multiplicative gate that discounts leads outside the service area
  - neighbor  : completed-job "blast radius" — stubbed to 0 here, wired in Phase 3

Every component is 0–100 and the weighted sum is normalized so `geo_score` stays
0–100 for any weight values. `blend_final_score` combines it with the property
score. Distance is haversine × a road-circuity factor — no routing engine at MVP
(see docs/geo_scoring.md for the OSRM upgrade path).

Geometry helpers use GeoJSON coordinate order — (lng, lat) pairs — so service-area
polygons round-trip through the DB unchanged.
"""
import math

from config import (
    GEO_ROAD_CIRCUITY,
    GEO_PROXIMITY_DECAY_KM,
    GEO_DENSITY_RADIUS_M,
    GEO_DENSITY_CAP,
    GEO_NEIGHBOR_FRESH_DAYS,
    GEO_NEIGHBOR_DECAY_DAYS,
    GEO_TERRITORY_GATE_OUT,
    GEO_SERVICE_AREA_BUFFER_KM,
)

EARTH_RADIUS_KM = 6371.0088


# ── Distance ──────────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (straight-line) distance between two lat/lng points, in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def road_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Estimated road distance: straight-line × a circuity factor. The MVP stand-in
    for a routing engine — good enough to rank stops without standing up OSRM."""
    return haversine_km(lat1, lon1, lat2, lon2) * GEO_ROAD_CIRCUITY


# ── Score components (each 0–100) ─────────────────────────────────────────────

def proximity_component(nearest_km: float | None) -> float:
    """Exponential decay on road distance to the nearest active customer.
    100 at the doorstep, ~50 at ~1.4km, →0 far away. No nearby customer → 0."""
    if nearest_km is None or nearest_km < 0:
        return 0.0
    return 100.0 * math.exp(-nearest_km / GEO_PROXIMITY_DECAY_KM)


def density_component(customers_within_radius: int | None) -> float:
    """Linear in the count of active customers within the density radius, capped so
    a dense tenant doesn't run the score away. Cap → 100."""
    if not customers_within_radius or customers_within_radius < 0:
        return 0.0
    return min(customers_within_radius, GEO_DENSITY_CAP) / GEO_DENSITY_CAP * 100.0


def neighbor_component(days_since_completed_job: float | None) -> float:
    """Visible-work contagion: 100 if a job completed within FRESH_DAYS, linear
    decay to 0 at DECAY_DAYS, else 0. Phase 3 populates the input; Phase 1 always
    passes None (→ 0) since there is no jobs table yet."""
    if days_since_completed_job is None or days_since_completed_job < 0:
        return 0.0
    if days_since_completed_job <= GEO_NEIGHBOR_FRESH_DAYS:
        return 100.0
    if days_since_completed_job >= GEO_NEIGHBOR_DECAY_DAYS:
        return 0.0
    span = GEO_NEIGHBOR_DECAY_DAYS - GEO_NEIGHBOR_FRESH_DAYS
    return 100.0 * (1.0 - (days_since_completed_job - GEO_NEIGHBOR_FRESH_DAYS) / span)


def territory_gate(inside_service_area: bool) -> float:
    """Multiplicative gate. 1.0 inside the service area; a heavy (but non-zero)
    penalty outside, so out-of-area leads sink without vanishing — they still
    surface in an expansion view."""
    return 1.0 if inside_service_area else GEO_TERRITORY_GATE_OUT


def geo_score(
    proximity: float,
    density: float,
    neighbor: float,
    route_weight: float,
    neighbor_weight: float,
    gate: float = 1.0,
) -> float:
    """Weighted, normalized blend of the components × the territory gate.

        raw = (route*proximity + route*density + neighbor*neighbor)
              / (2*route + neighbor)
        geo = raw * gate

    Normalizing by the sum of applied weights keeps the result 0–100 regardless of
    the weight magnitudes, so weights are pure relative dials."""
    denom = 2 * route_weight + neighbor_weight
    if denom <= 0:
        return 0.0
    raw = (route_weight * proximity + route_weight * density + neighbor_weight * neighbor) / denom
    return raw * gate


def blend_final_score(property_score: float, geo: float, geo_blend: float) -> float:
    """final = (1 - blend) * property_score + blend * geo_score.
    `geo_blend` is per-vertical (recurring services lean on geo more than one-time
    project work). Both inputs are 0–100, so the result is 0–100."""
    return (1.0 - geo_blend) * (property_score or 0.0) + geo_blend * (geo or 0.0)


def score_geo(row: dict, config: dict) -> dict:
    """Assemble the full geo result from precomputed spatial facts + a config row.

    `row` carries the spatial facts the DB layer measured:
        nearest_customer_km, customers_within_radius, days_since_completed_job,
        inside_service_area, property_score
    `config` carries route_weight / neighbor_weight / geo_blend.

    Returns geo_score, final_score, and the component breakdown stored as JSONB so
    the UI can explain *why* a lead scored the way it did.
    """
    rw = float(config["route_weight"])
    nw = float(config["neighbor_weight"])
    blend = float(config["geo_blend"])

    proximity = round(proximity_component(row.get("nearest_customer_km")), 2)
    density = round(density_component(row.get("customers_within_radius")), 2)
    neighbor = round(neighbor_component(row.get("days_since_completed_job")), 2)
    inside = row.get("inside_service_area", True)
    gate = territory_gate(inside)

    geo = round(geo_score(proximity, density, neighbor, rw, nw, gate), 2)
    final = round(blend_final_score(row.get("property_score") or 0.0, geo, blend), 2)

    return {
        "geo_score": geo,
        "final_score": final,
        "components": {
            "proximity": proximity,
            "density": density,
            "neighbor": neighbor,
            "territory_gate": gate,
            "inside_service_area": bool(inside),
            "route_weight": rw,
            "neighbor_weight": nw,
            "geo_blend": blend,
        },
    }


# ── Geometry (GeoJSON (lng, lat) order) ───────────────────────────────────────

def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Convex hull of (lng, lat) points via Andrew's monotone chain. Returns the
    hull ring (not closed). Fewer than 3 unique points → the unique points as-is
    (a degenerate 'hull' the caller treats as no polygon)."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def point_in_polygon(lng: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon on a ring of (lng, lat) vertices."""
    n = len(ring)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _km_per_deg(lat0: float) -> tuple[float, float]:
    """Local km-per-degree scale (equirectangular) at a reference latitude."""
    return 111.320 * math.cos(math.radians(lat0)), 110.574  # (x per lng°, y per lat°)


def _seg_distance_km(px, py, ax, ay, bx, by, kx, ky) -> float:
    """Distance from point P to segment AB in km, using a local planar projection
    (inputs are (lng, lat); kx/ky are km-per-degree scales)."""
    px, ax, bx = px * kx, ax * kx, bx * kx
    py, ay, by = py * ky, ay * ky, by * ky
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_polygon_km(lng: float, lat: float, ring: list[tuple[float, float]]) -> float:
    """Shortest distance (km) from a point to a polygon boundary. 0 if inside."""
    if not ring:
        return float("inf")
    if point_in_polygon(lng, lat, ring):
        return 0.0
    kx, ky = _km_per_deg(lat)
    n = len(ring)
    best = float("inf")
    for i in range(n):
        ax, ay = ring[i]
        bx, by = ring[(i + 1) % n]
        best = min(best, _seg_distance_km(lng, lat, ax, ay, bx, by, kx, ky))
    return best


def in_service_area(
    lat: float | None,
    lng: float | None,
    polygon: list | None,
    source: str = "derived",
    buffer_km: float = GEO_SERVICE_AREA_BUFFER_KM,
) -> bool:
    """Is a point inside the tenant's service area?

    - No polygon (tenant has too few customers to derive one) → True: don't
      penalize leads when we have no territory to judge against.
    - User-drawn polygon → strict point-in-polygon.
    - Derived polygon (customer convex hull) → inside the hull OR within
      `buffer_km` of it, so leads just past the edge aren't wrongly gated out.
    """
    if not polygon or len(polygon) < 3:
        return True
    if lat is None or lng is None:
        return False
    ring = [(float(x), float(y)) for x, y in polygon]
    if source == "user_drawn":
        return point_in_polygon(lng, lat, ring)
    return distance_to_polygon_km(lng, lat, ring) <= buffer_km


def derive_service_area(customer_points: list[tuple[float, float]]) -> list[list[float]] | None:
    """Convex hull of customer (lat, lng) points as a GeoJSON-style ring of
    [lng, lat] pairs, or None when there are too few points for a polygon. The
    2km buffer is applied at membership time (`in_service_area`), not baked in."""
    lnglat = [(lng, lat) for (lat, lng) in customer_points if lat is not None and lng is not None]
    hull = convex_hull(lnglat)
    if len(hull) < 3:
        return None
    return [[x, y] for (x, y) in hull]


# ── Selection (used by the re-score-on-new-customer trigger) ──────────────────

def nearby_property_ids(
    center: tuple[float, float],
    candidates: list[dict],
    radius_km: float,
) -> list[int]:
    """IDs of candidate properties within `radius_km` (straight-line) of `center`.

    Pure so the "which leads does a new customer trigger a re-score for" rule is
    unit-testable without a database. Each candidate is a dict with id/latitude/
    longitude; those missing coordinates are skipped.
    """
    clat, clng = center
    out = []
    for c in candidates:
        lat, lng = c.get("latitude"), c.get("longitude")
        if lat is None or lng is None:
            continue
        if haversine_km(clat, clng, lat, lng) <= radius_km:
            out.append(c["id"])
    return out
