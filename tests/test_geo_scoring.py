"""
Tests for pipeline/geo_scoring.py — pure geospatial-scoring math (no database).

Covers the decay curve, density cap, neighbor decay, territory gate, weighted
normalization, the property/geo blend, and the geometry helpers (convex hull,
point-in-polygon, service-area membership). Mirrors tests/test_scoring.py: these
lock in current behavior and must pass without a DB connection.
"""
import math

import pytest

import config
import pipeline.geo_scoring as geo
from pipeline.geo_scoring import (
    haversine_km,
    road_distance_km,
    proximity_component,
    density_component,
    neighbor_component,
    territory_gate,
    geo_score,
    blend_final_score,
    score_geo,
    convex_hull,
    point_in_polygon,
    in_service_area,
    derive_service_area,
    nearby_property_ids,
)


# ── haversine / road distance ─────────────────────────────────────────────────

class TestDistance:
    def test_zero_distance(self):
        assert haversine_km(29.76, -95.37, 29.76, -95.37) == pytest.approx(0.0)

    def test_known_one_degree_lat(self):
        # 1° of latitude ≈ 111 km anywhere on Earth.
        d = haversine_km(0.0, 0.0, 1.0, 0.0)
        assert d == pytest.approx(111.19, abs=0.5)

    def test_symmetric(self):
        a = haversine_km(29.7, -95.4, 30.1, -95.1)
        b = haversine_km(30.1, -95.1, 29.7, -95.4)
        assert a == pytest.approx(b)

    def test_road_applies_circuity(self):
        straight = haversine_km(29.70, -95.40, 29.72, -95.40)
        road = road_distance_km(29.70, -95.40, 29.72, -95.40)
        assert road == pytest.approx(straight * config.GEO_ROAD_CIRCUITY)


# ── proximity_component (exponential decay) ───────────────────────────────────

class TestProximity:
    def test_none_is_zero(self):
        assert proximity_component(None) == 0.0

    def test_negative_is_zero(self):
        assert proximity_component(-1.0) == 0.0

    def test_at_doorstep_is_100(self):
        assert proximity_component(0.0) == pytest.approx(100.0)

    def test_one_decay_length(self):
        # d = decay_km → 100*e^-1 ≈ 36.79
        assert proximity_component(config.GEO_PROXIMITY_DECAY_KM) == pytest.approx(100 * math.exp(-1))

    def test_half_life_point(self):
        # score 50 at d = decay * ln(2)
        d = config.GEO_PROXIMITY_DECAY_KM * math.log(2)
        assert proximity_component(d) == pytest.approx(50.0, abs=0.01)

    def test_monotonic_decreasing(self):
        vals = [proximity_component(d) for d in (0.1, 0.5, 1.0, 2.0, 4.0, 8.0)]
        assert vals == sorted(vals, reverse=True)

    def test_far_away_near_zero(self):
        assert proximity_component(20.0) < 0.01


# ── density_component (capped linear) ─────────────────────────────────────────

class TestDensity:
    def test_none_is_zero(self):
        assert density_component(None) == 0.0

    def test_zero_is_zero(self):
        assert density_component(0) == 0.0

    def test_negative_is_zero(self):
        assert density_component(-3) == 0.0

    def test_one_of_cap(self):
        assert density_component(1) == pytest.approx(1 / config.GEO_DENSITY_CAP * 100)

    def test_at_cap_is_100(self):
        assert density_component(config.GEO_DENSITY_CAP) == pytest.approx(100.0)

    def test_above_cap_clamped(self):
        assert density_component(config.GEO_DENSITY_CAP * 5) == pytest.approx(100.0)


# ── neighbor_component (visible-work decay) ───────────────────────────────────

class TestNeighbor:
    def test_none_is_zero(self):
        assert neighbor_component(None) == 0.0

    def test_negative_is_zero(self):
        assert neighbor_component(-5) == 0.0

    def test_fresh_is_100(self):
        assert neighbor_component(0) == 100.0
        assert neighbor_component(config.GEO_NEIGHBOR_FRESH_DAYS) == 100.0

    def test_past_decay_is_zero(self):
        assert neighbor_component(config.GEO_NEIGHBOR_DECAY_DAYS) == 0.0
        assert neighbor_component(config.GEO_NEIGHBOR_DECAY_DAYS + 30) == 0.0

    def test_midpoint_linear(self):
        fresh, decay = config.GEO_NEIGHBOR_FRESH_DAYS, config.GEO_NEIGHBOR_DECAY_DAYS
        mid = (fresh + decay) / 2
        assert neighbor_component(mid) == pytest.approx(50.0)


