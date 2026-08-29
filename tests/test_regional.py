"""
Tests for pipeline/regional.py — the market calibration layer.

Three things are being pinned here, in descending order of how expensive they
are to get wrong:

1. **A regional profile is still a valid profile.** Weights sum to 1.0, every
   key has metadata and a signal function, and a perfect row still scores ~100.
   A market that quietly produces a malformed profile breaks scoring for every
   account in it.
2. **Deltas mean what they say.** `scale` is relative and `set` is absolute, a
   scale naming a signal the base profile doesn't carry is a typo rather than a
   silent no-op, and the chain merges root-to-leaf.
3. **Only within-market discriminators carry weight.** The layer's whole
   discipline is that climate, electricity price and policy — real drivers of
   regional demand, identical for every lead in the market — never become
   scoring signals. `test_every_weighted_signal_reads_a_property_field` is the
   mechanical form of that rule.

No database, no network — same contract as tests/test_scoring.py.
"""
from datetime import date

import pytest

import config
from pipeline import regional, scoring
from pipeline.db import ALL_COLS
from pipeline.profiles import PROFILES, resolve_profile

REGIONS = sorted(config.REGIONAL_CALIBRATION_MATRIX)
CALIBRATED_REGIONS = [r for r in REGIONS if r != regional.NATIONAL]
PROPERTY_VERTICALS = [None, *sorted(config.VERTICAL_WEIGHTS)]


# A row that maxes every signal a regional property profile can weight. It is
# the national PERFECT_ROW with the occupancy flipped: `absentee` and
# `owner_occupied` read the same column and point opposite ways, so no single
# row can max both — which is precisely why no profile may weight both.
PERFECT_ROW = {
    "year_built":               date.today().year - 22,
    "last_sale_date":           date.today(),
    "estimated_equity":         1_000_000,
    "garage_spaces":            10,
    "zip_median_income":        1_000_000,
    "permit_count_24mo":        10,
    "neighborhood_value_ratio": 5.0,
    "has_pool":                 True,
    "has_cracked_slab":         True,
    "last_storm_date":          date.today(),
    "last_freeze_date":         date.today(),
    "hail_size_in":             10.0,
    "square_footage":           20_000,
    "home_improvement_flag":    True,
    "refi_date":                date.today(),
    "credit_rating":            "A",
    "has_children":             True,
    "gardening_flag":           True,
    "owner_occupied":           True,
    "ownership_years":          50,
    "life_stage":               "new_mover",
}

# Row fields a signal may read that are not `properties` columns because they
# are computed at score time rather than stored.
COMPUTED_ROW_FIELDS = {"neighborhood_value_ratio"}


def perfect_row_for(profile) -> dict:
    """PERFECT_ROW with the occupancy flag set the way THIS profile rewards.

    There is no single perfect row across profiles, and that is the point:
    `absentee` and `owner_occupied` read one column and point opposite ways, so
    a market that weights one must not also weight the other. Profiles that
    still score `absentee` (the national ones) want the investor answer;
    profiles calibrated for a majority-renter market want the resident.
    """
    row = dict(PERFECT_ROW)
    row["owner_occupied"] = not profile.weights.get("absentee")
    return row


# ── Region resolution ─────────────────────────────────────────────────────────

class TestRegionForZip:
    @pytest.mark.parametrize("zip_code,expected", [
        ("77002", "tx_houston"),   # downtown Houston
        ("77396", "tx_houston"),   # Humble
        ("77573", "tx_houston"),   # League City
        ("77706", "tx_houston"),   # Beaumont
        ("75201", "tx"),           # Dallas
        ("78701", "tx"),           # Austin
        ("79901", "tx"),           # El Paso
        ("88510", "tx"),           # the El Paso 885xx block
        ("60601", "us"),           # Chicago
        ("90210", "us"),           # Beverly Hills
        ("70112", "us"),           # New Orleans — adjacent Gulf, not calibrated
    ])
    def test_zip_maps_to_expected_region(self, zip_code, expected):
        assert regional.region_for_zip(zip_code) == expected

    @pytest.mark.parametrize("bad", [None, "", "7", "abcde", "  "])
    def test_unusable_zip_scores_nationally(self, bad):
        assert regional.region_for_zip(bad) == regional.NATIONAL

    def test_zip_with_padding_still_resolves(self):
        assert regional.region_for_zip("  77002  ") == "tx_houston"

    def test_zip_plus_four_resolves_on_the_prefix(self):
        assert regional.region_for_zip("77002-1234") == "tx_houston"

    def test_matching_state_is_accepted(self):
        assert regional.region_for_zip("77002", "TX") == "tx_houston"
        assert regional.region_for_zip("77002", "tx") == "tx_houston"

    def test_state_disagreeing_with_the_zip_falls_back_to_national(self):
        # A mistyped ZIP must not hand a Louisiana lead Texas hail calibration.
        assert regional.region_for_zip("77002", "LA") == regional.NATIONAL

    def test_state_is_ignored_for_uncalibrated_zips(self):
        # Nothing to cross-check against; national either way.
        assert regional.region_for_zip("60601", "IL") == regional.NATIONAL


