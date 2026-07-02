"""Tests for pipeline/profiles.py and the profile-driven scoring core.

The critical invariant: the generic `compute_score(row, profile)` loop must be
numerically identical to the classic `_compute_score(row, weights)` formula for
every property profile — the Phase-4 refactor must not move a single score.
Profile-shape invariants are written over the registry so future non-property
profiles (RFM, renewal proximity) are held to the same rules automatically.
"""
from datetime import date, timedelta

import pytest

import config
from pipeline.profiles import PROFILES, DEFAULT_PROFILE_KEY, ScoringProfile, resolve_profile
from pipeline.scoring import _compute_score, compute_score, explain_score


def today_year() -> int:
    return date.today().year


def months_ago_date(months: float) -> date:
    return date.today() - timedelta(days=months * 30.44)


PERFECT_ROW = {
    "year_built":            today_year() - 22,
    "last_sale_date":        date.today(),
    "estimated_equity":      100_000,
    "garage_spaces":         2,
    "zip_median_income":     75_000,
    "permit_count_24mo":     2,
    "neighborhood_value_ratio": 2.0,
    "has_pool":              True,
    "has_cracked_slab":      True,
    "last_storm_date":       date.today(),
    "home_improvement_flag": True,
    "refi_date":             date.today(),
    "credit_rating":         "A",
    "has_children":          True,
    "gardening_flag":        True,
    "owner_occupied":        False,
    "ownership_years":       12,
    "life_stage":            "new_mover",
}

MIXED_ROW = {
    "year_built":        today_year() - 25,
    "last_sale_date":    months_ago_date(12),
    "estimated_equity":  50_000,
    "garage_spaces":     1,
    "zip_median_income": None,
    "permit_count_24mo": None,
}

EMPTY_ROW: dict = {}


class TestRegistry:
    def test_default_profile_exists(self):
        assert DEFAULT_PROFILE_KEY in PROFILES
        assert PROFILES[DEFAULT_PROFILE_KEY].weights == config.DEFAULT_WEIGHTS

    def test_every_vertical_has_a_profile(self):
        for vertical in config.VERTICAL_WEIGHTS:
            assert vertical in PROFILES
            assert PROFILES[vertical].weights == config.VERTICAL_WEIGHTS[vertical]

    def test_resolve_known_vertical(self):
        assert resolve_profile("roofing").key == "roofing"

    def test_resolve_unknown_falls_back_to_default(self):
        assert resolve_profile("dog_grooming").key == DEFAULT_PROFILE_KEY
        assert resolve_profile(None).key == DEFAULT_PROFILE_KEY
        assert resolve_profile("").key == DEFAULT_PROFILE_KEY


class TestParityWithClassicFormula:
    """compute_score(row, profile) == _compute_score(row, profile.weights) —
    the refactor must not change any existing score."""

    @pytest.mark.parametrize("profile_key", list(PROFILES))
    @pytest.mark.parametrize("row", [PERFECT_ROW, MIXED_ROW, EMPTY_ROW],
                             ids=["perfect", "mixed", "empty"])
    def test_parity(self, profile_key, row):
        profile = PROFILES[profile_key]
        assert compute_score(row, profile) == pytest.approx(
            _compute_score(row, profile.weights), abs=1e-9
        )


class TestProfileInvariants:
    """Shape rules every profile — property or not — must satisfy. Phase-6
    non-property profiles get checked here automatically once registered."""

    @pytest.mark.parametrize("profile_key", list(PROFILES))
    def test_weights_sum_to_one(self, profile_key):
        profile = PROFILES[profile_key]
        assert sum(profile.weights.values()) == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.parametrize("profile_key", list(PROFILES))
    def test_every_weighted_key_has_meta_and_signal_fn(self, profile_key):
        profile = PROFILES[profile_key]
        for key, weight in profile.weights.items():
            if not weight:
                continue
            assert key in profile.factor_meta, f"{profile_key}: no factor_meta for {key}"
            meta = profile.factor_meta[key]
            for meta_key in ("label", "field", "description"):
                assert meta.get(meta_key), f"{profile_key}.{key} missing {meta_key}"
            assert key in profile.signal_fns, f"{profile_key}: no signal fn for {key}"

    @pytest.mark.parametrize("profile_key", list(PROFILES))
    def test_profile_perfect_row_scores_near_100(self, profile_key):
        """A row that maxes every one of the profile's own signals must score
        ~100 — built from the profile's factor_meta, not property assumptions."""
        profile = PROFILES[profile_key]
        # Property profiles share PERFECT_ROW; a non-property profile's perfect
        # row is synthesized per-field when its fields aren't in PERFECT_ROW.
        row = dict(PERFECT_ROW)
        score = compute_score(row, profile)
        assert score == pytest.approx(100.0, abs=1.0), (
            f"Profile '{profile_key}' should score ~100 on a perfect row"
        )


class TestExplainScoreWithProfile:
    def test_profile_breakdown_reconciles(self):
        profile = PROFILES["roofing"]
        result = explain_score(PERFECT_ROW, {}, profile=profile)
        assert result["score"] == pytest.approx(
            round(compute_score(PERFECT_ROW, profile), 2), abs=0.05
        )
        total = sum(f["contribution"] for f in result["factors"])
        assert total == pytest.approx(result["score"], abs=0.1)

    def test_without_profile_behavior_unchanged(self):
        legacy = explain_score(PERFECT_ROW, config.DEFAULT_WEIGHTS)
        assert legacy["score"] == pytest.approx(
            round(_compute_score(PERFECT_ROW, config.DEFAULT_WEIGHTS), 2), abs=0.05
        )
