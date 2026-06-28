"""Tests for pipeline/demographics.py — Versium field parsing and no-key no-op."""
from datetime import date

import pytest

from pipeline.demographics import (
    _first_name, _last_name, _safe_int, _safe_float,
    _yn, _band_lower, _parse_ym_date, _credit_grade,
    _mortgage_rate_type, _age_midpoint, _normalize_life_stage,
    _decade_band, _iso_date, _latest_refi_date, _last_sale_year, _years_since,
    _batchdata_lookup, PROVIDERS,
    enrich_demographics,
)


# ── Name splitting ─────────────────────────────────────────────────────────────

class TestNameHelpers:
    def test_first_name_two_words(self):
        assert _first_name("John Smith") == "John"

    def test_last_name_two_words(self):
        assert _last_name("John Smith") == "Smith"

    def test_last_name_single_word(self):
        assert _last_name("Smith") == "Smith"

    def test_first_name_single_word(self):
        assert _first_name("Smith") == "Smith"

    def test_empty_name(self):
        assert _first_name("") == ""
        assert _last_name("") == ""


# ── _yn ───────────────────────────────────────────────────────────────────────

class TestYN:
    def test_y_true(self):
        assert _yn("Y") is True

    def test_yes_true(self):
        assert _yn("Yes") is True

    def test_n_false(self):
        assert _yn("N") is False

    def test_no_false(self):
        assert _yn("No") is False

    def test_bool_true(self):
        assert _yn(True) is True

    def test_bool_false(self):
        assert _yn(False) is False

    def test_none_is_none(self):
        assert _yn(None) is None

    def test_garbage_is_none(self):
        assert _yn("maybe") is None


# ── _safe_int ─────────────────────────────────────────────────────────────────

class TestSafeInt:
    def test_plain_int(self):
        assert _safe_int(42) == 42

    def test_string_int(self):
        assert _safe_int("65") == 65

    def test_string_with_comma(self):
        assert _safe_int("75,000") == 75000

    def test_float_string(self):
        assert _safe_int("65.7") == 65

    def test_none(self):
        assert _safe_int(None) is None

    def test_garbage(self):
        assert _safe_int("n/a") is None


# ── _safe_float ───────────────────────────────────────────────────────────────

class TestSafeFloat:
    def test_plain(self):
        assert _safe_float(45.5) == pytest.approx(45.5)

    def test_percent_string(self):
        assert _safe_float("45%") == pytest.approx(45.0)

    def test_none(self):
        assert _safe_float(None) is None


# ── _band_lower ───────────────────────────────────────────────────────────────

class TestBandLower:
    def test_dollar_band(self):
        assert _band_lower("$75,000-$99,999") == 75000

    def test_plain_int(self):
        assert _band_lower(350000) == 350000

    def test_no_dollar(self):
        assert _band_lower("500000-749999") == 500000

    def test_none(self):
        assert _band_lower(None) is None

    def test_unparseable(self):
        assert _band_lower("unknown") is None


# ── _parse_ym_date ────────────────────────────────────────────────────────────

class TestParseYmDate:
    def test_full_iso(self):
        assert _parse_ym_date("2023-06-15") == date(2023, 6, 15)

    def test_year_month(self):
        assert _parse_ym_date("2023-06") == date(2023, 6, 1)

    def test_year_only(self):
        assert _parse_ym_date("2023") == date(2023, 1, 1)

    def test_none(self):
        assert _parse_ym_date(None) is None

    def test_garbage(self):
        assert _parse_ym_date("not-a-date") is None


# ── _credit_grade ─────────────────────────────────────────────────────────────

class TestCreditGrade:
    def test_a(self):
        assert _credit_grade("A") == "A"

    def test_lowercase_b(self):
        assert _credit_grade("b") == "B"

    def test_excellent_maps_to_a(self):
        assert _credit_grade("Excellent") == "A"

    def test_good_maps_to_b(self):
        assert _credit_grade("Good") == "B"

    def test_fair_maps_to_c(self):
        assert _credit_grade("Fair") == "C"

    def test_poor_maps_to_d(self):
        assert _credit_grade("Poor") == "D"

    def test_none(self):
        assert _credit_grade(None) is None

    def test_unknown(self):
        assert _credit_grade("X") is None


# ── _mortgage_rate_type ───────────────────────────────────────────────────────

class TestMortgageRateType:
    def test_fixed(self):
        assert _mortgage_rate_type("Fixed") == "Fixed"

    def test_fixed_lowercase(self):
        assert _mortgage_rate_type("fixed rate") == "Fixed"

    def test_arm(self):
        assert _mortgage_rate_type("ARM") == "ARM"

    def test_adjustable(self):
        assert _mortgage_rate_type("Adjustable") == "ARM"

    def test_none(self):
        assert _mortgage_rate_type(None) is None


# ── _age_midpoint ─────────────────────────────────────────────────────────────

class TestAgeMidpoint:
    def test_range(self):
        assert _age_midpoint("35-44") == 39

    def test_single_int(self):
        assert _age_midpoint("52") == 52

    def test_none(self):
        assert _age_midpoint(None) is None

    def test_65_plus(self):
        # '65+' has only one number — parsed as 65
        assert _age_midpoint("65+") == 65


# ── _normalize_life_stage ─────────────────────────────────────────────────────

