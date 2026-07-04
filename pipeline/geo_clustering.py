"""
Pure customer clustering — DBSCAN over haversine distance, no database.

The PostGIS-free stand-in for `ST_ClusterDBSCAN` (juncto geo layer, Phase 2). Runs
per account over the tenant's customer points to find dense pockets of business,
then builds each cluster's convex hull for the map overlay and the "prospect this
area" flow. eps is in meters and `min_points` includes the point itself, matching
the plan's Section 6 example (eps 800m, minpoints 3) and PostGIS semantics.

Complexity is O(n²) in the customer count — fine at per-account scale; the
docs note the PostGIS/GIST upgrade path for very large books.
"""
from pipeline.geo_scoring import haversine_km, convex_hull, point_in_polygon

NOISE = -1


def dbscan(points: list[dict], eps_m: float, min_points: int) -> list[int]:
    """Label each point with a 0-based cluster id, or NOISE (-1).

    `points` is an ordered list of dicts with `latitude`/`longitude`. Returns a
    label list parallel to `points`. A point is a core point when at least
    `min_points` points (itself included) lie within `eps_m` meters.
    """
    eps_km = eps_m / 1000.0
    n = len(points)
    labels: list[int | None] = [None] * n  # None = unvisited

    def region(i: int) -> list[int]:
        pi = points[i]
        lat, lng = pi["latitude"], pi["longitude"]
        return [
            j for j in range(n)
            if haversine_km(lat, lng, points[j]["latitude"], points[j]["longitude"]) <= eps_km
        ]

    cluster_id = -1
    for i in range(n):
        if labels[i] is not None:
            continue
        neighbors = region(i)
        if len(neighbors) < min_points:
            labels[i] = NOISE
            continue
        cluster_id += 1
        labels[i] = cluster_id
        # Expand the cluster. `seeds` grows as new core points are found; a set
        # tracks membership so points are never enqueued twice.
        seeds = [j for j in neighbors if j != i]
        in_seeds = set(seeds)
        k = 0
        while k < len(seeds):
            j = seeds[k]
            k += 1
            if labels[j] == NOISE:
                labels[j] = cluster_id  # border point picked up by this cluster
            if labels[j] is not None:
                continue
            labels[j] = cluster_id
            j_neighbors = region(j)
            if len(j_neighbors) >= min_points:  # j is itself a core point
                for m in j_neighbors:
                    if m not in in_seeds:
                        in_seeds.add(m)
                        seeds.append(m)

    return [NOISE if lbl is None else lbl for lbl in labels]


def build_clusters(points: list[dict], labels: list[int]) -> list[dict]:
    """Group labeled points into cluster summaries.

    Returns one dict per non-noise cluster:
        {cluster_label, member_ids, customer_count, centroid_lat, centroid_lng,
         hull}  — hull is a GeoJSON-style ring of [lng, lat] pairs (None for a
        cluster with fewer than 3 hull vertices).
    """
    by_label: dict[int, list[dict]] = {}
    for point, label in zip(points, labels):
        if label == NOISE:
            continue
        by_label.setdefault(label, []).append(point)

    clusters = []
    for label in sorted(by_label):
        members = by_label[label]
        lats = [m["latitude"] for m in members]
        lngs = [m["longitude"] for m in members]
        hull_ring = convex_hull([(lng, lat) for lat, lng in zip(lats, lngs)])
        hull = [[x, y] for (x, y) in hull_ring] if len(hull_ring) >= 3 else None
        clusters.append({
            "cluster_label": label,
            "member_ids": [m["id"] for m in members],
            "customer_count": len(members),
            "centroid_lat": sum(lats) / len(lats),
            "centroid_lng": sum(lngs) / len(lngs),
            "hull": hull,
        })
    return clusters


def cluster_for_point(lat: float | None, lng: float | None, clusters: list[dict]) -> int | None:
    """The label of the first cluster whose hull contains the point, else None.
    Used to stamp a lead with its cluster membership."""
    if lat is None or lng is None:
        return None
    for cluster in clusters:
        hull = cluster.get("hull")
        if hull and point_in_polygon(lng, lat, [(x, y) for x, y in hull]):
            return cluster["cluster_label"]
    return None