class TestResolveRegion:
    def test_auto_derives_from_the_zip(self, monkeypatch):
        monkeypatch.setattr(config, "REGIONAL_CALIBRATION", "auto")
        assert regional.resolve_region("77002") == "tx_houston"

    def test_off_forces_national_everywhere(self, monkeypatch):
        monkeypatch.setattr(config, "REGIONAL_CALIBRATION", "off")
        assert regional.resolve_region("77002") == regional.NATIONAL
        assert regional.is_enabled() is False

    def test_an_explicit_region_pins_every_lead(self, monkeypatch):
        monkeypatch.setattr(config, "REGIONAL_CALIBRATION", "tx")
        assert regional.resolve_region("60601") == "tx"

    def test_an_unknown_setting_degrades_to_national(self, monkeypatch):
        # A typo in an env var must not stop the pipeline scoring.
        monkeypatch.setattr(config, "REGIONAL_CALIBRATION", "texas")
        assert regional.resolve_region("77002") == regional.NATIONAL


class TestRegionChain:
    def test_chain_is_root_first(self):
        assert regional.region_chain("tx_houston") == ["us", "tx", "tx_houston"]

    def test_national_chain_is_itself(self):
        assert regional.region_chain("us") == ["us"]

    def test_unknown_region_degrades_to_national(self):
        assert regional.region_chain("atlantis") == ["us"]

    @pytest.mark.parametrize("region", REGIONS)
    def test_every_region_reaches_the_national_root(self, region):
        assert regional.region_chain(region)[0] == regional.NATIONAL

    @pytest.mark.parametrize("region", REGIONS)
    def test_every_region_has_a_label(self, region):
        assert regional.label(region) and regional.label(region) != region


# ── Weight arithmetic ─────────────────────────────────────────────────────────

BASE = {"age": 0.5, "sale": 0.3, "equity": 0.2}


class TestApplyWeightSpec:
    def test_empty_spec_is_a_no_op(self):
        assert regional.apply_weight_spec(BASE, {}) == BASE

    def test_result_always_sums_to_one(self):
        out = regional.apply_weight_spec(BASE, {"scale": {"age": 2.0}})
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)

    def test_scale_is_relative_and_others_absorb_the_difference(self):
        out = regional.apply_weight_spec(BASE, {"scale": {"age": 2.0}})
        assert out["age"] > BASE["age"]
        assert out["sale"] < BASE["sale"]
        # Unscaled weights keep their ratio to each other (to within the 4-dp
        # rounding apply_weight_spec applies so weights stay human-readable).
        assert out["sale"] / out["equity"] == pytest.approx(
            BASE["sale"] / BASE["equity"], rel=1e-3)

    def test_scale_of_zero_removes_a_signal_without_breaking_the_sum(self):
        out = regional.apply_weight_spec(BASE, {"scale": {"equity": 0.0}})
        assert out["equity"] == 0.0
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)

    def test_set_lands_on_the_exact_share_requested(self):
        out = regional.apply_weight_spec(BASE, {"set": {"age": 0.4}})
        assert out["age"] == pytest.approx(0.4)

    def test_set_introduces_a_signal_the_base_profile_lacks(self):
        out = regional.apply_weight_spec(BASE, {"set": {"freeze": 0.1}})
        assert out["freeze"] == pytest.approx(0.1)
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)

    def test_unpinned_weights_keep_their_proportions(self):
        out = regional.apply_weight_spec(BASE, {"set": {"freeze": 0.2}})
        assert out["age"] / out["sale"] == pytest.approx(BASE["age"] / BASE["sale"])

    def test_key_order_is_base_profile_then_introduced(self):
        out = regional.apply_weight_spec(
            BASE, {"set": {"freeze": 0.1, "hail": 0.1}})
        assert list(out) == ["age", "sale", "equity", "freeze", "hail"]

    def test_scaling_an_absent_signal_raises_instead_of_no_opping(self):
        # The failure mode this guards: a typo'd or renamed signal silently
        # doing nothing, forever, in production.
        with pytest.raises(ValueError, match="absent from the base profile"):
            regional.apply_weight_spec(BASE, {"scale": {"storm": 1.5}})

    def test_pinning_the_whole_profile_raises(self):
        with pytest.raises(ValueError, match="nothing to rank on"):
            regional.apply_weight_spec(BASE, {"set": {"age": 0.6, "sale": 0.5}})

    def test_a_set_weight_outside_zero_to_one_raises(self):
        with pytest.raises(ValueError, match="must be in"):
            regional.apply_weight_spec(BASE, {"set": {"age": 1.5}})
        with pytest.raises(ValueError, match="must be in"):
            regional.apply_weight_spec(BASE, {"set": {"age": -0.1}})

    def test_zeroing_everything_unpinned_raises(self):
        with pytest.raises(ValueError, match="scaled every unpinned weight"):
            regional.apply_weight_spec(
                BASE, {"scale": {"age": 0.0, "sale": 0.0, "equity": 0.0}})

    def test_weights_are_rounded_for_human_review(self):
        out = regional.apply_weight_spec(BASE, {"scale": {"age": 1.37}})
        for weight in out.values():
            assert weight == round(weight, 6)


