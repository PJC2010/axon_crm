"""
Tests for the re-score-on-customer-creation behavior and geo config resolution
(pipeline/geo_score_store.py) — the DB-free parts.

The end-to-end trigger (apply_status_change → enqueue_customer_geo_rescore →
rescore_nearby_leads_for_customer) is exercised here at the logic level: the
selection of which leads a new customer touches, and the score effect that
re-scoring produces. Neither needs a live database.
"""
import pytest

import config
from pipeline import geo_scoring
from pipeline.geo_score_store import get_geo_config


# ── get_geo_config resolution + fallback ──────────────────────────────────────

class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self._row


class _FakeConn:
    """Returns a single canned row for any query — enough to exercise the two
    branches of get_geo_config without a database."""
    def __init__(self, row):
        self._row = row

    def cursor(self, *a, **k):
        return _FakeCursor(self._row)


class TestGetGeoConfig:
    def test_none_vertical_uses_default_without_query(self):
        # conn is never touched when vertical is falsy.
        result = get_geo_config(conn=None, account_id=1, vertical=None)
        assert result == config.GEO_DEFAULT_CONFIG

    def test_found_row_is_returned(self):
        row = {"route_weight": 0.9, "neighbor_weight": 0.5, "geo_blend": 0.35}
        result = get_geo_config(_FakeConn(row), account_id=1, vertical="lawn_care")
        assert result == row

    def test_missing_row_falls_back_to_default(self):
        result = get_geo_config(_FakeConn(None), account_id=1, vertical="unknown_vertical")
        assert result == config.GEO_DEFAULT_CONFIG


# ── The trigger's effect: a new customer lifts nearby leads ───────────────────

RECURRING = {"route_weight": 0.9, "neighbor_weight": 0.5, "geo_blend": 0.35}


def _facts(nearest_km, within, property_score=50, inside=True):
    return {
        "nearest_customer_km": nearest_km,
        "customers_within_radius": within,
        "inside_service_area": inside,
        "property_score": property_score,
    }


class TestCustomerCreationEffect:
    def test_new_customer_raises_nearby_lead_final_score(self):
        # Before any customer exists, a lead has no proximity/density signal.
        before = geo_scoring.score_geo(_facts(None, 0), RECURRING)
        # After a customer is won ~150m away, the same lead gains proximity+density.
        after = geo_scoring.score_geo(_facts(0.15, 1), RECURRING)
        assert after["geo_score"] > before["geo_score"]
        assert after["final_score"] > before["final_score"]

    def test_distant_lead_unaffected_by_new_customer(self):
        # A lead 12 km from the new customer sees no proximity/density change.
        before = geo_scoring.score_geo(_facts(None, 0), RECURRING)
        after = geo_scoring.score_geo(_facts(12.0, 0), RECURRING)
        assert after["geo_score"] == pytest.approx(before["geo_score"], abs=0.5)

    def test_only_leads_in_blast_radius_are_selected(self):
        # rescore_nearby_leads_for_customer selects via this pure function.
        customer = (29.70, -95.40)
        leads = [
            {"id": 10, "latitude": 29.7005, "longitude": -95.4005},  # ~0.07 km — in
            {"id": 11, "latitude": 29.74, "longitude": -95.40},      # ~4.5 km  — in
            {"id": 12, "latitude": 29.90, "longitude": -95.40},      # ~22 km   — out
        ]
        selected = geo_scoring.nearby_property_ids(customer, leads, config.GEO_RESCORE_RADIUS_KM)
        assert 10 in selected and 11 in selected
        assert 12 not in selected

    def test_density_climbs_as_customers_cluster(self):
        # More won customers within the radius → higher density component → higher geo.
        one = geo_scoring.score_geo(_facts(0.2, 1), RECURRING)
        many = geo_scoring.score_geo(_facts(0.2, 6), RECURRING)
        assert many["geo_score"] > one["geo_score"]
        assert many["components"]["density"] > one["components"]["density"]
