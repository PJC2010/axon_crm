"""
Tests for the scoring-hardening layer: missing-data renormalization,
data_completeness, qualifier gates, equity-fallback down-weighting, and
validate_weights. Pure math — no database required.

Behavioral defaults are unchanged (SCORE_MISSING_MODE defaults to "zero");
renormalize-mode tests monkeypatch config.SCORE_MISSING_MODE.
"""
from datetime import date

import pytest

import config
import pipeline.scoring as scoring
from pipeline.scoring import (
    _compute_score,
    data_completeness,
    explain_score,
    validate_weights,
)
from pipeline.equity import estimate_equity
from pipeline.profiles import resolve_profile


def today_year() -> int:
    return date.today().year


FULL_ROW = {
    "year_built":            today_year() - 22,
    "last_sale_date":        date.today(),
    "estimated_equity":      100_000,
    "garage_spaces":         2,
    "zip_median_income":     75_000,
    "permit_count_24mo":     2,
    "neighborhood_value_ratio": 1.3,
}

# Only age + equity present: 0.25 + 0.18 = 0.43 of the default profile's weight.
SPARSE_ROW = {
    "year_built":       today_year() - 22,   # signal 1.0
    "estimated_equity": 50_000,              # signal 0.5
}


@pytest.fixture
def renormalize(monkeypatch):
    monkeypatch.setattr(config, "SCORE_MISSING_MODE", "renormalize")
    yield
    # monkeypatch restores "zero"


# ── Missing-data modes ────────────────────────────────────────────────────────

class TestMissingModeZero:
    def test_default_mode_is_zero(self):
        assert config.SCORE_MISSING_MODE == "zero"

    def test_sparse_row_penalized_in_zero_mode(self):
        # 0.25*1.0 + 0.18*0.5 = 0.34 → 34 points; missing weights score 0.
        score = _compute_score(SPARSE_ROW, config.DEFAULT_WEIGHTS)
        assert score == pytest.approx(34.0)


class TestMissingModeRenormalize:
    def test_sparse_row_rescaled(self, renormalize):
        # (0.25*1.0 + 0.18*0.5) / 0.43 ≈ 0.7907 → ~79 points.
        score = _compute_score(SPARSE_ROW, config.DEFAULT_WEIGHTS)
        assert score == pytest.approx(34.0 / 0.43, abs=0.01)

    def test_full_row_unaffected(self, renormalize):
        assert _compute_score(FULL_ROW, config.DEFAULT_WEIGHTS) == pytest.approx(100.0, abs=0.5)

    def test_empty_row_still_zero(self, renormalize):
        assert _compute_score({}, config.DEFAULT_WEIGHTS) == 0.0

    def test_present_zero_values_still_score_zero(self, renormalize):
        # 0 permits is a real data point (no investment activity), not a gap —
        # it must NOT renormalize away.
        row = dict(SPARSE_ROW, permit_count_24mo=0)
        available = 0.25 + 0.18 + 0.08
        expected = (0.25 * 1.0 + 0.18 * 0.5 + 0.08 * 0.0) / available * 100
        assert _compute_score(row, config.DEFAULT_WEIGHTS) == pytest.approx(expected, abs=0.01)


# ── data_completeness ─────────────────────────────────────────────────────────

class TestDataCompleteness:
    def test_full_row_is_complete(self):
        assert data_completeness(FULL_ROW, config.DEFAULT_WEIGHTS) == 1.0

    def test_sparse_row(self):
        assert data_completeness(SPARSE_ROW, config.DEFAULT_WEIGHTS) == pytest.approx(0.43)

    def test_empty_row(self):
        assert data_completeness({}, config.DEFAULT_WEIGHTS) == 0.0

    def test_zero_weight_factors_ignored(self):
        # garage has weight 0 in roofing — its absence must not lower completeness.
        row = {meta["field"]: 1 for meta in config.FACTOR_META.values()}
        row.pop("garage_spaces")
        assert data_completeness(row, config.VERTICAL_WEIGHTS["roofing"]) == 1.0

    def test_present_zero_counts_as_data(self):
        row = dict(FULL_ROW, permit_count_24mo=0)
        assert data_completeness(row, config.DEFAULT_WEIGHTS) == 1.0


# ── Qualifier gates ───────────────────────────────────────────────────────────

