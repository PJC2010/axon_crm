"""Tests for pipeline/job_value.py — pure job-value estimation (no DB/network)."""
import config
from pipeline.job_value import estimate_job_value


def test_no_inputs_returns_none():
    assert estimate_job_value({}, "roofing") is None
    assert estimate_job_value({}, None) is None


def test_per_sqft_vertical():
    # roofing: base 3000 + 4.5 * sqft
    row = {"square_footage": 2000}
    assert estimate_job_value(row, "roofing") == int(3000 + 4.5 * 2000)


def test_per_garage_vertical():
    # epoxy_flooring: base 800 + 1800 * garage_spaces
    row = {"garage_spaces": 2}
    assert estimate_job_value(row, "epoxy_flooring") == int(800 + 1800 * 2)


def test_per_lot_sqft_vertical():
    # fencing: base 1500 + 0.4 * lot_size
    row = {"lot_size": 7000}
    assert estimate_job_value(row, "fencing") == int(1500 + 0.4 * 7000)


def test_pool_gated_vertical_requires_pool():
    model = config.JOB_VALUE_MODEL["pool_maintenance"]
    expected = int(model.get("base", 0) + model.get("pool_value", 0))
    assert estimate_job_value({"has_pool": True}, "pool_maintenance") == expected


def test_pool_gated_without_pool_falls_back_to_value():
    # No pool → vertical model doesn't apply → generic value fallback.
    row = {"has_pool": False, "estimated_value": 400_000}
    assert estimate_job_value(row, "pool_maintenance") == \
        int(400_000 * config.JOB_VALUE_FALLBACK_PCT)


def test_generic_fallback_when_no_vertical():
    row = {"estimated_value": 500_000}
    assert estimate_job_value(row, None) == \
        int(500_000 * config.JOB_VALUE_FALLBACK_PCT)


def test_generic_fallback_when_vertical_inputs_missing():
    # roofing model needs square_footage; absent → fall back to value fraction.
    row = {"estimated_value": 250_000}
    assert estimate_job_value(row, "roofing") == \
        int(250_000 * config.JOB_VALUE_FALLBACK_PCT)


def test_unknown_vertical_uses_generic_fallback():
    row = {"estimated_value": 300_000, "square_footage": 2000}
    assert estimate_job_value(row, "not_a_real_vertical") == \
        int(300_000 * config.JOB_VALUE_FALLBACK_PCT)


def test_result_is_non_negative_int():
    val = estimate_job_value({"square_footage": 1500}, "hvac")
    assert isinstance(val, int) and val >= 0


# ── Regional ticket multiplier ────────────────────────────────────────────────

def test_multiplier_defaults_to_neutral():
    row = {"square_footage": 2000}
    assert estimate_job_value(row, "roofing") == \
        estimate_job_value(row, "roofing", multiplier=1.0)


def test_multiplier_scales_a_vertical_model_estimate():
    row = {"square_footage": 2000}
    base = estimate_job_value(row, "roofing")
    assert estimate_job_value(row, "roofing", multiplier=1.25) == \
        int(round(base * 1.25))


def test_multiplier_also_scales_the_generic_fallback():
    # The branch most leads actually take — a market's ticket adjustment has to
    # reach it, or the multiplier only moves the minority with full inputs.
    row = {"estimated_value": 400_000}
    base = estimate_job_value(row, None)
    assert estimate_job_value(row, None, multiplier=1.25) == int(round(base * 1.25))


def test_multiplier_cannot_conjure_an_estimate_from_nothing():
    assert estimate_job_value({}, "roofing", multiplier=5.0) is None


def test_houston_epoxy_ticket_is_above_the_baseline_model():
    # >75% year-round humidity pushes jobs toward moisture-barrier systems,
    # which sit above the bare-epoxy ticket JOB_VALUE_MODEL assumes.
    from pipeline import regional
    row = {"garage_spaces": 2}
    national = estimate_job_value(
        row, "epoxy_flooring",
        multiplier=regional.job_value_multiplier("us", "epoxy_flooring"))
    houston = estimate_job_value(
        row, "epoxy_flooring",
        multiplier=regional.job_value_multiplier("tx_houston", "epoxy_flooring"))
    assert houston > national
    # Still inside the $3,000–$15,000 band the research reports for Texas.
    assert 3_000 <= houston <= 15_000
