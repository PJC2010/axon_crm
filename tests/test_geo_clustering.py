"""
Tests for pipeline/geo_clustering.py — pure DBSCAN + cluster building (no DB) —
and pipeline/geo_h3.py where h3 is installed. Mirrors the DB-free style of
tests/test_geo_scoring.py.
"""
import pytest

from pipeline import geo_clustering, geo_h3
from pipeline.geo_clustering import dbscan, build_clusters, cluster_for_point, NOISE


def _pt(i, lat, lng):
    return {"id": i, "latitude": lat, "longitude": lng}


# Two tight pockets ~30 km apart, plus one far-off loner. At eps=800m/minpts=3
# each pocket is its own cluster and the loner is noise.
CLUSTER_A = [_pt(1, 29.7000, -95.4000), _pt(2, 29.7010, -95.4005), _pt(3, 29.7005, -95.3995), _pt(4, 29.7008, -95.4002)]
CLUSTER_B = [_pt(5, 29.9500, -95.6000), _pt(6, 29.9505, -95.6005), _pt(7, 29.9510, -95.5995)]
LONER = [_pt(8, 30.5000, -96.5000)]


class TestDBSCAN:
    def test_finds_two_clusters(self):
        points = CLUSTER_A + CLUSTER_B + LONER
        labels = dbscan(points, eps_m=800, min_points=3)
        # 4 points of A share a label, 3 of B share another, loner is noise.
        a_labels = set(labels[:4])
        b_labels = set(labels[4:7])
        assert len(a_labels) == 1 and NOISE not in a_labels
        assert len(b_labels) == 1 and NOISE not in b_labels
        assert a_labels != b_labels
        assert labels[7] == NOISE

    def test_below_minpoints_is_all_noise(self):
        # Two points can't form a cluster at minpoints=3.
        labels = dbscan(CLUSTER_A[:2], eps_m=800, min_points=3)
        assert labels == [NOISE, NOISE]

    def test_empty(self):
        assert dbscan([], eps_m=800, min_points=3) == []

    def test_large_eps_merges_everything(self):
        # A 200 km eps swallows both pockets and the far loner into one cluster.
        points = CLUSTER_A + CLUSTER_B + LONER
        labels = dbscan(points, eps_m=200_000, min_points=3)
        assert set(labels) == {0}

    def test_labels_are_zero_based_and_contiguous(self):
        points = CLUSTER_A + CLUSTER_B
        labels = dbscan(points, eps_m=800, min_points=3)
        clusters = {l for l in labels if l != NOISE}
        assert clusters == {0, 1}


class TestBuildClusters:
    def test_summary_shape(self):
        points = CLUSTER_A + CLUSTER_B + LONER
        labels = dbscan(points, eps_m=800, min_points=3)
        clusters = build_clusters(points, labels)
        assert len(clusters) == 2
        for c in clusters:
            assert set(c) >= {"cluster_label", "member_ids", "customer_count",
                              "centroid_lat", "centroid_lng", "hull"}
        # Cluster A has 4 members and a 3+-vertex hull.
        a = next(c for c in clusters if 1 in c["member_ids"])
        assert a["customer_count"] == 4
        assert a["hull"] is not None and len(a["hull"]) >= 3

    def test_centroid_within_cluster_bounds(self):
        labels = dbscan(CLUSTER_A, eps_m=800, min_points=3)
        c = build_clusters(CLUSTER_A, labels)[0]
        lats = [p["latitude"] for p in CLUSTER_A]
        lngs = [p["longitude"] for p in CLUSTER_A]
        assert min(lats) <= c["centroid_lat"] <= max(lats)
        assert min(lngs) <= c["centroid_lng"] <= max(lngs)

    def test_noise_excluded(self):
        points = CLUSTER_A + LONER
        labels = dbscan(points, eps_m=800, min_points=3)
        clusters = build_clusters(points, labels)
        assert all(8 not in c["member_ids"] for c in clusters)


class TestClusterForPoint:
    def test_point_inside_hull_gets_label(self):
        labels = dbscan(CLUSTER_A, eps_m=800, min_points=3)
        clusters = build_clusters(CLUSTER_A, labels)
        # A point in the middle of cluster A falls inside its hull.
        label = cluster_for_point(29.7005, -95.4000, clusters)
        assert label == clusters[0]["cluster_label"]

    def test_point_far_away_is_none(self):
        labels = dbscan(CLUSTER_A, eps_m=800, min_points=3)
        clusters = build_clusters(CLUSTER_A, labels)
        assert cluster_for_point(30.5, -96.5, clusters) is None

    def test_missing_coords_is_none(self):
        assert cluster_for_point(None, -95.4, []) is None


@pytest.mark.skipif(not geo_h3.available(), reason="h3 not installed")
class TestH3:
    def test_to_cell_and_back(self):
        cell = geo_h3.to_cell(29.7604, -95.3698)
        assert isinstance(cell, str) and cell
        center = geo_h3.cell_center(cell)
        assert center is not None
        lat, lng = center
        assert abs(lat - 29.7604) < 0.05 and abs(lng - -95.3698) < 0.05

    def test_nearby_points_share_cell(self):
        # Two points ~10 m apart land in the same res-8 hex (~0.74 km²).
        a = geo_h3.to_cell(29.7604, -95.3698)
        b = geo_h3.to_cell(29.7605, -95.3699)
        assert a == b

    def test_boundary_is_ring_of_lng_lat(self):
        cell = geo_h3.to_cell(29.7604, -95.3698)
        boundary = geo_h3.cell_boundary(cell)
        assert boundary and all(len(p) == 2 for p in boundary)
        # lng negative, lat ~29–30 for Houston.
        assert all(p[0] < 0 and 29 < p[1] < 31 for p in boundary)

    def test_missing_coords_returns_none(self):
        assert geo_h3.to_cell(None, -95.37) is None
