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
