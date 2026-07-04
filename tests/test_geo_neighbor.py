"""
Tests for the Phase 3 neighbor / visible-work component wiring in
pipeline/geo_score_store.py — the pure pieces (_days_since and _spatial_facts,
which take plain dicts and touch no database).
"""
from datetime import date, datetime, timedelta

import pytest

import config
from pipeline.geo_score_store import _days_since, _spatial_facts


def _cust(id, lat, lng, completed_at=None):
    return {"id": id, "latitude": lat, "longitude": lng, "completed_at": completed_at}


# ── _days_since ───────────────────────────────────────────────────────────────

class TestDaysSince:
    def test_none(self):
        assert _days_since(None) is None

    def test_today_date(self):
        assert _days_since(date.today()) == 0.0

    def test_past_date(self):
        assert _days_since(date.today() - timedelta(days=10)) == pytest.approx(10.0)

    def test_naive_datetime(self):
        d = _days_since(datetime.now() - timedelta(days=5))
        assert d == pytest.approx(5.0, abs=0.01)

    def test_iso_string(self):
        d = _days_since((date.today() - timedelta(days=3)).isoformat())
        assert d == pytest.approx(3.0, abs=1.0)

    def test_malformed_string(self):
        assert _days_since("not-a-date") is None


# ── _spatial_facts neighbor component ─────────────────────────────────────────

# A lead and a customer ~50 m apart (well within the 150 m neighbor radius).
LEAD = {"id": 1, "latitude": 29.7000, "longitude": -95.4000, "lead_score": 50}
CLOSE_LATLNG = (29.70045, -95.4000)   # ~50 m north
FAR_LATLNG = (29.7050, -95.4000)      # ~560 m north (outside neighbor radius)


class TestSpatialFactsNeighbor:
    def test_recent_close_job_sets_neighbor_days(self):
        customers = [_cust(2, *CLOSE_LATLNG, completed_at=date.today() - timedelta(days=10))]
        facts = _spatial_facts(LEAD, customers, ring=None, source="derived")
        assert facts["days_since_completed_job"] == pytest.approx(10.0, abs=1.0)

    def test_job_outside_neighbor_radius_ignored(self):
        customers = [_cust(2, *FAR_LATLNG, completed_at=date.today())]
        facts = _spatial_facts(LEAD, customers, ring=None, source="derived")
        assert facts["days_since_completed_job"] is None

    def test_freshest_job_wins(self):
        customers = [
            _cust(2, *CLOSE_LATLNG, completed_at=date.today() - timedelta(days=40)),
            _cust(3, 29.70040, -95.40001, completed_at=date.today() - timedelta(days=5)),
        ]
        facts = _spatial_facts(LEAD, customers, ring=None, source="derived")
        assert facts["days_since_completed_job"] == pytest.approx(5.0, abs=1.0)

    def test_no_completed_date_yields_none(self):
        customers = [_cust(2, *CLOSE_LATLNG, completed_at=None)]
        facts = _spatial_facts(LEAD, customers, ring=None, source="derived")
        assert facts["days_since_completed_job"] is None

    def test_self_excluded(self):
        # A won lead scored against itself must not count as its own neighbor.
        customers = [_cust(1, LEAD["latitude"], LEAD["longitude"], completed_at=date.today())]
        facts = _spatial_facts(LEAD, customers, ring=None, source="derived")
        assert facts["days_since_completed_job"] is None
        assert facts["customers_within_radius"] == 0

    def test_close_job_also_counts_toward_density_and_proximity(self):
        customers = [_cust(2, *CLOSE_LATLNG, completed_at=date.today())]
        facts = _spatial_facts(LEAD, customers, ring=None, source="derived")
        assert facts["customers_within_radius"] == 1
        assert facts["nearest_customer_km"] is not None and facts["nearest_customer_km"] < 0.1

    def test_neighbor_radius_matches_config(self):
        # Sanity: the neighbor radius used is the configured one.
        assert config.GEO_NEIGHBOR_RADIUS_M == 150