# ── Thresholds ────────────────────────────────────────────────────────────────

class TestThresholds:
    def test_national_states_no_overrides(self):
        assert regional.thresholds_for(regional.NATIONAL) == {}

    def test_child_region_inherits_the_parent(self):
        # tx sets EQUITY_TARGET; Houston does not restate it.
        assert regional.thresholds_for("tx_houston")["EQUITY_TARGET"] == \
            regional.thresholds_for("tx")["EQUITY_TARGET"]

    def test_child_region_overrides_the_parent(self):
        assert (regional.thresholds_for("tx_houston")["AGE_DECAY_FLOOR"]
                != regional.thresholds_for("tx")["AGE_DECAY_FLOOR"])

    def test_vertical_thresholds_override_the_regions(self):
        # Roofing states its own age floor; the region-wide one must not win.
        assert (regional.thresholds_for("tx_houston", "roofing")["AGE_DECAY_FLOOR"]
                != regional.thresholds_for("tx_houston")["AGE_DECAY_FLOOR"])

    @pytest.mark.parametrize("region", REGIONS)
    @pytest.mark.parametrize("vertical", PROPERTY_VERTICALS)
    def test_every_override_names_a_real_threshold(self, region, vertical):
        # thresholds_for raises on an unknown key; this walks the whole matrix
        # so a typo in config fails here rather than being silently ignored.
        assert set(regional.thresholds_for(region, vertical)) <= \
            set(scoring.DEFAULT_THRESHOLDS)

    def test_an_unknown_threshold_key_raises(self, monkeypatch):
        monkeypatch.setitem(config.REGIONAL_CALIBRATION_MATRIX, "us",
                            {"thresholds": {"COOLING_DEGREE_DAYS": 3000}})
        with pytest.raises(ValueError, match="unknown threshold"):
            regional.thresholds_for(regional.NATIONAL)

    def test_thresholds_actually_reach_the_signal_functions(self):
        national = resolve_profile("roofing")
        houston = resolve_profile("roofing", "tx_houston")
        # $120k of equity is full marks nationally ($100k target) and short of
        # it in Texas ($150k), because the market's median owner clears $100k.
        assert national.signal_fns["equity"](120_000) == 1.0
        assert houston.signal_fns["equity"](120_000) < 1.0


