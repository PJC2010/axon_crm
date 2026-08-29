"""Tests for pipeline/storm.py — storm report matching and signal logic."""
from datetime import date, timedelta

import pytest

import pipeline.storm as storm_mod
from pipeline.storm import (
    _TYPE_MAP, _FREEZE_TYPE_MAP, _fetch_storm_reports, _haversine_mi, _match_property,
)


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

    def test_freeze_events_do_not_touch_the_storm_columns(self):
        # The regression the separate columns exist to prevent: a market that
        # gets both would otherwise have every roofing lead's hail date
        # overwritten by whichever snow report happened to land last.
        hail = _report(200, storm_type="hail")
        snow = _report(10, storm_type="freeze", hail_size=None)
        result = _match_property(self.PROP_LAT, self.PROP_LON, [hail, snow], 1.0, self.CUTOFF)
        assert result["last_storm_date"] == date.today() - timedelta(days=200)
        assert result["last_storm_type"] == "hail"
        assert result["storm_count_24mo"] == 1
        assert result["last_freeze_date"] == date.today() - timedelta(days=10)
        assert result["freeze_count_24mo"] == 1

    def test_freeze_only_match_writes_no_storm_columns(self):
        snow = _report(10, storm_type="freeze", hail_size=None)
        result = _match_property(self.PROP_LAT, self.PROP_LON, [snow], 1.0, self.CUTOFF)
        assert "last_storm_date" not in result
        assert "storm_count_24mo" not in result
        assert result["freeze_count_24mo"] == 1

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


# ── _fetch_storm_reports ──────────────────────────────────────────────────────
#
# These guard the IEM request/response contract, which is what previously broke
# silently: the API 422s on a malformed timestamp and ignores an unknown filter
# key, and get_json swallows both as "no data".

