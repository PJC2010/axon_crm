"""
Tests for pipeline/scoring.py — pure lead-scoring math.

Covers: all six signal functions, _compute_score, score_property,
_grade band boundaries, and weight-profile invariants.

These tests intentionally lock in CURRENT behavior, including known quirks
(documented inline). They must pass without a database connection.
"""
from datetime import date, timedelta

import pytest

import config
import pipeline.scoring as scoring
from pipeline.scoring import (
    score_property,
    _compute_score,
    _grade,
    _age_signal,
    _sale_signal,
    _equity_signal,
    _garage_signal,
    _income_signal,
    _permit_signal,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def today_year() -> int:
    return date.today().year


def days_ago(n: int) -> date:
    return date.today() - timedelta(days=n)


def months_ago_date(months: float) -> date:
    return date.today() - timedelta(days=months * 30.44)


# ── _age_signal ───────────────────────────────────────────────────────────────

class TestAgeSignal:
    def test_none(self):
        assert _age_signal(None) == 0.0

    def test_zero_year_treated_as_missing(self):
        # year_built=0 is falsy — treated as missing
        assert _age_signal(0) == 0.0

    def test_sweet_spot_min_boundary(self):
        assert _age_signal(today_year() - 15) == 1.0

    def test_sweet_spot_max_boundary(self):
        assert _age_signal(today_year() - 30) == 1.0

    def test_sweet_spot_middle(self):
        assert _age_signal(today_year() - 22) == 1.0

    def test_young_age_5(self):
        result = _age_signal(today_year() - 5)
        assert result == pytest.approx(5 / 15)

    def test_young_age_10(self):
        result = _age_signal(today_year() - 10)
        assert result == pytest.approx(10 / 15)

    def test_young_age_1(self):
        result = _age_signal(today_year() - 1)
        assert result == pytest.approx(1 / 15)

    def test_old_age_40(self):
        # decay: 1 - (40-30)/20 = 0.5
        result = _age_signal(today_year() - 40)
        assert result == pytest.approx(0.5)

    def test_old_age_50_floor(self):
        # 1 - (50-30)/20 = 0.0 exactly
        result = _age_signal(today_year() - 50)
        assert result == pytest.approx(0.0)

    def test_old_age_60_clamped_to_zero(self):
        # would be negative without max(0, ...) clamp
        result = _age_signal(today_year() - 60)
        assert result == 0.0

    def test_old_age_31(self):
        result = _age_signal(today_year() - 31)
        assert result == pytest.approx(1.0 - 1 / 20)


# ── _sale_signal ──────────────────────────────────────────────────────────────

class TestSaleSignal:
    def test_none(self):
        assert _sale_signal(None) == 0.0

    def test_empty_string(self):
        assert _sale_signal("") == 0.0

    def test_today_as_date(self):
        result = _sale_signal(date.today())
        assert result == pytest.approx(1.0, abs=0.01)

    def test_today_as_string(self):
        result = _sale_signal(str(date.today()))
        assert result == pytest.approx(1.0, abs=0.01)

    def test_date_vs_string_parity(self):
        d = days_ago(90)
        assert _sale_signal(d) == pytest.approx(_sale_signal(d.isoformat()))

    def test_12_months_ago(self):
        d = months_ago_date(12)
        result = _sale_signal(d)
        assert result == pytest.approx(0.5, abs=0.02)

    def test_exactly_24_months_ago_is_zero(self):
        # months_ago = days/30.44 must be >= 24, so days >= ceil(24*30.44) = 731
        d = days_ago(731)
        result = _sale_signal(d)
        assert result == 0.0

    def test_older_than_24_months(self):
        d = months_ago_date(36)
        assert _sale_signal(d) == 0.0

    def test_future_date_returns_above_one(self):
        # Known quirk: no upper clamp, future dates yield > 1.0
        future = date.today() + timedelta(days=180)
        result = _sale_signal(future)
        assert result > 1.0

    def test_datetime_string_with_time_component(self):
        # [:10] slice handles ISO datetimes
        result = _sale_signal("2024-06-15T14:30:00")
        assert isinstance(result, float)
        assert 0.0 <= result  # value depends on today, just check it doesn't crash

    def test_malformed_string(self):
        assert _sale_signal("not-a-date") == 0.0

    def test_wrong_type_int(self):
        assert _sale_signal(20240101) == 0.0

    def test_wrong_type_float(self):
        assert _sale_signal(2024.5) == 0.0


# ── _equity_signal ────────────────────────────────────────────────────────────

class TestEquitySignal:
    def test_none(self):
        assert _equity_signal(None) == 0.0

    def test_zero(self):
        assert _equity_signal(0) == 0.0

    def test_negative(self):
        assert _equity_signal(-5000) == 0.0

    def test_below_target(self):
        assert _equity_signal(50_000) == pytest.approx(0.5)

    def test_at_target(self):
        assert _equity_signal(100_000) == pytest.approx(1.0)

    def test_above_target_capped(self):
        assert _equity_signal(250_000) == pytest.approx(1.0)

    def test_quarter_target(self):
        assert _equity_signal(25_000) == pytest.approx(0.25)


# ── _garage_signal ────────────────────────────────────────────────────────────

class TestGarageSignal:
    def test_none(self):
        assert _garage_signal(None) == 0.0

    def test_zero(self):
        assert _garage_signal(0) == 0.0

    def test_one_space(self):
        assert _garage_signal(1) == pytest.approx(0.5)

    def test_at_target(self):
        assert _garage_signal(2) == pytest.approx(1.0)

    def test_above_target_capped(self):
        assert _garage_signal(4) == pytest.approx(1.0)

    def test_negative_passes_through(self):
        # Known quirk: no <=0 guard (unlike equity/income/permit).
        # Negative input yields a negative signal — locked in as current behavior.
        result = _garage_signal(-1)
        assert result == pytest.approx(-0.5)


# ── _income_signal ────────────────────────────────────────────────────────────

class TestIncomeSignal:
    def test_none(self):
        assert _income_signal(None) == 0.0

    def test_zero(self):
        assert _income_signal(0) == 0.0

    def test_negative(self):
        assert _income_signal(-1000) == 0.0

    def test_below_target(self):
        assert _income_signal(37_500) == pytest.approx(0.5)

    def test_at_target(self):
        assert _income_signal(75_000) == pytest.approx(1.0)

    def test_above_target_capped(self):
        assert _income_signal(150_000) == pytest.approx(1.0)


# ── _permit_signal ────────────────────────────────────────────────────────────

class TestPermitSignal:
    def test_none(self):
        assert _permit_signal(None) == 0.0

    def test_zero(self):
        assert _permit_signal(0) == 0.0

    def test_negative(self):
        assert _permit_signal(-1) == 0.0

    def test_one_permit(self):
        assert _permit_signal(1) == pytest.approx(0.5)

    def test_at_target(self):
        assert _permit_signal(2) == pytest.approx(1.0)

    def test_above_target_capped(self):
        assert _permit_signal(5) == pytest.approx(1.0)


# ── _grade ────────────────────────────────────────────────────────────────────

class TestGrade:
    def test_perfect_score(self):
        assert _grade(100) == "A"

    def test_a_boundary_exact(self):
        assert _grade(75) == "A"

    def test_just_below_a(self):
        assert _grade(74.99) == "B"

    def test_b_boundary_exact(self):
        assert _grade(55) == "B"

    def test_just_below_b(self):
        assert _grade(54.99) == "C"

    def test_c_boundary_exact(self):
        assert _grade(35) == "C"

    def test_just_below_c(self):
        assert _grade(34.99) == "D"

    def test_d_boundary_exact(self):
        assert _grade(0) == "D"

    def test_negative_score(self):
        assert _grade(-5) == "D"

    @pytest.mark.parametrize("score,expected", [
        (100, "A"), (75, "A"), (74.9, "B"),
        (55, "B"),  (54.9, "C"),
        (35, "C"),  (34.9, "D"),
        (0, "D"),   (-1, "D"),
    ])
    def test_grade_parametrized(self, score, expected):
        assert _grade(score) == expected


# ── _compute_score / score_property ──────────────────────────────────────────

PERFECT_ROW = {
    "year_built":       today_year() - 22,   # sweet-spot age → signal 1.0
    "last_sale_date":   date.today(),         # just sold → signal ≈ 1.0
    "estimated_equity": 100_000,              # at target → 1.0
    "garage_spaces":    2,                    # at target → 1.0
    "zip_median_income": 75_000,              # at target → 1.0
    "permit_count_24mo": 2,                   # at target → 1.0
    "has_pool":          True,                # pool_maintenance signal → 1.0
    "has_cracked_slab":  True,                # epoxy_flooring slab signal → 1.0
}

EMPTY_ROW: dict = {}


class TestComputeScore:
    def test_perfect_row_near_100(self):
        score = _compute_score(PERFECT_ROW, config.DEFAULT_WEIGHTS)
        assert score == pytest.approx(100.0, abs=1.0)  # sale signal ≈ 1.0 not exactly

    def test_empty_row_is_zero(self):
        assert _compute_score(EMPTY_ROW, config.DEFAULT_WEIGHTS) == 0.0

    def test_none_values_row_is_zero(self):
        row = {k: None for k in PERFECT_ROW}
        assert _compute_score(row, config.DEFAULT_WEIGHTS) == 0.0

    def test_realistic_mixed_row(self):
        row = {
            "year_built":        today_year() - 25,  # sweet spot → 1.0
            "last_sale_date":    months_ago_date(12),  # 12 mo ago → ~0.5
            "estimated_equity":  50_000,              # half target → 0.5
            "garage_spaces":     1,                   # half target → 0.5
            "zip_median_income": None,                # missing → 0.0
            "permit_count_24mo": None,                # missing → 0.0
        }
        w = config.DEFAULT_WEIGHTS
        expected = (
            w["age"]    * 1.0 +
            w["sale"]   * 0.5 +
            w["equity"] * 0.5 +
            w["garage"] * 0.5 +
            w["income"] * 0.0 +
            w["permit"] * 0.0
        ) * 100
        result = _compute_score(row, w)
        assert result == pytest.approx(expected, abs=1.0)

    @pytest.mark.parametrize("profile_name,weights", [
        ("default", config.DEFAULT_WEIGHTS),
        *config.VERTICAL_WEIGHTS.items(),
    ])
    def test_perfect_row_near_100_all_profiles(self, profile_name, weights):
        score = _compute_score(PERFECT_ROW, weights)
        assert score == pytest.approx(100.0, abs=1.0), (
            f"Profile '{profile_name}' should score ~100 on a perfect row"
        )


class TestScoreProperty:
    def test_returns_tuple(self):
        result = score_property(PERFECT_ROW, config.DEFAULT_WEIGHTS)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_score_and_grade_consistent(self):
        score, grade = score_property(PERFECT_ROW, config.DEFAULT_WEIGHTS)
        assert grade == _grade(score)

    def test_empty_row_returns_zero_d(self):
        score, grade = score_property(EMPTY_ROW, config.DEFAULT_WEIGHTS)
        assert score == 0.0
        assert grade == "D"

    def test_perfect_row_returns_a(self):
        score, grade = score_property(PERFECT_ROW, config.DEFAULT_WEIGHTS)
        assert grade == "A"
        assert score >= 75


# ── Weight-profile invariants ─────────────────────────────────────────────────

ALL_PROFILES = {
    "default": config.DEFAULT_WEIGHTS,
    **config.VERTICAL_WEIGHTS,
}

EXPECTED_KEYS = set(config.DEFAULT_WEIGHTS.keys())
# pool/slab are optional vertical-only signals (scored via weights.get()).
OPTIONAL_KEYS = {"pool", "slab"}
ALLOWED_KEYS = EXPECTED_KEYS | OPTIONAL_KEYS


class TestWeightProfiles:
    @pytest.mark.parametrize("name,weights", ALL_PROFILES.items())
    def test_weights_sum_to_one(self, name, weights):
        assert sum(weights.values()) == pytest.approx(1.0), (
            f"Profile '{name}' weights sum to {sum(weights.values())}, expected 1.0"
        )

    @pytest.mark.parametrize("name,weights", ALL_PROFILES.items())
    def test_weights_have_correct_keys(self, name, weights):
        keys = set(weights.keys())
        assert EXPECTED_KEYS <= keys, (
            f"Profile '{name}' is missing base keys: {EXPECTED_KEYS - keys}"
        )
        assert keys <= ALLOWED_KEYS, (
            f"Profile '{name}' has unexpected keys: {keys - ALLOWED_KEYS}"
        )

    @pytest.mark.parametrize("name,weights", ALL_PROFILES.items())
    def test_all_weights_non_negative(self, name, weights):
        for key, val in weights.items():
            assert val >= 0.0, f"Profile '{name}' has negative weight for '{key}'"