# ── Regional profiles ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("region", REGIONS)
@pytest.mark.parametrize("vertical", PROPERTY_VERTICALS)
class TestRegionalProfileInvariants:
    def test_weights_sum_to_one(self, region, vertical):
        profile = resolve_profile(vertical, region)
        assert sum(profile.weights.values()) == pytest.approx(1.0, abs=1e-6)

    def test_no_negative_weights(self, region, vertical):
        profile = resolve_profile(vertical, region)
        assert all(w >= 0 for w in profile.weights.values())

    def test_every_weighted_key_has_metadata_and_a_signal_fn(self, region, vertical):
        profile = resolve_profile(vertical, region)
        for key, weight in profile.weights.items():
            assert key in profile.factor_meta, f"{region}/{vertical}: {key} lacks FACTOR_META"
            assert key in profile.signal_fns, f"{region}/{vertical}: {key} lacks a signal fn"

    def test_perfect_row_still_scores_about_one_hundred(self, region, vertical):
        # The load-bearing invariant: a market may reweight signals, it may not
        # make the top of the scale unreachable.
        profile = resolve_profile(vertical, region)
        assert scoring.compute_score(perfect_row_for(profile), profile) == \
            pytest.approx(100.0, abs=1.0)

    def test_empty_row_scores_zero(self, region, vertical):
        profile = resolve_profile(vertical, region)
        assert scoring.compute_score({}, profile) == 0.0

    def test_no_profile_weights_both_occupancy_signals(self, region, vertical):
        # `absentee` and `owner_occupied` read the same column and disagree
        # about which way it points. Weighting both is not a compromise, it is
        # a profile that pays every lead the same regardless of the answer.
        weights = resolve_profile(vertical, region).weights
        assert not (weights.get("absentee") and weights.get("owner_occupied")), (
            f"{region}/{vertical} weights both absentee and owner_occupied"
        )

    def test_every_weighted_signal_reads_a_property_field(self, region, vertical):
        # The layer's central discipline, mechanically enforced: a weighted
        # signal must read something that VARIES between two homes in the same
        # market. Climate, electricity price and policy incentives are real
        # regional demand drivers and none of them have a per-property column —
        # weighting one would add a constant to every lead in the market and
        # reorder nothing. They belong in base_rate()/job_value_multiplier().
        profile = resolve_profile(vertical, region)
        for key, weight in profile.weights.items():
            if not weight:
                continue
            field = profile.factor_meta[key]["field"]
            assert field in ALL_COLS or field in COMPUTED_ROW_FIELDS, (
                f"{region}/{vertical}: signal {key!r} reads {field!r}, which is "
                f"not a per-property field — a market constant cannot be a weight"
            )


class TestProfileResolution:
    def test_no_region_returns_the_shared_national_profile(self):
        assert resolve_profile("roofing") is PROFILES["roofing"]

    def test_national_region_returns_the_shared_national_profile(self):
        assert resolve_profile("roofing", regional.NATIONAL) is PROFILES["roofing"]

    def test_regional_profiles_are_cached_not_rebuilt_per_call(self):
        # A pipeline run scores tens of thousands of rows through one profile;
        # rebuilding ~20 closures per row would be pure waste.
        assert resolve_profile("roofing", "tx") is resolve_profile("roofing", "tx")

    def test_an_unknown_vertical_falls_back_to_default_in_a_region_too(self):
        assert (resolve_profile("underwater-basket-weaving", "tx").key
                == resolve_profile(None, "tx").key)

    def test_non_property_profiles_are_never_regionalised(self):
        # Days-to-renewal has no geography.
        assert resolve_profile("insurance_renewal", "tx") is PROFILES["insurance_renewal"]
        assert resolve_profile("retail_rfm", "tx") is PROFILES["retail_rfm"]

    def test_the_profile_reports_its_market(self):
        profile = resolve_profile("hvac", "tx_houston")
        assert profile.region == "tx_houston"
        assert profile.region_label == config.REGION_LABELS["tx_houston"]


# ── The Texas calibration itself ──────────────────────────────────────────────