class TestGates:
    POOL_WEIGHTS = config.VERTICAL_WEIGHTS["pool_maintenance"]

    def _pool_row(self, has_pool):
        return {
            "year_built":            today_year() - 22,   # 1.0
            "last_sale_date":        date.today(),         # ~1.0
            "estimated_equity":      100_000,              # 1.0
            "zip_median_income":     75_000,               # 1.0
            "neighborhood_value_ratio": 1.3,               # 1.0
            "permit_count_24mo":     2,                    # 1.0
            "has_pool":              has_pool,
            "has_children":          True,                 # 1.0
            "credit_rating":         "A",                  # 1.0
            "home_improvement_flag": True,                 # 1.0
            "life_stage":            "new_mover",          # 1.0
        }

    def test_confirmed_pool_scores_normally(self):
        score = _compute_score(self._pool_row(True), self.POOL_WEIGHTS, ("pool",))
        assert score == pytest.approx(100.0, abs=1.0)

    def test_confirmed_absence_gates_score(self):
        # A perfect lead with NO pool: qualified score ~100 → × GATE_MISS_FACTOR.
        score = _compute_score(self._pool_row(False), self.POOL_WEIGHTS, ("pool",))
        assert score == pytest.approx(100.0 * config.GATE_MISS_FACTOR, abs=1.0)

    def test_gated_score_stays_below_a_band(self):
        score = _compute_score(self._pool_row(False), self.POOL_WEIGHTS, ("pool",))
        assert score < 75

    def test_missing_gate_field_does_not_gate(self):
        row = self._pool_row(None)
        row.pop("has_pool")
        score = _compute_score(row, self.POOL_WEIGHTS, ("pool",))
        # Unknown is not disqualifying: no multiplier, and the gate factor's
        # weight renormalizes out — the lead ranks on its other signals alone.
        assert score == pytest.approx(100.0, abs=1.0)

    def test_profile_carries_configured_gates(self):
        assert resolve_profile("pool_maintenance").gates == ("pool",)
        assert resolve_profile("roofing").gates == ()

    def test_explain_flags_gated_lead(self):
        result = explain_score(self._pool_row(False), self.POOL_WEIGHTS,
                               resolve_profile("pool_maintenance"))
        assert result["gated"] is True
        # Breakdown still reconciles with the (multiplied) displayed score.
        total = sum(f["contribution"] for f in result["factors"])
        assert total == pytest.approx(result["score"], abs=0.5)


# ── Equity fallback down-weighting ────────────────────────────────────────────

class TestEquityFallbackScale:
    def test_fallback_flag_scales_equity_contribution(self):
        row = dict(FULL_ROW, estimated_equity_is_fallback=True)
        scale = config.EQUITY_FALLBACK_SIGNAL_SCALE
        # equity signal 1.0 → scale; everything else untouched.
        expected = (1.0 - config.DEFAULT_WEIGHTS["equity"] * (1 - scale)) * 100
        assert _compute_score(row, config.DEFAULT_WEIGHTS) == pytest.approx(expected, abs=0.5)

    def test_unflagged_row_unaffected(self):
        assert _compute_score(FULL_ROW, config.DEFAULT_WEIGHTS) == pytest.approx(100.0, abs=0.5)

    def test_estimate_equity_reports_fallback_source(self):
        _, source = estimate_equity(300_000, return_source=True)
        assert source == "fallback"

    def test_estimate_equity_reports_amortized_source(self):
        _, source = estimate_equity(300_000, last_sale_price=250_000,
                                    last_sale_date="2020-01-01", return_source=True)
        assert source == "amortized"

    def test_estimate_equity_reports_balance_source(self):
        _, source = estimate_equity(300_000, mortgage_balance=100_000,
                                    return_source=True)
        assert source == "balance"

    def test_estimate_equity_default_return_unchanged(self):
        # Back-compat: single-arg call still returns just the int.
        assert estimate_equity(300_000) == 180_000


# ── validate_weights ──────────────────────────────────────────────────────────

class TestValidateWeights:
    def test_builtin_profiles_all_valid(self):
        validate_weights(config.DEFAULT_WEIGHTS)
        for weights in config.VERTICAL_WEIGHTS.values():
            validate_weights(weights)

    def test_unknown_key_rejected(self):
        with pytest.raises(ValueError, match="Unknown signal"):
            validate_weights({"age": 0.5, "eqwity": 0.5})  # typo

    def test_negative_weight_rejected(self):
        bad = dict(config.DEFAULT_WEIGHTS, age=-0.1, sale=0.32)
        with pytest.raises(ValueError, match="Negative weight"):
            validate_weights(bad)

    def test_non_unit_sum_rejected(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            validate_weights({"age": 0.5, "sale": 0.4})

    def test_profiles_validate_at_load(self):
        # Every registered property profile passed validation at import time;
        # spot-check the registry resolved them.
        assert resolve_profile("roofing").weights == config.VERTICAL_WEIGHTS["roofing"]