# ── territory_gate ────────────────────────────────────────────────────────────

class TestTerritoryGate:
    def test_inside_is_one(self):
        assert territory_gate(True) == 1.0

    def test_outside_is_penalty(self):
        assert territory_gate(False) == config.GEO_TERRITORY_GATE_OUT

    def test_gate_multiplies_geo_score(self):
        inside = geo_score(100, 100, 0, 0.9, 0.5, territory_gate(True))
        outside = geo_score(100, 100, 0, 0.9, 0.5, territory_gate(False))
        assert outside == pytest.approx(inside * config.GEO_TERRITORY_GATE_OUT)


# ── geo_score (weighted, normalized) ──────────────────────────────────────────

class TestGeoScore:
    def test_all_components_max_is_100(self):
        # Every component at 100 must yield exactly 100, whatever the weights.
        assert geo_score(100, 100, 100, 0.9, 0.5) == pytest.approx(100.0)
        assert geo_score(100, 100, 100, 0.2, 0.9) == pytest.approx(100.0)

    def test_all_components_zero_is_zero(self):
        assert geo_score(0, 0, 0, 0.9, 0.5) == 0.0

    def test_stays_in_range_for_any_weights(self):
        for rw in (0.1, 0.5, 0.9):
            for nw in (0.1, 0.5, 0.9):
                s = geo_score(80, 40, 20, rw, nw)
                assert 0.0 <= s <= 100.0

    def test_normalization_formula(self):
        rw, nw = 0.9, 0.5
        prox, dens, neigh = 100, 60, 0
        expected = (rw * prox + rw * dens + nw * neigh) / (2 * rw + nw)
        assert geo_score(prox, dens, neigh, rw, nw) == pytest.approx(expected)

    def test_zero_weights_is_zero(self):
        assert geo_score(100, 100, 100, 0.0, 0.0) == 0.0

    def test_neighbor_weight_pulls_toward_neighbor(self):
        # Project vertical (high neighbor weight) rewards a fresh neighbor job more
        # than a recurring vertical (low neighbor weight) does.
        project = geo_score(0, 0, 100, 0.2, 0.8)
        recurring = geo_score(0, 0, 100, 0.9, 0.3)
        assert project > recurring


# ── blend_final_score ─────────────────────────────────────────────────────────

class TestBlend:
    def test_zero_blend_is_property_score(self):
        assert blend_final_score(70, 20, 0.0) == pytest.approx(70.0)

    def test_full_blend_is_geo_score(self):
        assert blend_final_score(70, 20, 1.0) == pytest.approx(20.0)

    def test_default_blend(self):
        b = config.GEO_BLEND_RECURRING
        assert blend_final_score(80, 40, b) == pytest.approx((1 - b) * 80 + b * 40)

    def test_none_inputs_safe(self):
        assert blend_final_score(None, None, 0.35) == 0.0


# ── score_geo (integration) ───────────────────────────────────────────────────

RECURRING_CONFIG = {"route_weight": 0.9, "neighbor_weight": 0.5, "geo_blend": 0.35}


class TestScoreGeo:
    def test_breakdown_keys(self):
        row = {"nearest_customer_km": 0.1, "customers_within_radius": 3,
               "inside_service_area": True, "property_score": 60}
        result = score_geo(row, RECURRING_CONFIG)
        assert set(result) == {"geo_score", "final_score", "components"}
        assert set(result["components"]) >= {"proximity", "density", "neighbor",
                                             "territory_gate", "route_weight", "neighbor_weight"}

    def test_near_beats_far_identical_lead(self):
        # The moat: an identical property near the customer book outscores one far
        # from it. This is the core acceptance criterion for Phase 1.
        near = score_geo({"nearest_customer_km": 0.15, "customers_within_radius": 4,
                          "inside_service_area": True, "property_score": 50}, RECURRING_CONFIG)
        far = score_geo({"nearest_customer_km": 12.0, "customers_within_radius": 0,
                         "inside_service_area": True, "property_score": 50}, RECURRING_CONFIG)
        assert near["geo_score"] > far["geo_score"]
        assert near["final_score"] > far["final_score"]

    def test_outside_service_area_is_gated_down(self):
        base = {"nearest_customer_km": 0.2, "customers_within_radius": 5, "property_score": 50}
        inside = score_geo({**base, "inside_service_area": True}, RECURRING_CONFIG)
        outside = score_geo({**base, "inside_service_area": False}, RECURRING_CONFIG)
        assert outside["geo_score"] < inside["geo_score"]
        assert outside["components"]["territory_gate"] == config.GEO_TERRITORY_GATE_OUT

    def test_final_score_in_range(self):
        result = score_geo({"nearest_customer_km": 0.0, "customers_within_radius": 20,
                            "inside_service_area": True, "property_score": 100}, RECURRING_CONFIG)
        assert 0.0 <= result["final_score"] <= 100.0

    def test_no_customers_zero_geo(self):
        result = score_geo({"nearest_customer_km": None, "customers_within_radius": 0,
                            "inside_service_area": True, "property_score": 40}, RECURRING_CONFIG)
        assert result["geo_score"] == 0.0
        # Final still reflects the property score through the blend.
        assert result["final_score"] == pytest.approx((1 - 0.35) * 40)


