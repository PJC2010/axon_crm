"""
Tests for the Phase 4 event layer — the pure scoring pieces in
pipeline/geo_scoring.py: best_event_for_point (polygon containment + bonus
tie-break) and the event bonus in score_geo. No DB.
"""
import pytest

from pipeline.geo_scoring import best_event_for_point, score_geo

# A square event polygon around a point, as a ring of (lng, lat).
SQUARE = [(-95.50, 29.60), (-95.30, 29.60), (-95.30, 29.80), (-95.50, 29.80)]
INSIDE = (29.70, -95.40)   # (lat, lng)
OUTSIDE = (29.70, -90.00)

RECURRING = {"route_weight": 0.9, "neighbor_weight": 0.5, "geo_blend": 0.35}


def _event(id, bonus, ring=SQUARE, event_type="hail_swath", name="Test swath"):
    return {"id": id, "event_type": event_type, "name": name, "bonus": bonus, "ring": ring}


# ── best_event_for_point ──────────────────────────────────────────────────────

class TestBestEventForPoint:
    def test_inside_returns_event(self):
        e = best_event_for_point(*INSIDE, [_event(1, 40)])
        assert e is not None and e["id"] == 1

    def test_outside_returns_none(self):
        assert best_event_for_point(*OUTSIDE, [_event(1, 40)]) is None

    def test_highest_bonus_wins(self):
        e = best_event_for_point(*INSIDE, [_event(1, 20), _event(2, 45), _event(3, 30)])
        assert e["id"] == 2

    def test_missing_coords_none(self):
        assert best_event_for_point(None, -95.4, [_event(1, 40)]) is None

    def test_no_events(self):
        assert best_event_for_point(*INSIDE, []) is None

    def test_event_without_ring_skipped(self):
        assert best_event_for_point(*INSIDE, [{"id": 1, "bonus": 40}]) is None


# ── score_geo event bonus ─────────────────────────────────────────────────────

def _facts(**over):
    base = {"nearest_customer_km": 1.0, "customers_within_radius": 1,
            "inside_service_area": True, "property_score": 40}
    base.update(over)
    return base


class TestScoreGeoEventBonus:
    def test_event_bumps_geo_score(self):
        without = score_geo(_facts(), RECURRING)
        with_ev = score_geo(_facts(event_bonus=40, event={"type": "hail_swath", "id": 1, "name": "x"}), RECURRING)
        assert with_ev["geo_score"] > without["geo_score"]

    def test_event_named_in_breakdown(self):
        r = score_geo(_facts(event_bonus=40, event={"type": "hail_swath", "id": 7, "name": "May hail"}), RECURRING)
        assert r["components"]["event_bonus"] == 40
        assert r["components"]["event"]["type"] == "hail_swath"
        assert r["components"]["event"]["id"] == 7

    def test_no_event_is_zero_bonus(self):
        r = score_geo(_facts(), RECURRING)
        assert r["components"]["event_bonus"] == 0
        assert r["components"]["event"] is None

    def test_geo_score_clamped_to_100(self):
        r = score_geo(_facts(nearest_customer_km=0.0, customers_within_radius=20, event_bonus=90), RECURRING)
        assert r["geo_score"] <= 100.0

    def test_gate_suppresses_event_when_out_of_area(self):
        inside = score_geo(_facts(inside_service_area=True, event_bonus=40), RECURRING)
        outside = score_geo(_facts(inside_service_area=False, event_bonus=40), RECURRING)
        assert outside["geo_score"] < inside["geo_score"]

    def test_bonus_flows_into_final_score(self):
        without = score_geo(_facts(), RECURRING)
        with_ev = score_geo(_facts(event_bonus=40), RECURRING)
        assert with_ev["final_score"] > without["final_score"]
