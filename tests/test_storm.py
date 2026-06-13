"""Tests for pipeline/storm.py — storm report matching and signal logic."""
from datetime import date, timedelta

import pytest

from pipeline.storm import _haversine_mi, _match_property


# ── Haversine ─────────────────────────────────────────────────────────────────

class TestHaversineMi:
    def test_same_point_is_zero(self):
        assert _haversine_mi(29.7604, -95.3698, 29.7604, -95.3698) == pytest.approx(0.0, abs=1e-6)

    def test_downtown_houston_to_galleria_roughly_5mi(self):
        # Downtown Houston → Galleria is ~4.5 miles; haversine should be in that range.
        dist = _haversine_mi(29.7604, -95.3698, 29.7393, -95.4613)
        assert 4.0 < dist < 6.0

    def test_symmetry(self):
        lat1, lon1 = 29.7604, -95.3698
        lat2, lon2 = 29.800, -95.400
        assert _haversine_mi(lat1, lon1, lat2, lon2) == pytest.approx(
            _haversine_mi(lat2, lon2, lat1, lon1), abs=1e-6
        )

    def test_one_degree_latitude_is_roughly_69mi(self):
        dist = _haversine_mi(29.0, -95.0, 30.0, -95.0)
        assert 68 < dist < 70


# ── _match_property ───────────────────────────────────────────────────────────

def _report(days_ago: int, lat: float = 29.7604, lon: float = -95.3698,
            storm_type: str = "hail", hail_size: float | None = 1.0) -> dict:
    return {
        "date": date.today() - timedelta(days=days_ago),
        "storm_type": storm_type,
        "hail_size_in": hail_size,
        "lat": lat,
        "lon": lon,
    }


class TestMatchProperty:
    # Property at downtown Houston
    PROP_LAT = 29.7604
    PROP_LON = -95.3698
    CUTOFF = date.today() - timedelta(days=730)  # 24 months

    def test_no_reports_returns_empty(self):
        result = _match_property(self.PROP_LAT, self.PROP_LON, [], 1.0, self.CUTOFF)
        assert result == {}

    def test_nearby_recent_report_matches(self):
        reports = [_report(30)]  # 30 days ago, same location
        result = _match_property(self.PROP_LAT, self.PROP_LON, reports, 1.0, self.CUTOFF)
        assert result["storm_count_24mo"] == 1
        assert result["last_storm_type"] == "hail"
        assert result["hail_size_in"] == pytest.approx(1.0)

    def test_far_away_report_not_matched(self):
        # 10 miles north — outside 1-mile radius
        reports = [_report(30, lat=29.905, lon=-95.3698)]
        result = _match_property(self.PROP_LAT, self.PROP_LON, reports, 1.0, self.CUTOFF)
        assert result == {}

    def test_report_before_cutoff_not_matched(self):
        old_cutoff = date.today() - timedelta(days=10)  # cutoff only 10 days ago
        reports = [_report(30)]  # 30 days ago — older than cutoff
        result = _match_property(self.PROP_LAT, self.PROP_LON, reports, 1.0, old_cutoff)
        assert result == {}

    def test_most_recent_event_is_last_storm_date(self):
        old = _report(200)
        recent = _report(10)
        result = _match_property(self.PROP_LAT, self.PROP_LON, [old, recent], 1.0, self.CUTOFF)
        assert result["last_storm_date"] == date.today() - timedelta(days=10)

    def test_storm_count_aggregates_all_nearby_events(self):
        reports = [_report(10), _report(100), _report(300)]  # 300 days ago < 24mo
        result = _match_property(self.PROP_LAT, self.PROP_LON, reports, 1.0, self.CUTOFF)
        assert result["storm_count_24mo"] == 3

    def test_max_hail_size_taken(self):
        reports = [
            _report(10, hail_size=0.75),
            _report(50, hail_size=2.0),
            _report(100, hail_size=1.25),
        ]
        result = _match_property(self.PROP_LAT, self.PROP_LON, reports, 1.0, self.CUTOFF)
        assert result["hail_size_in"] == pytest.approx(2.0)

    def test_non_hail_event_hail_size_is_none(self):
        reports = [_report(10, storm_type="wind", hail_size=None)]
        result = _match_property(self.PROP_LAT, self.PROP_LON, reports, 1.0, self.CUTOFF)
        assert result["last_storm_type"] == "wind"
        assert result["hail_size_in"] is None

    def test_wider_radius_captures_more(self):
        # Report ~2 miles away
        reports = [_report(10, lat=29.789, lon=-95.3698)]
        narrow = _match_property(self.PROP_LAT, self.PROP_LON, reports, 1.0, self.CUTOFF)
        wide = _match_property(self.PROP_LAT, self.PROP_LON, reports, 3.0, self.CUTOFF)
        assert narrow == {}
        assert wide["storm_count_24mo"] == 1