# ── Geometry ──────────────────────────────────────────────────────────────────

class TestGeometry:
    def test_convex_hull_of_square(self):
        # Interior point is dropped; the 4 corners remain.
        pts = [(0, 0), (0, 1), (1, 0), (1, 1), (0.5, 0.5)]
        hull = convex_hull(pts)
        assert len(hull) == 4
        assert (0.5, 0.5) not in hull

    def test_hull_too_few_points(self):
        assert len(convex_hull([(0, 0), (1, 1)])) == 2

    def test_point_in_polygon_inside(self):
        square = [(0, 0), (2, 0), (2, 2), (0, 2)]
        assert point_in_polygon(1, 1, square) is True

    def test_point_in_polygon_outside(self):
        square = [(0, 0), (2, 0), (2, 2), (0, 2)]
        assert point_in_polygon(3, 3, square) is False

    def test_in_service_area_none_polygon_is_inside(self):
        # No derived area yet → don't penalize.
        assert in_service_area(29.7, -95.4, None) is True

    def test_in_service_area_user_drawn_strict(self):
        # A small polygon; a point clearly outside is out for user_drawn areas.
        poly = [[-95.5, 29.6], [-95.3, 29.6], [-95.3, 29.8], [-95.5, 29.8]]
        assert in_service_area(29.7, -95.4, poly, source="user_drawn") is True
        assert in_service_area(29.7, -90.0, poly, source="user_drawn") is False

    def test_derived_area_applies_buffer(self):
        # A point just outside the hull but within the buffer counts as inside for
        # a derived area, but not for a user-drawn one.
        poly = [[-95.50, 29.60], [-95.30, 29.60], [-95.30, 29.80], [-95.50, 29.80]]
        # ~1km east of the eastern edge (0.30° lng span handled by buffer at 2km).
        just_outside_lng = -95.30 + 0.005  # ~0.5 km east at this latitude
        assert in_service_area(29.70, just_outside_lng, poly, source="derived") is True
        assert in_service_area(29.70, just_outside_lng, poly, source="user_drawn") is False

    def test_derive_service_area_returns_geojson_ring(self):
        # (lat, lng) customer points → ring of [lng, lat] pairs.
        customers = [(29.6, -95.5), (29.6, -95.3), (29.8, -95.3), (29.8, -95.5), (29.7, -95.4)]
        ring = derive_service_area(customers)
        assert ring is not None
        assert all(len(p) == 2 for p in ring)
        # coordinates are [lng, lat] — lng is negative here, lat is ~29–30.
        assert all(p[0] < 0 and 29 < p[1] < 31 for p in ring)

    def test_derive_service_area_too_few_points(self):
        assert derive_service_area([(29.7, -95.4), (29.8, -95.3)]) is None


# ── nearby_property_ids (re-score selection) ──────────────────────────────────

class TestNearbyPropertyIds:
    def test_selects_within_radius(self):
        center = (29.70, -95.40)
        candidates = [
            {"id": 1, "latitude": 29.701, "longitude": -95.401},   # ~0.15 km
            {"id": 2, "latitude": 29.80, "longitude": -95.40},     # ~11 km
            {"id": 3, "latitude": 29.705, "longitude": -95.405},   # ~0.7 km
        ]
        ids = nearby_property_ids(center, candidates, radius_km=8.0)
        assert set(ids) == {1, 3}

    def test_skips_missing_coords(self):
        center = (29.70, -95.40)
        candidates = [
            {"id": 1, "latitude": None, "longitude": -95.40},
            {"id": 2, "latitude": 29.70, "longitude": None},
            {"id": 3, "latitude": 29.7001, "longitude": -95.4001},
        ]
        assert nearby_property_ids(center, candidates, radius_km=8.0) == [3]

    def test_empty_candidates(self):
        assert nearby_property_ids((29.7, -95.4), [], radius_km=8.0) == []
