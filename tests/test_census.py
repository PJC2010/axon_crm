"""
Tests for pipeline/census.py — ACS response parsing and request shape.

Pure; no HTTP, no database.
"""
import pytest

import config
from pipeline import census
from pipeline.census import parse_income


def test_parses_a_normal_response():
    data = [["B19013_001E", "zip code tabulation area"], ["78500", "77449"]]
    assert parse_income(data) == 78500


def test_column_order_is_read_from_the_header_not_assumed():
    data = [["zip code tabulation area", "B19013_001E"], ["77449", "78500"]]
    assert parse_income(data) == 78500


def test_negative_sentinel_means_not_available():
    """ACS encodes 'no data' as -666666666, which int() would happily accept."""
    data = [["B19013_001E", "zip code tabulation area"], ["-666666666", "77449"]]
    assert parse_income(data) is None


@pytest.mark.parametrize("data", [
    None,
    [],
    [["B19013_001E", "zip code tabulation area"]],      # header only, no rows
    "an error string",
    {"error": "bad request"},
    [["wrong_column"], ["1"]],                           # variable missing
    [["B19013_001E", "z"], ["not-a-number", "77449"]],
    [["B19013_001E", "z"], []],                          # short row
])
def test_bad_payloads_degrade_to_none_rather_than_raising(data):
    """A missing income must leave the signal unscored, never fail the run."""
    assert parse_income(data) is None


def test_zero_income_is_kept_not_treated_as_missing():
    data = [["B19013_001E", "zip code tabulation area"], ["0", "77449"]]
    assert parse_income(data) == 0


def test_fetch_income_requests_one_zcta_not_the_whole_country(monkeypatch):
    """Regression: this used to request `*` — every ZCTA in the US (~33,000
    rows) — and filter client-side to find one ZIP."""
    seen = {}

    def fake_get_json(url, params=None, timeout=None):
        seen["url"] = url
        seen["params"] = params
        return [["B19013_001E", "zip code tabulation area"], ["78500", "77449"]]

    monkeypatch.setattr(census, "get_json", fake_get_json)
    assert census.fetch_income("77449") == 78500
    assert seen["params"]["for"] == "zip code tabulation area:77449"
    assert "*" not in seen["params"]["for"]


def test_fetch_income_includes_the_api_key_only_when_set(monkeypatch):
    seen = {}

    def fake_get_json(url, params=None, timeout=None):
        seen.update(params)
        return None

    monkeypatch.setattr(census, "get_json", fake_get_json)

    monkeypatch.setattr(census, "CENSUS_API_KEY", "")
    census.fetch_income("77449")
    assert "key" not in seen

    seen.clear()
    monkeypatch.setattr(census, "CENSUS_API_KEY", "abc123")
    census.fetch_income("77449")
    assert seen["key"] == "abc123"


def test_fetch_income_returns_none_when_the_request_fails(monkeypatch):
    monkeypatch.setattr(census, "get_json", lambda *a, **k: None)
    assert census.fetch_income("77449") is None


def test_income_variable_matches_config():
    """The parser keys off the configured variable name."""
    data = [[config.CENSUS_INCOME_VAR, "zip code tabulation area"], ["61000", "77396"]]
    assert parse_income(data) == 61000