class TestNormalizeLifeStage:
    def test_senior_flag_wins(self):
        assert _normalize_life_stage(None, 50, 10, True) == "retiree"

    def test_short_tenure_new_mover(self):
        assert _normalize_life_stage(None, 45, 1, False) == "new_mover"

    def test_old_age_retiree(self):
        assert _normalize_life_stage(None, 70, None, False) == "retiree"

    def test_long_tenure_established(self):
        assert _normalize_life_stage(None, 50, 10, False) == "established"

    def test_no_data_returns_none(self):
        assert _normalize_life_stage(None, None, None, None) is None

    def test_some_data_returns_other(self):
        assert _normalize_life_stage(None, 40, 3, False) == "other"

    def test_raw_label_new_mover(self):
        assert _normalize_life_stage("New Mover", None, None, None) == "new_mover"


# ── enrich_demographics no-key no-op ─────────────────────────────────────────

# ── BatchData property-search parsing helpers ────────────────────────────────────

class TestBatchdataHelpers:
    def test_decade_band(self):
        assert _decade_band(33) == "30-39"
        assert _decade_band(67) == "60-69"
        assert _decade_band(None) is None

    def test_iso_date(self):
        from datetime import date
        assert _iso_date("2003-03-19T00:00:00.000Z") == date(2003, 3, 19)
        assert _iso_date(None) is None

    def test_latest_refi_date_picks_most_recent_refi(self):
        from datetime import date
        history = [
            {"transactionType": "Resale", "recordingDate": "1996-03-27T00:00:00.000Z"},
            {"transactionType": "Refi loans and 2nd trust deeds", "recordingDate": "2003-03-19T00:00:00.000Z"},
            {"transactionType": "Refi", "recordingDate": "2010-06-01T00:00:00.000Z"},
        ]
        assert _latest_refi_date(history) == date(2010, 6, 1)

    def test_latest_refi_date_none_when_no_refi(self):
        assert _latest_refi_date([{"transactionType": "Resale",
                                   "recordingDate": "1996-03-27T00:00:00.000Z"}]) is None

    def test_last_sale_year_from_last_sale(self):
        prop = {"sale": {"lastSale": {"saleDate": "1996-03-21T00:00:00.000Z"}}}
        assert _last_sale_year(prop) == 1996

    def test_years_since(self):
        from datetime import date
        assert _years_since(date.today().year - 8) == 8
        assert _years_since(None) is None


# ── _batchdata_lookup (Property Search demographics envelope) ─────────────────────

class TestBatchdataDemographics:
    def test_registered(self):
        assert "batchdata" in PROVIDERS

    def test_parses_property_search_response(self, monkeypatch):
        captured = {}
        def fake(url, *, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return {"results": {"properties": [{
                "demographics": {
                    "age": 33,
                    "income": 40000,
                    "netWorth": 215000,
                    "maritalStatus": "Married",
                    "individualOccupation": "Craftsman / Blue Collar",
                    "hasChildren": False,
                },
                "valuation": {"ltv": 0, "equityPercent": 100},
                "quickLists": {"seniorOwner": False},
                "mortgageHistory": [
                    {"transactionType": "Refi loans and 2nd trust deeds",
                     "recordingDate": "2003-03-19T00:00:00.000Z"},
                ],
                "sale": {"lastSale": {"saleDate": "1996-03-21T00:00:00.000Z"}},
            }]}}
        monkeypatch.setattr("pipeline.demographics.post_json", fake)
        out = _batchdata_lookup({"owner_name": "Pete Castillo",
                                 "address": "3723 Apple Hollow Ln",
                                 "city": "Humble", "state": "TX", "zip": "77396"})
        from datetime import date
        assert out["owner_age"] == 33
        assert out["age_range"] == "30-39"
        assert out["est_household_income"] == 40000
        assert out["estimated_net_worth"] == 215000
        assert out["marital_status"] == "Married"
        assert out["occupation"] == "Craftsman / Blue Collar"
        assert out["has_children"] is False
        assert out["loan_to_value"] == 0
        assert out["senior_in_household"] is False
        assert out["refi_date"] == date(2003, 3, 19)
        assert out["length_of_residence_years"] == date.today().year - 1996
        # Address query reached the property-search endpoint.
        assert captured["url"].endswith("/property/search")
        assert "3723 Apple Hollow Ln" in captured["json"]["searchCriteria"]["query"]

    def test_senior_from_quicklist_flag(self, monkeypatch):
        monkeypatch.setattr("pipeline.demographics.post_json",
                            lambda *a, **k: {"results": {"properties": [
                                {"demographics": {"age": 70}, "quickLists": {"seniorOwner": True}}]}})
        out = _batchdata_lookup({"address": "1 Oak St"})
        assert out["senior_in_household"] is True
        assert out["life_stage"] == "retiree"

    def test_no_properties_returns_none(self, monkeypatch):
        monkeypatch.setattr("pipeline.demographics.post_json",
                            lambda *a, **k: {"results": {"properties": []}})
        assert _batchdata_lookup({"address": "1 Nowhere St"}) is None

    def test_api_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr("pipeline.demographics.post_json", lambda *a, **k: None)
        assert _batchdata_lookup({"address": "1 Oak St"}) is None


class TestEnrichDemographicsNoKey:
    def test_no_provider_configured_returns_skipped(self, monkeypatch):
        monkeypatch.setattr("pipeline.demographics.DEMO_PROVIDER", "")
        monkeypatch.setattr("pipeline.demographics.DEMO_API_KEY", "")
        result = enrich_demographics("77002", 1)
        assert result["skipped_no_key"] is True
        assert result["updated"] == 0

    def test_unknown_provider_returns_skipped(self, monkeypatch):
        monkeypatch.setattr("pipeline.demographics.DEMO_PROVIDER", "unknown_provider")
        monkeypatch.setattr("pipeline.demographics.DEMO_API_KEY", "fake-key")
        result = enrich_demographics("77002", 1)
        assert result["skipped_no_key"] is True