class TestTexasCalibration:
    def test_hvac_gains_a_freeze_signal_that_is_national_dead_weight(self):
        assert config.VERTICAL_WEIGHTS["hvac"].get("freeze", 0) == 0
        assert resolve_profile("hvac", "tx").weights["freeze"] > 0

    def test_roofing_gains_hail_severity_on_top_of_storm_recency(self):
        assert config.VERTICAL_WEIGHTS["roofing"].get("hail", 0) == 0
        texas = resolve_profile("roofing", "tx").weights
        assert texas["hail"] > 0 and texas["storm"] > 0

    def test_texas_replaces_absentee_with_owner_occupancy(self):
        # The research's sharpest deviation: at ~42% owner-occupancy in the City
        # of Houston, occupancy is near-evenly split — maximum discriminative
        # power — and landlord stock price-shops the same job.
        assert config.VERTICAL_WEIGHTS["roofing"]["absentee"] > 0
        texas = resolve_profile("roofing", "tx").weights
        assert texas["absentee"] == 0
        assert texas["owner_occupied"] > 0

    def test_solar_moves_from_rate_driven_to_usage_driven(self):
        national = resolve_profile("solar").weights
        texas = resolve_profile("solar", "tx").weights
        # Consumption proxies appear; area income (a bill-size proxy at best)
        # loses share to them.
        assert texas["home_size"] > 0 and texas["pool"] > 0
        assert texas["income"] < national["income"]

    def test_solar_wants_a_younger_roof_than_the_other_trades(self):
        # Panels need a roof with life left; Houston's 1990s stock needs
        # re-roofing first. Solar's age curve must peak earlier than roofing's.
        solar = regional.thresholds_for("tx", "solar")
        assert solar["AGE_SWEET_SPOT_MAX"] < config.AGE_SWEET_SPOT_MAX

    def test_hvac_ages_faster_in_calendar_years(self):
        # The doc's "effective component age": a 9-month cooling season, so
        # replacement propensity peaks 1–3 years earlier than nationally.
        assert regional.thresholds_for("tx", "hvac")["AGE_RUNTIME_FACTOR"] > 1.0

    def test_old_houston_stock_is_not_written_off(self):
        # The national curve decays a 1989 build — the Houston median — toward
        # nothing. Houston's floors it well above the national value.
        year_built = 1989
        national = resolve_profile(None).signal_fns["age"]
        houston = resolve_profile(None, "tx_houston").signal_fns["age"]
        assert houston(year_built) > national(year_built)
        assert houston(1930) > 0

    def test_the_age_floor_does_not_flatten_the_whole_old_stock(self):
        # A floor alone would tie every pre-1983 home at one number. The point
        # of the slower decay is that they stay ordered.
        age = resolve_profile(None, "tx_houston").signal_fns["age"]
        assert age(1995) > age(1985) > age(1975) > age(1965)

    def test_garage_and_equity_targets_move_off_the_market_median(self):
        # Both national targets saturate for the median Texas home, which is a
        # signal with no ranking information left in it.
        texas = regional.thresholds_for("tx")
        assert texas["GARAGE_TARGET"] > config.GARAGE_TARGET
        assert texas["EQUITY_TARGET"] > config.EQUITY_TARGET

    def test_hail_target_rises_to_golf_ball_size(self):
        assert regional.thresholds_for("tx")["STORM_HAIL_TARGET_IN"] > \
            config.STORM_HAIL_TARGET_IN


# ── Market priors ─────────────────────────────────────────────────────────────

class TestMarketPriors:
    def test_job_value_multiplier_defaults_to_neutral(self):
        assert regional.job_value_multiplier(regional.NATIONAL, "roofing") == 1.0
        assert regional.job_value_multiplier("tx", "roofing") == 1.0

    def test_houston_raises_the_two_tickets_the_research_separates(self):
        assert regional.job_value_multiplier("tx_houston", "landscaping") > 1.0
        assert regional.job_value_multiplier("tx_houston", "epoxy_flooring") > 1.0

    def test_no_vertical_has_no_multiplier(self):
        assert regional.job_value_multiplier("tx_houston", None) == 1.0

    def test_base_rates_inherit_and_override(self):
        assert regional.base_rate("tx", "roofing") > regional.base_rate("us", "roofing")
        # Houston states none of its own and inherits Texas's.
        assert regional.base_rate("tx_houston", "roofing") == regional.base_rate("tx", "roofing")

    def test_solar_base_rate_tracks_the_nation(self):
        # Texas is #1 in installations and only #4 residential — utility-scale
        # dominates the headline, so the per-home rate does not move.
        assert regional.base_rate("tx", "solar") == regional.base_rate("us", "solar")

    def test_an_unknown_vertical_has_no_base_rate(self):
        assert regional.base_rate("tx", "underwater-basket-weaving") is None
        assert regional.base_rate("tx", None) is None

    @pytest.mark.parametrize("region", REGIONS)
    def test_base_rates_are_plausible_annual_incidences(self, region):
        for vertical, rate in regional._merge(region, "base_rates").items():
            assert 0.0 < rate < 1.0, f"{region}/{vertical} base rate {rate} is not a share"
