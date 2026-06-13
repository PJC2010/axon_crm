"""Tests for pipeline/demographics.py — provider response mapping and no-key no-op."""
import pytest

from pipeline.demographics import (
    _first_name, _last_name, _safe_int, _normalize_life_stage, enrich_demographics,
)


# ── Name splitting ─────────────────────────────────────────────────────────────

class TestNameHelpers:
    def test_first_name_single_word(self):
        assert _first_name("Smith") == "Smith"

    def test_first_name_two_words(self):
        assert _first_name("John Smith") == "John"

    def test_last_name_two_words(self):
        assert _last_name("John Smith") == "Smith"

    def test_last_name_single_word(self):
        assert _last_name("Smith") == "Smith"

    def test_empty_name(self):
        assert _first_name("") == ""
        assert _last_name("") == ""


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


# ── _normalize_life_stage ─────────────────────────────────────────────────────

class TestNormalizeLifeStage:
    def test_raw_new_mover(self):
        assert _normalize_life_stage("New Mover", None, None) == "new_mover"

    def test_raw_retiree(self):
        assert _normalize_life_stage("Retiree", None, None) == "retiree"

    def test_raw_established(self):
        assert _normalize_life_stage("Established", None, None) == "established"

    def test_passthrough_canonical(self):
        assert _normalize_life_stage("established", None, None) == "established"

    def test_short_tenure_inferred_new_mover(self):
        assert _normalize_life_stage(None, 45, 2) == "new_mover"

    def test_old_age_inferred_retiree(self):
        assert _normalize_life_stage(None, 70, None) == "retiree"

    def test_long_tenure_inferred_established(self):
        assert _normalize_life_stage(None, 50, 10) == "established"

    def test_no_data_returns_none(self):
        assert _normalize_life_stage(None, None, None) is None

    def test_some_data_returns_other(self):
        # Age present but doesn't hit any threshold
        result = _normalize_life_stage(None, 40, 3)
        assert result == "other"


# ── enrich_demographics no-key no-op ─────────────────────────────────────────

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