def _feature(typetext: str, *, magf=None, magnitude="", valid="2026-06-03T19:46:00Z",
             lon=-95.3698, lat=29.7604) -> dict:
    """One IEM LSR GeoJSON feature, shaped like the real feed."""
    return {
        "type": "Feature",
        "properties": {"typetext": typetext, "magf": magf, "magnitude": magnitude,
                       "valid": valid, "unit": "Inch"},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


@pytest.fixture(autouse=True)
def _clear_caches():
    """Both module caches persist across calls by design; isolate each test."""
    storm_mod._wfo_cache.clear()
    storm_mod._report_cache.clear()
    yield
    storm_mod._wfo_cache.clear()
    storm_mod._report_cache.clear()


@pytest.fixture
def captured_get(monkeypatch):
    """Stub pipeline.storm.get_json, recording every call.

    A lookback spans several chunked requests, so the payload is served once and
    later chunks come back empty; parsing assertions then stay independent of
    how many chunks the window happens to split into.
    """
    calls = []

    def _install(payload):
        def fake_get_json(url, *, headers=None, params=None, timeout=None, **kw):
            calls.append({"url": url, "params": params, "headers": headers})
            if len(calls) > 1 and isinstance(payload, dict):
                return {"type": "FeatureCollection", "features": []}
            return payload
        monkeypatch.setattr(storm_mod, "get_json", fake_get_json)
        return calls

    return _install


class TestTypeMap:
    def test_maps_real_feed_vocabulary(self):
        # Exact `typetext` strings observed in the live IEM feed. The feed uses
        # NWS product abbreviations, not spelled-out names.
        assert _TYPE_MAP["HAIL"] == "hail"
        assert _TYPE_MAP["TSTM WND DMG"] == "wind"
        assert _TYPE_MAP["TSTM WND GST"] == "wind"
        assert _TYPE_MAP["NON-TSTM WND GST"] == "wind"
        assert _TYPE_MAP["HIGH SUST WINDS"] == "wind"
        assert _TYPE_MAP["TORNADO"] == "tornado"
        assert _TYPE_MAP["LANDSPOUT"] == "tornado"

    def test_spelled_out_names_are_not_used(self):
        # Guards the original bug: these read plausibly but never appear.
        assert "THUNDERSTORM WIND" not in _TYPE_MAP
        assert "HIGH WIND" not in _TYPE_MAP

    def test_over_water_types_excluded(self):
        # No property damage, so they must not set last_storm_date.
        assert "MARINE TSTM WIND" not in _TYPE_MAP
        assert "WATERSPOUT" not in _TYPE_MAP

    def test_flood_is_not_a_damage_storm(self):
        # Hurricane flood damage runs through NFIP, not the homeowners policy
        # that funds a reroof — see the wind/flood note on _TYPE_MAP.
        for flood in ("FLOOD", "FLASH FLOOD", "COASTAL FLOOD", "STORM SURGE"):
            assert flood not in _TYPE_MAP
            assert flood not in _FREEZE_TYPE_MAP

    def test_freeze_map_is_disjoint_from_damage_map(self):
        assert not (set(_TYPE_MAP) & set(_FREEZE_TYPE_MAP))

    def test_freeze_map_uses_real_feed_vocabulary(self):
        # Observed in live LSR responses for HGX (Uri, and January 2025).
        for observed in ("SNOW", "SLEET", "FREEZING RAIN", "ICE STORM",
                         "SNOW/ICE DMG", "EXTREME COLD", "WIND CHILL"):
            assert _FREEZE_TYPE_MAP[observed] == "freeze"
        # Reads plausibly, never appears — the original _TYPE_MAP bug.
        assert "BLIZZARD" not in _FREEZE_TYPE_MAP


class TestFetchStormReports:
    def test_request_uses_accepted_param_names_and_formats(self, captured_get):
        calls = captured_get({"type": "FeatureCollection", "features": []})
        _fetch_storm_reports(24, "HGX")

        for call in calls:
            params = call["params"]
            # `wfo` (singular) is ignored by the API and returns nationwide data.
            assert "wfo" not in params
            assert params["wfos"] == "HGX"
            # %Y%m%d%H%M — anything else (notably a 'T') returns HTTP 422.
            assert params["sts"].isdigit() and len(params["sts"]) == 12
            assert params["ets"].isdigit() and len(params["ets"]) == 12

    def test_window_is_chunked_and_covers_full_lookback(self, captured_get):
        calls = captured_get({"type": "FeatureCollection", "features": []})
        _fetch_storm_reports(24, "HGX")

        def _day(stamp):
            return date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))

        # More than one request, or a busy office would silently hit the 10k cap.
        assert len(calls) > 1
        starts = [_day(c["params"]["sts"]) for c in calls]
        ends = [_day(c["params"]["ets"]) for c in calls]

        # Contiguous, no gaps that would drop reports between chunks.
        assert starts[1:] == ends[:-1]
        # Together they span the requested 24 months, ending today.
        assert 720 <= (date.today() - starts[0]).days <= 740
        assert ends[-1] == date.today()

    def test_parses_hail_size_from_magf(self, captured_get):
        captured_get({"type": "FeatureCollection",
                      "features": [_feature("HAIL", magf=1.75, magnitude="1.75")]})
        reports = _fetch_storm_reports(24, "HGX")
        assert len(reports) == 1
        assert reports[0]["storm_type"] == "hail"
        assert reports[0]["hail_size_in"] == pytest.approx(1.75)
        assert reports[0]["date"] == date(2026, 6, 3)
        assert reports[0]["lat"] == pytest.approx(29.7604)
        assert reports[0]["lon"] == pytest.approx(-95.3698)

    def test_wind_events_are_kept(self, captured_get):
        captured_get({"type": "FeatureCollection", "features": [
            _feature("TSTM WND DMG"), _feature("TSTM WND GST"),
        ]})
        reports = _fetch_storm_reports(24, "HGX")
        assert [r["storm_type"] for r in reports] == ["wind", "wind"]
        assert all(r["hail_size_in"] is None for r in reports)

    def test_irrelevant_and_marine_types_dropped(self, captured_get):
        captured_get({"type": "FeatureCollection", "features": [
            _feature("FLASH FLOOD"), _feature("RAIN"),
            _feature("MARINE TSTM WIND"), _feature("WATERSPOUT"),
        ]})
        assert _fetch_storm_reports(24, "HGX") == []

    def test_hurricane_wind_is_kept_and_hurricane_flood_is_not(self, captured_get):
        # Beryl's Harris County track produced all five of these in one window.
        # Wind damage is a homeowners-policy claim and buys a roof; hurricane
        # flood runs through NFIP and buys nothing this app sells.
        captured_get({"type": "FeatureCollection", "features": [
            _feature("TROPICAL CYCLONE"), _feature("NON-TSTM WND GST"),
            _feature("STORM SURGE"), _feature("FLASH FLOOD"),
            _feature("COASTAL FLOOD"),
        ]})
        reports = _fetch_storm_reports(24, "HGX")
        assert [r["storm_type"] for r in reports] == ["wind", "wind"]

    def test_freeze_types_are_kept(self, captured_get):
        # Winter Storm Uri reported as exactly these four types for HGX.
        captured_get({"type": "FeatureCollection", "features": [
            _feature("SNOW"), _feature("SLEET"),
            _feature("FREEZING RAIN"), _feature("ICE STORM"),
        ]})
        reports = _fetch_storm_reports(24, "HGX")
        assert [r["storm_type"] for r in reports] == ["freeze"] * 4

    def test_hail_with_no_measurement_still_recorded(self, captured_get):
        captured_get({"type": "FeatureCollection",
                      "features": [_feature("HAIL", magf=None, magnitude="")]})
        reports = _fetch_storm_reports(24, "HGX")
        assert len(reports) == 1
        assert reports[0]["hail_size_in"] is None

    def test_error_body_returns_empty_not_crash(self, captured_get):
        # A 422 body is a JSON *list*; .get() on it would raise AttributeError.
        captured_get([{"type": "value_error", "loc": ["query", "sts"]}])
        assert _fetch_storm_reports(24, "HGX") == []

    def test_failed_request_returns_empty(self, captured_get):
        captured_get(None)
        assert _fetch_storm_reports(24, "HGX") == []

    def test_repeat_wfo_is_served_from_cache(self, captured_get):
        calls = captured_get({"type": "FeatureCollection",
                              "features": [_feature("HAIL", magf=1.0)]})
        first = _fetch_storm_reports(24, "HGX")
        after_first = len(calls)
        second = _fetch_storm_reports(24, "HGX")

        assert second == first
        assert len(calls) == after_first, "second ZIP in the same WFO refetched"

    def test_different_wfo_is_fetched_separately(self, captured_get):
        calls = captured_get({"type": "FeatureCollection", "features": []})
        _fetch_storm_reports(24, "HGX")
        after_first = len(calls)
        _fetch_storm_reports(24, "FWD")
        assert len(calls) > after_first

    def test_malformed_features_skipped(self, captured_get):
        captured_get({"type": "FeatureCollection", "features": [
            {"properties": {"typetext": "HAIL"}, "geometry": None},          # no coords
            _feature("HAIL", magf=1.0, valid="not-a-date"),                  # bad date
            _feature("HAIL", magf=1.0),                                      # good
        ]})
        assert len(_fetch_storm_reports(24, "HGX")) == 1


class TestResolveWfo:
    def test_reads_cwa_and_caches(self, monkeypatch, captured_get):
        calls = captured_get({"properties": {"cwa": "FWD"}})

        assert storm_mod._resolve_wfo(32.7767, -96.7970) == "FWD"
        assert "32.78,-96.8" in calls[0]["url"]
        # NWS rejects requests without an identifying User-Agent.
        assert calls[0]["headers"]["User-Agent"]

        # Second call for the same point must not re-request.
        monkeypatch.setattr(storm_mod, "get_json", lambda *a, **k: pytest.fail("not cached"))
        assert storm_mod._resolve_wfo(32.7767, -96.7970) == "FWD"

    def test_returns_none_on_failure(self, captured_get):
        captured_get(None)
        # None, not a default — a wrong WFO would match another region's storms.
        assert storm_mod._resolve_wfo(29.7604, -95.3698) is None

    def test_missing_cwa_returns_none(self, captured_get):
        captured_get({"properties": {}})
        assert storm_mod._resolve_wfo(29.7604, -95.3698) is None
